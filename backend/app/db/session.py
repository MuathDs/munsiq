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

A second caveat specific to this deployment: the application connects to
Supabase as ``postgres``, which carries BYPASSRLS. RLS policies do not constrain
that role, so the GUC below is necessary but NOT sufficient today. See
docs/db.md — the mitigation is FORCE ROW LEVEL SECURITY plus a dedicated
non-bypassing role, the latter of which is still deferred.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker

ORG_GUC = "app.current_org_id"


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
    """Open a transaction with the RLS GUC set for ``org_id``."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
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
