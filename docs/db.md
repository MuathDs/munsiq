# Database & tenant isolation

Postgres 17 on Supabase. Schema managed by Alembic, tenant isolation enforced by
Row-Level Security.

## The short version

Every org-scoped table has `org_id`, RLS `ENABLE`d **and** `FORCE`d, and one
policy matching `org_id` against `current_setting('app.current_org_id')`. The
application sets that GUC per transaction from a verified JWT claim and from
nothing else.

There is one significant caveat, documented in full below: the role the
application currently connects as bypasses RLS.

## Why `FORCE ROW LEVEL SECURITY`, not just `ENABLE`

RLS in Postgres does not constrain everyone equally:

| Who | Constrained by RLS? |
| --- | --- |
| An ordinary role | Yes |
| The **table's owner** | **No** — unless the table is `FORCE`d |
| A **superuser** or a role with **`BYPASSRLS`** | **No** — `FORCE` does not help |

Alembic creates these tables as `postgres`, which makes `postgres` their owner.
Had we only `ENABLE`d RLS, every policy would exist, look correct in the schema,
and be silently skipped for the exact role the application connects as. `FORCE`
removes the owner exemption. It is applied to all 18 protected tables.

## The bypass caveat — closed

Measured against this project's Supabase instance:

```
current_user : postgres
rolsuper     : false
rolbypassrls : true      <-- bypasses RLS unconditionally
```

`postgres` is not a superuser here, but it carries `BYPASSRLS`, and `FORCE` does
not override that. Connecting as this role and setting only the GUC would leave
the application *adjacent* to RLS rather than subject to it.

**This is now closed at the session layer.** `session_scope()` issues
`SET LOCAL ROLE authenticated` in the same transaction as the GUC, before any
query runs. Both statements are transaction-local, so the elevated connection
role returns on commit or rollback and cannot leak to the next checkout from the
pool. The role is `settings.DB_APP_ROLE` (default `authenticated`); setting it to
`""` disables the switch, which is only correct if `DATABASE_URL` already points
at a non-bypassing role.

The connection still authenticates as `postgres` — that has not changed, and a
dedicated login role is still the cleaner end state (below). What changed is that
no application query now *executes* as a bypassing role.

### Evidence, not assertion

Same connection, same query, same GUC, two seeded tenants — only the effective
role differs:

| | executing as | `rolbypassrls` | rows visible |
| --- | --- | --- | --- |
| No `SET ROLE` | `postgres` | true | **2 of 2** |
| After `SET LOCAL ROLE authenticated` | `authenticated` | false | **1 of 2** |

And over HTTP, with the role switch disabled (`DB_APP_ROLE=""`), the API-level
test fails exactly as it should:

```
AssertionError: tenant B's annotation was returned to tenant A over HTTP
                — the request path is not constrained by RLS
```

Filtering appears precisely when the role stops bypassing RLS. The isolation is
produced by RLS and by nothing else.

For reference, the roles on this instance:

| Role | superuser | `BYPASSRLS` | Safe to run isolation tests as |
| --- | --- | --- | --- |
| `postgres` (app connects as) | no | **yes** | no |
| `service_role` | no | **yes** | no |
| `supabase_admin` | **yes** | **yes** | no |
| `authenticated` | no | no | **yes** |
| `anon` | no | no | yes |

## How the isolation test avoids being a false positive

`backend/tests/test_rls.py` never asserts isolation as `postgres`. Each
assertion opens a transaction and issues `SET LOCAL ROLE authenticated` — a role
Supabase already provisions, with no superuser and no `BYPASSRLS` — before
querying. No new role is created.

The suite also carries two guards on its own validity:

- `test_postgres_role_bypasses_rls_control` asserts that the *same* query as
  `postgres` returns **both** tenants' rows. If that ever starts showing
  isolation, the test setup has stopped measuring what it claims to, and the
  passing isolation tests would be meaningless.
- `test_the_test_role_does_not_bypass_rls` asserts `authenticated` still has
  neither flag, so a Supabase-side change to that role fails the suite loudly
  instead of quietly hollowing it out.

Plus two drift guards: every org-scoped table in the ORM must have RLS enabled
*and* forced, and must have a policy. Adding a model with an `org_id` and
forgetting the migration fails the suite.

## Isolation over the HTTP request path

`backend/tests/test_api_tenancy.py` proves the *application* is subject to RLS,
not just that the policies work when queried directly. Requests go through the
real ASGI app, router, session dependency, role switch and policies.

The only substituted piece is `get_current_org_id` — the JWT claim reader, which
does not exist until auth lands. Tests override it via
`app.dependency_overrides`, standing in for the token a real caller would
present. Everything downstream is production code.

Two properties make that test meaningful:

- **The endpoints contain no `org_id` filter at all.** `app/api/annotations.py`
  issues `SELECT ... FROM annotations` with no tenant predicate. There is no
  second line of defence, so if RLS stopped working the test would see both
  tenants and fail.
- **The unauthenticated case is asserted too.** With no override, the real
  dependency runs and must return 501. It deliberately has no fallback to a
  header, query parameter or "default org": that value feeds the RLS GUC
  directly, so accepting a caller-supplied one would let anyone choose which
  tenant to read.

