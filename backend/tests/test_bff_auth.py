"""The trusted-BFF identity path.

This is a scaffold for deferred authentication, which makes it exactly the kind
of code that quietly becomes a hole. These tests pin the conditions:

* off by default — a request with no credentials gets 501, as before;
* a browser cannot assert a tenant, because it does not hold the secret;
* the flag alone is not enough, and the secret alone is not enough.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

SECRET = "test-bff-secret-value"
ORG = str(uuid.uuid4())


def app_with(**overrides: object) -> object:
    return create_app(Settings(DEBUG_ENDPOINTS=False, DATABASE_URL="", **overrides))  # type: ignore[arg-type]


async def call(app: object, headers: dict[str, str] | None = None) -> int:
    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/annotations", headers=headers or {})
    return response.status_code


# --------------------------------------------------------------------------- #
# Off by default
# --------------------------------------------------------------------------- #
async def test_without_the_flag_the_endpoint_is_501() -> None:
    """The default posture is unchanged: no identity source, no access."""
    assert await call(app_with()) == 501


async def test_headers_alone_do_not_grant_access() -> None:
    """A browser sending its own headers must get nowhere.

    This is the property the hard rule protects: tenant identity is never
    accepted just because a caller supplied it.
    """
    status = await call(
        app_with(),
        {"X-Munsiq-Org": ORG, "X-Munsiq-BFF-Secret": SECRET},
    )
    assert status == 501


async def test_the_flag_without_a_secret_is_inert() -> None:
    """Enabling the flag but leaving the secret empty must not open the door."""
    status = await call(
        app_with(TRUSTED_BFF_ENABLED=True, TRUSTED_BFF_SECRET=""),
        {"X-Munsiq-Org": ORG, "X-Munsiq-BFF-Secret": ""},
    )
    assert status == 501


# --------------------------------------------------------------------------- #
# Enabled: the secret is what authenticates
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "secret",
    ["", "wrong-secret", "test-bff-secret-valu", "test-bff-secret-value-extra"],
)
async def test_a_wrong_secret_is_rejected(secret: str) -> None:
    status = await call(
        app_with(TRUSTED_BFF_ENABLED=True, TRUSTED_BFF_SECRET=SECRET),
        {"X-Munsiq-Org": ORG, "X-Munsiq-BFF-Secret": secret},
    )
    assert status == 401


async def test_a_missing_secret_is_rejected() -> None:
    status = await call(
        app_with(TRUSTED_BFF_ENABLED=True, TRUSTED_BFF_SECRET=SECRET),
        {"X-Munsiq-Org": ORG},
    )
    assert status == 401


async def test_the_right_secret_without_an_org_is_a_400() -> None:
    """An authenticated peer that forgets the tenant gets an actionable error."""
    status = await call(
        app_with(TRUSTED_BFF_ENABLED=True, TRUSTED_BFF_SECRET=SECRET),
        {"X-Munsiq-BFF-Secret": SECRET},
    )
    assert status == 400


async def test_a_malformed_org_is_a_400_not_a_500() -> None:
    status = await call(
        app_with(TRUSTED_BFF_ENABLED=True, TRUSTED_BFF_SECRET=SECRET),
        {"X-Munsiq-Org": "not-a-uuid", "X-Munsiq-BFF-Secret": SECRET},
    )
    assert status == 400


async def test_valid_credentials_reach_the_handler() -> None:
    """With both the flag and the secret, identity resolves and the request
    proceeds past auth.

    DATABASE_URL is empty here, so it fails at the database rather than at
    auth — which is precisely the signal we want: the identity seam let it
    through. Anything other than 501/401/400 means auth succeeded.
    """
    status = await call(
        app_with(TRUSTED_BFF_ENABLED=True, TRUSTED_BFF_SECRET=SECRET),
        {"X-Munsiq-Org": ORG, "X-Munsiq-BFF-Secret": SECRET},
    )
    assert status not in {501, 401, 400}
