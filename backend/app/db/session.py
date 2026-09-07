"""Session dependencies that carry the tenant identity into Postgres.

SECURITY — read this before touching anything here.

Tenant isolation in Munsiq is enforced by Postgres RLS, and every policy reads
``current_setting('app.current_org_id')``. That GUC is therefore the *entire*
security boundary: whatever value reaches it is the tenant whose data the
request can see.

Consequently:

* ``get_session_for_request`` is the ONLY dependency application code may use.
  It derives org_id from a verified JWT claim and nothing else.
* Any code path that sets org_id from a request body, query parameter, header,
  path segment, or any other user-controllable input is a SECURITY BUG, not a
  convenience. It hands the caller the ability to read another tenant's data.
* ``get_session`` takes an explicit org_id and exists for workers, migrations
  and tests — callers that already hold a trusted org_id. It is deliberately
  not wired to FastAPI's dependency system.

The application connects to Supabase as ``postgres``, which carries BYPASSRLS.
A BYPASSRLS role is not constrained by RLS at all — not even with FORCE ROW
LEVEL SECURITY — so setting the GUC alone would leave the app's own path
*adjacent* to RLS rather than subject to it.

``session_scope`` therefore also issues ``SET LOCAL ROLE`` to
``settings.DB_APP_ROLE`` (default ``authenticated``, a role Supabase already
provisions with neither superuser nor BYPASSRLS). Both statements are
transaction-local, so the elevated connection role is restored on commit or
rollback and cannot leak to the next checkout from the pool.

Alembic deliberately does NOT go through here — alembic/env.py builds its own
engine from app.db.base.make_engine, so migrations keep the owner role they need
to create and alter objects. Do not "helpfully" route migrations through
session_scope; DDL as ``authenticated`` will fail.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker

ORG_GUC = "app.current_org_id"

# Role names are identifiers and cannot be parameterized, so they are validated
# against this pattern before interpolation. The value comes from settings, not
# from a request, but an injectable identifier is not a risk worth carrying.
_SAFE_ROLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


async def _set_app_role(session: AsyncSession) -> None:
    """Drop from the connection role to the RLS-constrained application role.

    SET LOCAL scopes this to the transaction. An empty DB_APP_ROLE disables the
    switch, which is the escape hatch if the deployment already connects as a
    non-bypassing role and has no need to downgrade further.
    """
    role = get_settings().DB_APP_ROLE.strip()
    if not role:
        return
    if not _SAFE_ROLE.match(role):
        raise ValueError(f"DB_APP_ROLE is not a valid SQL identifier: {role!r}")
    await session.execute(text(f"SET LOCAL ROLE {role}"))


async def _set_org_guc(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Bind the tenant to the current transaction.

    SET LOCAL scopes the value to this transaction, so it cannot leak to the
    next checkout of a pooled connection. The value is bound as a parameter
    rather than interpolated: set_config() takes it as data, closing the SQL
    injection path that string-formatting a GUC would open.
    """
    await session.execute(
        text("SELECT set_config(:guc, :value, true)"),
        {"guc": ORG_GUC, "value": str(org_id)},
    )


@asynccontextmanager
async def session_scope(org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Open a transaction bound to ``org_id`` AND constrained by RLS.

    Order matters only in that both must happen before any query: the role
    switch makes RLS apply, the GUC tells the policies which tenant this is.
    Setting the GUC first would be equally correct; doing the role first means
    no statement in this transaction ever runs unconstrained.
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        await _set_app_role(session)
        await _set_org_guc(session, org_id)
        yield session


async def get_session(org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Async session bound to an explicit, already-trusted org_id.

    For workers and tests. NOT for request handling — see the module docstring.
    """
    async with session_scope(org_id) as session:
        yield session


async def get_session_for_request(org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Async session for HTTP handlers. org_id comes from the verified JWT ONLY.

    The JWT dependency lands in a later phase; until then this signature exists
    so no handler is tempted to invent its own tenant plumbing. When auth is
    wired, ``org_id`` must be supplied by the token-verification dependency and
    must never be reachable from user-controlled request data.
    """
    async with session_scope(org_id) as session:
        yield session
