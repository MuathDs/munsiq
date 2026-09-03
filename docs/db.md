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

## The bypass caveat — read before trusting isolation

Measured against this project's Supabase instance:

```
current_user : postgres
rolsuper     : false
rolbypassrls : true      <-- bypasses RLS unconditionally
```

`postgres` is not a superuser here, but it carries `BYPASSRLS`, and `FORCE` does
not override that. **Today, RLS does not constrain the application's own
connection.** The policies are correct and enforced for every non-bypassing
role; they are simply not reached by this one.

That is a deliberate, temporary trade-off — see "Deferred: dedicated application
role" below — and it is why the isolation tests are written the way they are.

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

## Deferred: dedicated application role

The execution plan calls for a non-superuser application role that RLS applies
to, with the app never connecting as the table owner. **Not built.** Supabase
provisions its own `postgres` role and a connection pooler, and wiring a custom
role through the pooler is more complexity than this portfolio project needs
right now.

Consequences, stated plainly:

- Tenant isolation is enforced by the database for any non-bypassing role, and
  is proven under `authenticated` by the test suite.
- It is **not** enforced for the application's current connection. Today the
  app's own correctness — always setting the GUC, never deriving `org_id` from
  user input — is what separates tenants on that path. RLS is defence in depth
  that is not yet reached.
- This must be closed before the system holds data belonging to anyone other
  than the developer.

Closing it means: create a `LOGIN` role without `BYPASSRLS`, `GRANT` it DML on
the application tables, point `DATABASE_URL` at it, and keep running migrations
as `postgres`. The RLS policies themselves need no change — they already work,
as the tests under `authenticated` demonstrate.

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
