"""Request-scoped dependencies.

The tenant-identity seam lives here. Everything downstream — every session,
every query — inherits whatever ``get_current_org_id`` returns, so this is the
one function whose correctness decides tenant isolation on the request path.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import session_scope

logger = logging.getLogger(__name__)


def get_app_settings() -> Settings:
    """Settings as a dependency, so create_app() can inject a different set.

    Reading the module-level singleton directly would mean an injected Settings
    governed routing but not the dependencies underneath it — half-configured,
    and impossible to test without mutating global state.
    """
    return get_settings()


ORG_HEADER = "X-Munsiq-Org"
SECRET_HEADER = "X-Munsiq-BFF-Secret"


async def get_current_org_id(
    x_munsiq_org: str | None = Header(default=None, alias=ORG_HEADER),
    x_munsiq_bff_secret: str | None = Header(default=None, alias=SECRET_HEADER),
    settings: Settings = Depends(get_app_settings),
) -> uuid.UUID:
    """Return the caller's org_id.

    REAL AUTHENTICATION IS NOT BUILT YET. When it is, this reads a verified JWT
    claim and the whole header path below disappears.

    Until then a trusted BFF may assert the tenant, because Next.js holds the
    identity server-side and the browser never sends one. Read the conditions
    carefully — the assertion is accepted ONLY when all of these hold:

    1. ``TRUSTED_BFF_ENABLED`` is on. Off by default.
    2. ``TRUSTED_BFF_SECRET`` is configured. No default value exists.
    3. The caller presents that exact secret, compared in constant time.

    With any of those missing this raises 501, exactly as it did before the BFF
    existed. That is what keeps the hard rule intact: a browser cannot choose
    its own tenant, because a browser does not have the secret. The header is
    not "tenant identity read from a request" in the sense the rule forbids —
    it is a service-to-service assertion from an authenticated peer, which is
    what a BFF is.

    This is a scaffold, and it is deliberately hard to turn on by accident.
    """
    if settings.TRUSTED_BFF_ENABLED and settings.TRUSTED_BFF_SECRET:
        if not x_munsiq_bff_secret or not hmac.compare_digest(
            x_munsiq_bff_secret, settings.TRUSTED_BFF_SECRET
        ):
            # Wrong or absent secret: refuse rather than fall through to 501,
            # so a misconfigured caller gets a distinct, actionable failure.
            logger.warning("auth.bff_secret_rejected")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid BFF credentials.",
            )
        if not x_munsiq_org:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{ORG_HEADER} is required when using the trusted BFF path.",
            )
        try:
            return uuid.UUID(x_munsiq_org)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{ORG_HEADER} is not a valid UUID.",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Authentication is not wired yet; org_id must come from a verified JWT "
            "or a trusted BFF."
        ),
    )


async def get_tenant_session(
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> AsyncIterator[AsyncSession]:
    """An RLS-constrained session bound to the caller's tenant.

    This is the only session dependency handlers may use.
    """
    async with session_scope(org_id) as session:
        yield session
