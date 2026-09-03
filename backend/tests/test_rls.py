"""Tenant isolation tests — the point of Phase 2.

These tests run against the real database, because RLS is a database behaviour
and cannot be meaningfully mocked.

READ THIS BEFORE CHANGING ANYTHING HERE.

The application connects to Supabase as ``postgres``, and that role carries
``BYPASSRLS`` (verified: rolsuper=False, rolbypassrls=True). RLS policies do not
constrain a BYPASSRLS role at all — not even with FORCE ROW LEVEL SECURITY.

So an isolation test executed as ``postgres`` would pass while proving nothing:
it would be a false positive on the single most important guarantee in this
project. Every assertion below therefore runs under ``SET LOCAL ROLE
authenticated`` — a role Supabase already provisions, which has neither
superuser nor BYPASSRLS.

``test_postgres_role_bypasses_rls_control`` is the guard on that reasoning: it
asserts that the *same* query as ``postgres`` sees BOTH tenants' rows. If that
control ever starts passing isolation, the test setup has silently stopped
measuring what it claims to measure.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import org_scoped_tables
from app.db.session import ORG_GUC

pytestmark = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)

NON_BYPASSING_ROLE = "authenticated"


class Tenant:
    """One organization plus the minimal FK chain down to an annotation."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.org_id = uuid.uuid4()
        self.document_id = uuid.uuid4()
        self.part_id = uuid.uuid4()
        self.annotation_id = uuid.uuid4()


