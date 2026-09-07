"""Tenant isolation over the real HTTP request path.

tests/test_rls.py proves the RLS policies work when queried directly. This file
proves the *application* is actually subject to them: requests go through the
real ASGI app, the real router, the real session dependency, the real
SET LOCAL ROLE, and the real policies.

The ONLY thing substituted is ``get_current_org_id`` — the JWT claim reader,
which does not exist until auth lands. Everything downstream of it is
production code. Overriding it is not a workaround: it stands in for the token
a real caller would present, and it is the same seam a signed JWT will plug
into.

Note that app/api/annotations.py contains no org_id filter at all. If the role
switch or the policies stopped working, these tests would see both tenants and
fail. That is deliberate: the endpoint has no second line of defence, so the
test measures RLS and nothing else.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.deps import get_current_org_id
from app.config import Settings, get_settings
from app.db.base import get_sessionmaker
from app.main import create_app

pytestmark = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)


class ApiTenant:
    def __init__(self, name: str) -> None:
        self.name = name
        self.org_id = uuid.uuid4()
        self.document_id = uuid.uuid4()
        self.part_id = uuid.uuid4()
        self.annotation_id = uuid.uuid4()


@pytest_asyncio.fixture(scope="module")
async def api_tenants() -> AsyncIterator[tuple[ApiTenant, ApiTenant]]:
    """Seed two tenants. Setup runs as the connecting role, which bypasses RLS."""
    a, b = ApiTenant("API Org A"), ApiTenant("API Org B")
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        for t in (a, b):
            await session.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
                {"id": t.org_id, "name": t.name},
            )
            await session.execute(
                text("INSERT INTO documents (id, org_id, source) VALUES (:id, :org, 'upload')"),
                {"id": t.document_id, "org": t.org_id},
            )
            await session.execute(
                text(
                    "INSERT INTO document_parts (id, org_id, document_id, part_index) "
                    "VALUES (:id, :org, :doc, 0)"
                ),
                {"id": t.part_id, "org": t.org_id, "doc": t.document_id},
            )
            await session.execute(
                text(
                    "INSERT INTO annotations (id, org_id, document_id, part_id, status) "
                    "VALUES (:id, :org, :doc, :part, 'to_review')"
                ),
                {
                    "id": t.annotation_id,
                    "org": t.org_id,
                    "doc": t.document_id,
                    "part": t.part_id,
                },
            )
    try:
        yield a, b
    finally:
        async with sessionmaker() as session, session.begin():
            for t in (a, b):
                await session.execute(
                    text("DELETE FROM organizations WHERE id = :id"), {"id": t.org_id}
                )


def client_as(org_id: uuid.UUID) -> AsyncClient:
    """An HTTP client whose requests carry ``org_id`` as the verified identity."""
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    app.dependency_overrides[get_current_org_id] = lambda: org_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# Isolation over HTTP
# --------------------------------------------------------------------------- #
async def test_list_endpoint_returns_only_callers_tenant(
    api_tenants: tuple[ApiTenant, ApiTenant],
) -> None:
    org_a, org_b = api_tenants

    async with client_as(org_a.org_id) as client:
        response = await client.get("/api/v1/annotations")

    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()}
    assert str(org_a.annotation_id) in ids
    assert str(org_b.annotation_id) not in ids, (
        "tenant B's annotation was returned to tenant A over HTTP — the request "
        "path is not constrained by RLS"
    )
    assert {row["org_id"] for row in response.json()} == {str(org_a.org_id)}


async def test_fetch_by_id_cannot_reach_another_tenant(
    api_tenants: tuple[ApiTenant, ApiTenant],
) -> None:
    """Knowing tenant B's UUID must not be enough. The endpoint does not filter."""
    org_a, org_b = api_tenants

    async with client_as(org_a.org_id) as client:
        own = await client.get(f"/api/v1/annotations/{org_a.annotation_id}")
        other = await client.get(f"/api/v1/annotations/{org_b.annotation_id}")

    assert own.status_code == 200
    assert own.json()["id"] == str(org_a.annotation_id)

    assert other.status_code == 200
    assert other.json() is None, "tenant A fetched tenant B's annotation by primary key over HTTP"


async def test_both_tenants_see_their_own_row(
    api_tenants: tuple[ApiTenant, ApiTenant],
) -> None:
    """Symmetry check: isolation is not an artefact of ordering or of one org."""
    org_a, org_b = api_tenants

    for tenant, other in ((org_a, org_b), (org_b, org_a)):
        async with client_as(tenant.org_id) as client:
            payload = (await client.get("/api/v1/annotations")).json()
        ids = {row["id"] for row in payload}
        assert str(tenant.annotation_id) in ids
        assert str(other.annotation_id) not in ids


# --------------------------------------------------------------------------- #
# The identity seam itself
# --------------------------------------------------------------------------- #
async def test_request_without_identity_is_refused() -> None:
    """With no override, the real dependency runs and must refuse, not default.

    A convenient fallback here — a header, a query param, a "default org" — would
    let the caller choose which tenant to read.
    """
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/annotations")

    assert response.status_code == 501
    assert "JWT" in response.json()["detail"]


async def test_health_needs_no_tenant() -> None:
    """Sanity: the isolation plumbing has not broken unauthenticated routes."""
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
