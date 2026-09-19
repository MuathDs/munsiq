# ADR 004 — RLS with FORCE, and a negative control that proves it

**Status:** Accepted · **Date:** 2026-09-19 (recorded; decided during Phase 2)

## Context

This is a multi-tenant system holding other companies' invoices: VAT
registrations, bank details, supplier relationships, prices. A cross-tenant leak
is not a bug report, it is a notifiable incident.

Application-level scoping — remembering a `WHERE org_id = :org` in every query —
fails the moment somebody forgets one. And a test that asserts isolation can
pass for the wrong reason: if the test's own setup silently stops seeing rows,
"no leak" and "no data" look identical.

## Decision

Enforce isolation in the database, and prove the proof.

* Every org-scoped table carries `org_id`, has RLS `ENABLE`d **and** `FORCE`d,
  and one policy comparing `org_id` with `current_setting('app.current_org_id')`.
  Measured: 17 of 17 such tables, 18 policies.
* `FORCE` matters because plain `ENABLE` does not constrain a table's owner.
  Without it the policies would be decorative for exactly the role migrations
  run as.
* Supabase's `postgres` role carries `BYPASSRLS`, which `FORCE` does not
  override. So `session_scope()` issues `SET LOCAL ROLE` to a non-bypassing
  role (`authenticated`) in the same transaction as the GUC. Both are
  transaction-local, so a connection returned to the pool carries neither.
* The API layer contains **no** `org_id` filter at all — deliberately. If RLS
  stopped working, the endpoints would return every tenant's rows and the tests
  would fail. The endpoint has no second line of defence, so the test measures
  RLS and nothing else.
* The tenant id comes only from a verified identity, never from a request body,
  query parameter or header. Until JWT auth lands, `get_current_org_id` raises
  501 rather than guessing, and the frontend holds the identity server-side.
* **The negative control.** `test_postgres_role_bypasses_rls_control` asserts
  that the bypassing role *does* see both tenants. It is not asserting a bug is
  correct: it is the control that gives the isolation tests their meaning. If it
  ever starts passing isolation, the setup has stopped inserting data and the
  green suite is a lie.

## Consequences

**Good.** Isolation holds for code nobody has written yet. Tests exercise the
real ASGI app, the real router, the real session dependency and the real
policies over HTTP.

**Bad / limits.**

* The connection still *authenticates* as a `BYPASSRLS` role; a session opened
  outside `session_scope()` would run unconstrained. A dedicated low-privilege
  LOGIN role makes the bypass unreachable rather than merely unused — deferred,
  with the steps in `docs/db.md`.
* Alembic must never inherit the role switch: `authenticated` cannot run DDL,
  so `alembic/env.py` builds its own engine on purpose.
* Every query pays a policy check. Not measured as a problem at this scale.

## See also

`app/db/session.py`, `backend/tests/test_rls.py`,
`backend/tests/test_api_tenancy.py`, `docs/db.md`.