## Grants required by the application role

Audited before anything was granted; `authenticated` already had everything:

| Layer | Status |
| --- | --- |
| `USAGE` on schema `public` | present |
| `SELECT/INSERT/UPDATE/DELETE` on all 19 tables | present (granted by the initial migration) |
| `USAGE` on `audit_log_id_seq`, `field_corrections_id_seq` | present |

The sequence grants come from Supabase's default privileges rather than our
migration. On a non-Supabase Postgres, a `BIGSERIAL` insert as the application
role would fail with a permission error until those are granted explicitly —
worth remembering when the dedicated role below is created.

`test_app_session_can_insert_and_update` covers INSERT, UPDATE and a `BIGSERIAL`
insert through `session_scope`, so a missing sequence grant surfaces in the test
suite rather than in production.

## Migrations keep the owner role

Alembic must NOT inherit the role switch — `authenticated` has no `CREATE` on
`public`, so DDL as that role fails. `alembic/env.py` builds its own engine via
`app.db.base.make_engine` and never touches `session_scope`, which keeps the two
paths separate.

`test_migration_path_does_not_inherit_the_app_role` asserts the raw engine path
is not the application role and still holds `CREATE` on `public`, so moving the
switch into `make_engine` or a connect event would fail the suite instead of
breaking every future migration.

Verified after the change: `downgrade base` → `upgrade head` round-trips
cleanly, and `alembic check` reports no drift.

## Deferred: dedicated application role

The execution plan calls for a non-superuser application role that RLS applies
to, with the app never connecting as the table owner. **Not built.** Supabase
provisions its own `postgres` role and a connection pooler, and wiring a custom
role through the pooler is more complexity than this portfolio project needs
right now.

Consequences, as they now stand:

- Tenant isolation **is** enforced by the database on the application path, via
  `SET LOCAL ROLE authenticated` in `session_scope()`, and is proven end to end
  over HTTP by `tests/test_api_tenancy.py`.
- What remains is narrower than it was: the connection still *authenticates* as
  a `BYPASSRLS` role, so a code path that opened a session without going through
  `session_scope()` would run unconstrained. The mitigation is convention plus
  tests, not the database.
- A dedicated login role removes that last gap by making the bypass unreachable
  rather than merely unused.

Closing it means: create a `LOGIN` role without `BYPASSRLS`, `GRANT` it DML on
the application tables **and `USAGE` on the sequences**, point `DATABASE_URL` at
it, keep running migrations as `postgres`, and set `DB_APP_ROLE=""` so no
redundant switch happens. The RLS policies themselves need no change.

## Tables not covered by RLS, on purpose

- **`users`** — a person is global, not org-scoped. One user may belong to
  several organizations; `memberships` (which *is* org-scoped and protected) is
  what binds them. Putting an `org_id` on `users` would misrepresent the model.
- **`alembic_version`** — migration bookkeeping, no tenant data.

`organizations` has no `org_id` either, but *is* protected: its policy matches
on `id`, because the tenant list is itself something a tenant should not see.

## The GUC contract

`app/db/session.py` is the only place the GUC is set.

```sql
SELECT set_config('app.current_org_id', $1, true)   -- true = transaction-local
```

Two properties matter:

- **Transaction-local.** The value cannot leak into the next checkout of a
  pooled connection.
- **Parameter-bound, not interpolated.** `set_config()` takes the value as data.
  Formatting a GUC into a SQL string would open an injection path directly into
  the tenant boundary.

`get_session_for_request` is the only dependency application code may use, and
its `org_id` must come from a verified JWT claim. Any code path that sets
`org_id` from a request body, query parameter, header, or path segment is a
security bug, not a shortcut.

## Schema notes

- 19 tables; 17 carry `org_id`, plus `organizations` protected on `id`.
- UUID primary keys via `gen_random_uuid()` (pgcrypto).
- All timestamps `TIMESTAMPTZ`, stored UTC. Money `NUMERIC(18,4)`, confidence
  `NUMERIC(5,4)` — never float.
- Defaults are **server-side**, not Python-side, so an insert that bypasses the
  ORM still gets them. (This was a real bug caught by the isolation test: raw
  SQL inserts hit a NOT NULL violation on `organizations.data_region`.)
- `document_parts` exists but nothing populates it yet. It is here now because
  one emailed PDF routinely holds an invoice plus a delivery note plus a
  purchase order, and retrofitting the table once annotations exist means a data
  migration rather than a feature.

## Running migrations

```bash
cd backend
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check        # fails on model/schema drift
.venv/Scripts/python.exe -m pytest tests/test_rls.py -v
```

`alembic downgrade base` is verified to round-trip cleanly. Order matters in
`downgrade()`: policies drop before their tables, enum types drop after, or
Postgres refuses with `DependentObjectsStillExist`.

`DATABASE_URL` is read from `backend/.env` by `alembic/env.py` via
pydantic-settings, so no credential appears in `alembic.ini` or any tracked
file. Either `postgresql://` or `postgresql+asyncpg://` works;
`Settings.async_database_url` normalizes it.
