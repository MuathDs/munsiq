"""Request-scoped dependencies.

The tenant-identity seam lives here. Everything downstream — every session,
every query — inherits whatever ``get_current_org_id`` returns, so this is the
one function whose correctness decides tenant isolation on the request path.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import session_scope


async def get_current_org_id() -> uuid.UUID:
    """Return the caller's org_id, from a verified JWT claim and nothing else.

    NOT IMPLEMENTED YET. JWT verification lands with auth in a later phase, and
    until then this raises rather than guessing.

    It deliberately does not fall back to a header, query parameter or body
    field. Any of those would be attacker-controlled, and since the value is
    fed straight into the RLS GUC, accepting one would let a caller select
    which tenant's data to read. A 501 is the correct behaviour here; a
    convenient default is a vulnerability.

    Tests exercise the request path by overriding this dependency via
    ``app.dependency_overrides`` — that substitutes only the identity source,
    leaving the router, the session dependency, the role switch and the RLS
    policies exactly as they run in production.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Authentication is not wired yet; org_id must come from a verified JWT.",
    )


async def get_tenant_session(
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> AsyncIterator[AsyncSession]:
    """An RLS-constrained session bound to the caller's tenant.

    This is the only session dependency handlers may use.
    """
    async with session_scope(org_id) as session:
        yield session