async def _insert_tenant(session: AsyncSession, t: Tenant) -> None:
    await session.execute(
        text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
        {"id": t.org_id, "name": t.name},
    )
    await session.execute(
        text(
            "INSERT INTO documents (id, org_id, storage_key, source) "
            "VALUES (:id, :org, :key, 'upload')"
        ),
        {"id": t.document_id, "org": t.org_id, "key": f"{t.org_id}/original.pdf"},
    )
    await session.execute(
        text(
            "INSERT INTO document_parts (id, org_id, document_id, part_index, "
            "doc_type, page_start, page_end) "
            "VALUES (:id, :org, :doc, 0, 'invoice', 1, 1)"
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


@pytest_asyncio.fixture(scope="module")
async def tenants() -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two orgs with one annotation each.

    Setup and teardown run as the connecting role (postgres), which bypasses
    RLS. That is correct for fixture management and is exactly why the
    assertions below must NOT run in the same role.
    """
    org_a, org_b = Tenant("Org A — الشركة أ"), Tenant("Org B — الشركة ب")
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        await _insert_tenant(session, org_a)
        await _insert_tenant(session, org_b)

    try:
        yield org_a, org_b
    finally:
        async with sessionmaker() as session, session.begin():
            for tenant in (org_a, org_b):
                # ON DELETE CASCADE from organizations clears the whole chain.
                await session.execute(
                    text("DELETE FROM organizations WHERE id = :id"),
                    {"id": tenant.org_id},
                )


async def _as_tenant(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Drop to a non-bypassing role and bind the tenant, for this transaction."""
    await session.execute(text(f"SET LOCAL ROLE {NON_BYPASSING_ROLE}"))
    await session.execute(
        text("SELECT set_config(:guc, :value, true)"),
        {"guc": ORG_GUC, "value": str(org_id)},
    )


# --------------------------------------------------------------------------- #
# The isolation test
# --------------------------------------------------------------------------- #
async def test_session_sees_only_its_own_org(tenants: tuple[Tenant, Tenant]) -> None:
    """A session scoped to org A sees exactly one annotation: its own."""
    org_a, _org_b = tenants
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        await _as_tenant(session, org_a.org_id)

        rows = (await session.execute(text("SELECT id, org_id FROM annotations"))).all()
        assert len(rows) == 1, f"expected exactly org A's annotation, got {len(rows)} rows"
        assert rows[0].id == org_a.annotation_id
        assert rows[0].org_id == org_a.org_id


async def test_direct_query_for_other_org_row_returns_nothing(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """Knowing org B's primary key must not help. This is the attack we care about."""
    org_a, org_b = tenants
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        await _as_tenant(session, org_a.org_id)

        count = await session.scalar(
            text("SELECT count(*) FROM annotations WHERE id = :id"),
            {"id": org_b.annotation_id},
        )
        assert count == 0, "org A retrieved org B's annotation by id — RLS is not working"


async def test_isolation_holds_across_every_org_scoped_table(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """Isolation is not just an annotations feature."""
    org_a, org_b = tenants
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        await _as_tenant(session, org_a.org_id)

        for table, other_id in (
            ("documents", org_b.document_id),
            ("document_parts", org_b.part_id),
            ("annotations", org_b.annotation_id),
        ):
            leaked = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": other_id}
            )
            assert leaked == 0, f"{table} leaked a row across tenants"

        visible_orgs = await session.scalar(text("SELECT count(*) FROM organizations"))
        assert visible_orgs == 1, "the tenant list itself leaked"


async def test_write_into_another_org_is_rejected(tenants: tuple[Tenant, Tenant]) -> None:
    """WITH CHECK must stop a session forging rows into someone else's tenant."""
    org_a, org_b = tenants
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        await _as_tenant(session, org_a.org_id)

        with pytest.raises(Exception) as exc_info:
            await session.execute(
                text(
                    "INSERT INTO vendors (org_id, trn, name_en) "
                    "VALUES (:org, '310122393510003', 'forged')"
                ),
                {"org": org_b.org_id},
            )
        assert "policy" in str(exc_info.value).lower()


# --------------------------------------------------------------------------- #
# The control — proves the test above is not vacuous
# --------------------------------------------------------------------------- #
async def test_postgres_role_bypasses_rls_control(tenants: tuple[Tenant, Tenant]) -> None:
    """The same query as `postgres` sees BOTH tenants.

    This is not a bug being asserted as correct — it is the control that gives
    the isolation tests their meaning. `postgres` has BYPASSRLS, so if this ever
    returns 1 row instead of 2, the isolation tests are no longer proving
    anything about RLS and this whole module needs re-examining.
    """
    org_a, org_b = tenants
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        # Note: NO SET ROLE. Deliberately the bypassing role.
        await session.execute(
            text("SELECT set_config(:guc, :value, true)"),
            {"guc": ORG_GUC, "value": str(org_a.org_id)},
        )
        ids = {
            row.id
            for row in (
                await session.execute(
                    text("SELECT id FROM annotations WHERE id = ANY(:ids)"),
                    {"ids": [org_a.annotation_id, org_b.annotation_id]},
                )
            ).all()
        }
        assert ids == {org_a.annotation_id, org_b.annotation_id}, (
            "postgres no longer bypasses RLS — re-read this module's docstring, "
            "the isolation tests may now be measuring something else"
        )

        bypasses = await session.scalar(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
        assert bypasses is True


async def test_the_test_role_does_not_bypass_rls() -> None:
    """Guard the other half: `authenticated` must stay non-bypassing."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        await session.execute(text(f"SET LOCAL ROLE {NON_BYPASSING_ROLE}"))
        row = (
            await session.execute(
                text(
                    "SELECT current_user AS role, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        assert row.role == NON_BYPASSING_ROLE
        assert row.rolsuper is False
        assert row.rolbypassrls is False, (
            f"{NON_BYPASSING_ROLE} gained BYPASSRLS — the isolation tests are "
            f"no longer valid and must move to another role"
        )


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #
async def test_every_org_scoped_table_has_rls_enabled_and_forced() -> None:
    """Fails when a new org_id table is added without RLS.

    ENABLE alone is not enough. A table's owner bypasses RLS unless the table is
    FORCEd, and migrations create these tables as the owner — so an un-FORCEd
    table would carry a policy that never fires for the app's own role.
    """
    sessionmaker = get_sessionmaker()
    expected = set(org_scoped_tables()) | {"organizations"}

    async with sessionmaker() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r'"
                )
            )
        ).all()

    state = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}
    missing_table = expected - set(state)
    assert not missing_table, f"declared in ORM but absent from the database: {missing_table}"

    not_enabled = [t for t in sorted(expected) if not state[t][0]]
    not_forced = [t for t in sorted(expected) if not state[t][1]]
    assert not not_enabled, f"RLS not ENABLED on: {not_enabled}"
    assert not not_forced, f"RLS not FORCED on: {not_forced}"


async def test_every_org_scoped_table_has_an_isolation_policy() -> None:
    sessionmaker = get_sessionmaker()
    expected = set(org_scoped_tables()) | {"organizations"}

    async with sessionmaker() as session, session.begin():
        rows = (
            await session.execute(
                text("SELECT tablename FROM pg_policies WHERE schemaname = 'public'")
            )
        ).all()

    with_policy = {r.tablename for r in rows}
    assert not (expected - with_policy), f"no RLS policy on: {sorted(expected - with_policy)}"
