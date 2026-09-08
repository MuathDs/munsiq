"""POST /annotations/{id}/confirm, over real HTTP against the real database.

tests/test_validation_rules.py proves the rules decide correctly. This file
proves the decision is actually *enforced* at the API boundary — that a
document which does not add up cannot be signed off and pushed downstream.

The blocker set is recomputed from validation_results on every call rather than
read from the cached annotations.blockers list, so these tests manipulate
validation_results directly: that is the source of truth the endpoint consults.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sql

from app.api.deps import get_current_org_id
from app.config import Settings, get_settings
from app.db.base import get_sessionmaker
from app.main import create_app

pytestmark = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)


class Fixture:
    def __init__(self) -> None:
        self.org_id = uuid.uuid4()
        self.document_id = uuid.uuid4()
        self.part_id = uuid.uuid4()
        self.annotation_id = uuid.uuid4()


@pytest_asyncio.fixture
async def annotation() -> AsyncIterator[Fixture]:
    """One org with one annotation in 'to_review' and no findings yet."""
    fx = Fixture()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        await session.execute(
            sql("INSERT INTO organizations (id, name) VALUES (:i, :n)"),
            {"i": fx.org_id, "n": f"Confirm Test {fx.org_id}"},
        )
        await session.execute(
            sql("INSERT INTO documents (id, org_id, source) VALUES (:i, :o, 'upload')"),
            {"i": fx.document_id, "o": fx.org_id},
        )
        await session.execute(
            sql(
                "INSERT INTO document_parts (id, org_id, document_id, part_index) "
                "VALUES (:i, :o, :d, 0)"
            ),
            {"i": fx.part_id, "o": fx.org_id, "d": fx.document_id},
        )
        await session.execute(
            sql(
                "INSERT INTO annotations (id, org_id, document_id, part_id, status) "
                "VALUES (:i, :o, :d, :p, 'to_review')"
            ),
            {"i": fx.annotation_id, "o": fx.org_id, "d": fx.document_id, "p": fx.part_id},
        )
    try:
        yield fx
    finally:
        async with sessionmaker() as session, session.begin():
            await session.execute(sql("DELETE FROM organizations WHERE id = :i"), {"i": fx.org_id})


async def add_finding(
    fx: Fixture, code: str, severity: str, passed: bool, field_key: str | None = None
) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, "
                "severity, message_ar, message_en, field_key, passed) "
                "VALUES (:o, :a, :c, :s, :ar, :en, :k, :p)"
            ),
            {
                "o": fx.org_id,
                "a": fx.annotation_id,
                "c": code,
                "s": severity,
                "ar": f"رسالة اختبار للقاعدة {code}.",
                "en": f"Test message for {code}.",
                "k": field_key,
                "p": passed,
            },
        )


async def status_of(fx: Fixture) -> str | None:
    async with get_sessionmaker()() as session, session.begin():
        return await session.scalar(
            sql("SELECT status FROM annotations WHERE id = :i"), {"i": fx.annotation_id}
        )


def client_as(org_id: uuid.UUID) -> AsyncClient:
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    app.dependency_overrides[get_current_org_id] = lambda: org_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# The refusal
# --------------------------------------------------------------------------- #
async def test_confirm_is_refused_while_a_blocking_error_remains(
    annotation: Fixture,
) -> None:
    """The point of Phase 5: an invoice that does not add up cannot be signed off."""
    await add_finding(
        annotation, "GRAND_TOTAL_MISMATCH", "error", passed=False, field_key="total_amount"
    )

    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert response.status_code == 409, response.text
    assert await status_of(annotation) == "to_review", "status changed despite refusal"


async def test_refusal_names_the_rule_and_carries_both_languages(
    annotation: Fixture,
) -> None:
    """A reviewer must be told WHICH check failed, in Arabic and English."""
    await add_finding(
        annotation, "OCR_SUBSTRING_MISSING", "error", passed=False, field_key="vat_amount"
    )

    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    payload = response.json()["detail"]
    blockers = payload["blockers"]
    assert len(blockers) == 1
    assert blockers[0]["rule_code"] == "OCR_SUBSTRING_MISSING"
    assert blockers[0]["field_key"] == "vat_amount"
    assert blockers[0]["message_ar"].strip()
    assert blockers[0]["message_en"].strip()
    # The Arabic message must actually be Arabic, not an English placeholder.
    assert any("؀" <= ch <= "ۿ" for ch in blockers[0]["message_ar"])


async def test_every_unresolved_blocker_is_reported_not_just_the_first(
    annotation: Fixture,
) -> None:
    """Fixing one problem at a time is a miserable review loop."""
    await add_finding(annotation, "GRAND_TOTAL_MISMATCH", "error", passed=False)
    await add_finding(annotation, "TRN_CHECKSUM", "error", passed=False)
    await add_finding(annotation, "VAT_CALC_MISMATCH", "error", passed=False)

    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    codes = {b["rule_code"] for b in response.json()["detail"]["blockers"]}
    assert codes == {"GRAND_TOTAL_MISMATCH", "TRN_CHECKSUM", "VAT_CALC_MISMATCH"}


# --------------------------------------------------------------------------- #
# What must NOT block
# --------------------------------------------------------------------------- #
async def test_clean_annotation_confirms(annotation: Fixture) -> None:
    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"
    assert await status_of(annotation) == "confirmed"


async def test_warnings_do_not_block(annotation: Fixture) -> None:
    """Only errors block. A simplified invoice over SAR 1,000 is the supplier's
    compliance problem, not a reason to stop the buyer booking it."""
    await add_finding(annotation, "INVOICE_TYPE_THRESHOLD", "warning", passed=False)
    await add_finding(annotation, "LINE_ITEM_PRICE_MISMATCH", "warning", passed=False)

    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert response.status_code == 200, response.text
    assert await status_of(annotation) == "confirmed"


async def test_passing_error_severity_rules_do_not_block(annotation: Fixture) -> None:
    """A rule whose severity is 'error' but which PASSED is not a blocker.

    Guards against a query that filters on severity and forgets `passed`.
    """
    await add_finding(annotation, "GRAND_TOTAL_MISMATCH", "error", passed=True)
    await add_finding(annotation, "TRN_CHECKSUM", "error", passed=True)

    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert response.status_code == 200, response.text


async def test_resolving_the_finding_unblocks_confirmation(
    annotation: Fixture,
) -> None:
    """The blocker set is recomputed, not cached — fixing the data clears it."""
    await add_finding(annotation, "GRAND_TOTAL_MISMATCH", "error", passed=False)

    async with client_as(annotation.org_id) as client:
        first = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")
        assert first.status_code == 409

        async with get_sessionmaker()() as session, session.begin():
            await session.execute(
                sql(
                    "UPDATE validation_results SET passed = true "
                    "WHERE annotation_id = :a AND rule_code = 'GRAND_TOTAL_MISMATCH'"
                ),
                {"a": annotation.annotation_id},
            )

        second = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert second.status_code == 200, second.text
    assert await status_of(annotation) == "confirmed"


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #
async def test_confirming_twice_is_idempotent(annotation: Fixture) -> None:
    async with client_as(annotation.org_id) as client:
        first = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")
        second = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"


async def test_unknown_annotation_is_404(annotation: Fixture) -> None:
    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{uuid.uuid4()}/confirm")
    assert response.status_code == 404


async def test_another_tenants_annotation_is_invisible(annotation: Fixture) -> None:
    """RLS still governs this endpoint: a foreign id must 404, not 409 or 200."""
    async with client_as(uuid.uuid4()) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert response.status_code == 404
    assert await status_of(annotation) == "to_review", "another tenant confirmed our annotation"


async def test_failed_annotation_cannot_be_confirmed(annotation: Fixture) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            sql("UPDATE annotations SET status = 'failed' WHERE id = :i"),
            {"i": annotation.annotation_id},
        )

    async with client_as(annotation.org_id) as client:
        response = await client.post(f"/api/v1/annotations/{annotation.annotation_id}/confirm")

    assert response.status_code == 409
    assert await status_of(annotation) == "failed"
