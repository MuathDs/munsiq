"""The dashboard's read endpoints, against seeded ground truth.

The numbers here are worked out by hand from the seed data below, so a wrong
definition fails loudly instead of matching itself. The accuracy case is the one
worth reading: it has to tell a deleted value from an accepted one, and a field
correctly absent from one that was never checked.

Seeded through SQL as the connecting role (which bypasses RLS), then read back
over HTTP through the real app, where RLS applies. Tenant B exists to prove the
new endpoints cannot see across the boundary.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.config import Settings, get_settings
from app.db.base import get_sessionmaker
from app.main import create_app

pytestmark = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)

NOW = datetime.now(UTC)

SCHEMA_V1 = {"name": "Old schema", "fields": [{"key": "invoice_number", "label_en": "Invoice"}]}
SCHEMA_V2 = {
    "name": "Saudi tax invoice",
    "fields": [
        {"key": "invoice_number", "type": "string", "label_en": "Invoice number",
         "label_ar": "رقم الفاتورة", "required": True},
        {"key": "total_amount", "type": "decimal", "label_en": "Total", "label_ar": "الإجمالي"},
    ],
    "line_item_fields": [
        {"key": "line_amount", "type": "decimal", "label_en": "Line amount",
         "label_ar": "مبلغ البند"},
    ],
}  # fmt: skip


@dataclass
class Seed:
    org_a: uuid.UUID = field(default_factory=uuid.uuid4)
    org_b: uuid.UUID = field(default_factory=uuid.uuid4)
    queue_a: uuid.UUID = field(default_factory=uuid.uuid4)
    queue_b: uuid.UUID = field(default_factory=uuid.uuid4)
    ids: dict[str, uuid.UUID] = field(default_factory=dict)


async def _document(
    s: AsyncSession,
    seed: Seed,
    name: str,
    *,
    org: uuid.UUID,
    queue: uuid.UUID,
    age: timedelta = timedelta(0),
    ubl: bool = False,
    status: str | None = None,
    model: str | None = None,
    fields: list[tuple[str, str | None, str | None]] | None = None,
    findings: list[tuple[str, str, bool]] | None = None,
) -> uuid.UUID:
    """Insert a document and, when `status` is given, its annotation, fields and findings."""
    doc_id = uuid.uuid4()
    seed.ids[name] = doc_id
    await s.execute(
        sql(
            "INSERT INTO documents (id, org_id, queue_id, source, filename, has_embedded_ubl, "
            "created_at) VALUES (:i, :o, :q, 'upload', :n, :u, :c)"
        ),
        {"i": doc_id, "o": org, "q": queue, "n": f"{name}.pdf", "u": ubl, "c": NOW - age},
    )
    if status is None:
        return doc_id

    part_id = await s.scalar(
        sql(
            "INSERT INTO document_parts (org_id, document_id, part_index, doc_type, page_start, "
            "page_end) VALUES (:o, :d, 0, 'invoice', 1, 1) RETURNING id"
        ),
        {"o": org, "d": doc_id},
    )
    ann_id = await s.scalar(
        sql(
            "INSERT INTO annotations (org_id, document_id, part_id, status, model_version, "
            "blockers) VALUES (:o, :d, :p, CAST(:s AS annotation_status), :m, '[]') RETURNING id"
        ),
        {"o": org, "d": doc_id, "p": part_id, "s": status, "m": model},
    )
    seed.ids[f"{name}:annotation"] = ann_id
    for key, extracted, final in fields or []:
        await s.execute(
            sql(
                "INSERT INTO extracted_fields (org_id, annotation_id, field_key, value_extracted, "
                "value_final, source, validation_state) "
                "VALUES (:o, :a, :k, :e, :f, 'vlm', 'auto_validated')"
            ),
            {"o": org, "a": ann_id, "k": key, "e": extracted, "f": final},
        )
    for code, severity, passed in findings or []:
        await s.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, severity, "
                "message_ar, message_en, passed) "
                "VALUES (:o, :a, :c, CAST(:sev AS severity), :ar, :en, :p)"
            ),
            {
                "o": org, "a": ann_id, "c": code, "sev": severity, "p": passed,
                "ar": f"عربي {code}", "en": f"Processing failed: {code}",
            },
        )  # fmt: skip
    return doc_id


@pytest_asyncio.fixture(scope="module")
async def seed() -> AsyncIterator[Seed]:
    seed = Seed()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s, s.begin():
        for org, queue, name in (
            (seed.org_a, seed.queue_a, "Dash A"),
            (seed.org_b, seed.queue_b, "Dash B"),
        ):
            await s.execute(
                sql("INSERT INTO organizations (id, name, vat_number) VALUES (:i, :n, :v)"),
                {"i": org, "n": f"{name} {org}", "v": "310122393510003"},
            )
            await s.execute(
                sql("INSERT INTO queues (id, org_id, name) VALUES (:i, :o, :n)"),
                {"i": queue, "o": org, "n": f"{name} queue"},
            )
        for version, definition in ((1, SCHEMA_V1), (2, SCHEMA_V2)):
            await s.execute(
                sql(
                    "INSERT INTO extraction_schemas (org_id, queue_id, version, definition) "
                    "VALUES (:o, :q, :v, CAST(:d AS jsonb))"
                ),
                {"o": seed.org_a, "q": seed.queue_a, "v": version,
                 "d": json.dumps(definition, ensure_ascii=False)},
            )  # fmt: skip

        a = {"org": seed.org_a, "queue": seed.queue_a}
        # Newest first once ordered by age: processing, clean, blocked, failed, ...
        await _document(s, seed, "processing", **a, age=timedelta(seconds=5))
        await _document(
            s, seed, "clean", **a, age=timedelta(minutes=1), ubl=True, status="to_review",
            fields=[("invoice_number", "INV-1", None), ("seller_name", "Acme", None),
                    ("total_amount", "115.00", None), ("currency", "SAR", None)],
        )  # fmt: skip
        await _document(
            s, seed, "blocked", **a, age=timedelta(minutes=2), status="to_review",
            model="qwen2.5:7b-instruct",
            fields=[("invoice_number", "INV-2", None), ("total_amount", "999.00", "998.00")],
            findings=[("GRAND_TOTAL_MISMATCH", "error", False)],
        )  # fmt: skip
        await _document(
            s, seed, "failed", **a, age=timedelta(minutes=3), status="failed",
            findings=[("PIPELINE_FAILED", "error", False)],
        )  # fmt: skip
        await _document(s, seed, "stalled", **a, age=timedelta(days=1))

        # Reviewed. Six fields, hand-classified:
        #   a  extracted, untouched                      -> counted, NOT corrected
        #   b  extracted 10.00, edited to 12.00          -> counted, corrected
        #   c  extracted, deleted (value_final stays NULL, so only the log shows it)
        #                                                -> counted, corrected
        #   d  absent on both sides                      -> makes no claim: not counted
        #   e  extracted NULL, a human ADDED a value     -> counted, corrected
        #   f  edited then reverted to the extracted one -> counted, NOT corrected
        await _document(
            s, seed, "reviewed_one", **a, age=timedelta(minutes=4), ubl=True, status="confirmed",
            fields=[("a", "x", None), ("b", "10.00", "12.00"), ("c", "y", None),
                    ("d", None, None), ("e", None, "z"), ("f", "w", "w")],
        )  # fmt: skip
        await s.execute(
            sql(
                "INSERT INTO field_corrections (org_id, annotation_id, field_key, old_value, "
                "action) VALUES (:o, :a, 'c', 'y', 'delete')"
            ),
            {"o": seed.org_a, "a": seed.ids["reviewed_one:annotation"]},
        )
        await _document(
            s, seed, "reviewed_two", **a, age=timedelta(minutes=5), status="approved",
            model="qwen2.5:7b-instruct",
            fields=[("g", "v1", None), ("h", "v2", None)],
        )  # fmt: skip

        # Tenant B: one document awaiting review, nothing confirmed.
        await _document(
            s, seed, "b_only", org=seed.org_b, queue=seed.queue_b, status="to_review",
            fields=[("invoice_number", "B-1", None)],
        )  # fmt: skip
    try:
        yield seed
    finally:
        async with sessionmaker() as s, s.begin():
            for org in (seed.org_a, seed.org_b):
                await s.execute(sql("DELETE FROM organizations WHERE id = :i"), {"i": org})


def client_as(org_id: uuid.UUID) -> AsyncClient:
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    app.dependency_overrides[get_current_org_id] = lambda: org_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _get(org: uuid.UUID, path: str) -> Any:
    async with client_as(org) as client:
        response = await client.get(f"/api/v1{path}")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
async def test_every_document_appears_with_the_right_state(seed: Seed) -> None:
    rows = {r["filename"]: r for r in await _get(seed.org_a, "/documents")}

    assert rows["processing.pdf"]["state"] == "processing"
    assert rows["processing.pdf"]["annotation_id"] is None, "nothing to open yet"
    assert rows["stalled.pdf"]["state"] == "stalled"
    assert rows["stalled.pdf"]["annotation_id"] is None
    assert rows["clean.pdf"]["state"] == "to_review"
    assert rows["failed.pdf"]["state"] == "failed"
    assert rows["reviewed_one.pdf"]["state"] == "confirmed"
    assert rows["reviewed_two.pdf"]["state"] == "approved"
    assert len(rows) == 7


async def test_list_carries_the_values_a_row_needs(seed: Seed) -> None:
    rows = {r["filename"]: r for r in await _get(seed.org_a, "/documents")}
    clean = rows["clean.pdf"]
    assert (clean["invoice_number"], clean["seller_name"]) == ("INV-1", "Acme")
    assert (clean["total_amount"], clean["currency"]) == ("115.00", "SAR")
    assert clean["has_embedded_ubl"] is True
    assert clean["model_version"] is None, "Step Zero answered: no model"
    assert clean["blocking_count"] == 0

    blocked = rows["blocked.pdf"]
    assert blocked["blocking_count"] == 1
    assert blocked["model_version"] == "qwen2.5:7b-instruct"
    # A reviewer's correction wins over the extracted value, as it does everywhere.
    assert blocked["total_amount"] == "998.00"


async def test_a_failed_document_says_why_in_both_languages(seed: Seed) -> None:
    rows = {r["filename"]: r for r in await _get(seed.org_a, "/documents")}
    failed = rows["failed.pdf"]
    assert failed["error_en"] == "Processing failed: PIPELINE_FAILED"
    assert "PIPELINE_FAILED" in failed["error_ar"]
    assert rows["clean.pdf"]["error_en"] is None


async def test_list_is_newest_first(seed: Seed) -> None:
    names = [r["filename"] for r in await _get(seed.org_a, "/documents")]
    assert names[:3] == ["processing.pdf", "clean.pdf", "blocked.pdf"]
    assert names[-1] == "stalled.pdf"  # a day old


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
async def test_counts_match_the_seed_exactly(seed: Seed) -> None:
    stats = await _get(seed.org_a, "/stats")
    assert stats["documents_total"] == 7
    assert stats["processed"] == 4  # clean, blocked, reviewed_one, reviewed_two
    assert stats["in_progress"] == 1  # processing — NOT the day-old stalled one
    assert stats["awaiting_review"] == 2  # clean, blocked
    assert stats["blocked"] == 1  # blocked only
    assert stats["confirmed"] == 2  # confirmed + approved
    assert stats["failed"] == 2  # failed + stalled
    # Processed, has UBL, and no model: clean and reviewed_one. Not blocked (no
    # UBL), not reviewed_two (model ran).
    assert stats["from_signed_xml"] == 2


async def test_accuracy_counts_corrections_deletions_and_additions(seed: Seed) -> None:
    accuracy = (await _get(seed.org_a, "/stats"))["accuracy"]
    # reviewed_one: a b c e f counted (d absent on both sides is not); b, c, e corrected.
    # reviewed_two: g h counted, neither corrected. => 7 counted, 3 corrected.
    assert accuracy == {"annotations": 2, "fields_total": 7, "fields_corrected": 3}
    # 4 of 7 untouched: the figure the card shows is 57.1%.
    assert round(100 * (7 - 3) / 7, 1) == 57.1


async def test_accuracy_ignores_documents_nobody_has_reviewed(seed: Seed) -> None:
    """Untouched fields in a document awaiting review are unchecked, not correct.

    Tenant B has one to_review document and no confirmed one: the figure is not
    computable, so it is null and the frontend hides the card.
    """
    stats = await _get(seed.org_b, "/stats")
    assert stats["documents_total"] == 1
    assert stats["awaiting_review"] == 1
    assert stats["accuracy"] is None


# --------------------------------------------------------------------------- #
# Templates, org, system
# --------------------------------------------------------------------------- #
async def test_templates_mark_the_version_the_pipeline_actually_reads(seed: Seed) -> None:
    templates = await _get(seed.org_a, "/templates")
    by_version = {t["version"]: t for t in templates}
    assert by_version[2]["in_use"] is True
    assert by_version[1]["in_use"] is False
    assert [t["version"] for t in templates] == [2, 1], "newest version first"

    v2 = by_version[2]
    assert v2["name"] == "Saudi tax invoice"
    assert v2["queue_name"] == "Dash A queue"
    keys = [(f["key"], f["line_item"]) for f in v2["fields"]]
    assert keys == [("invoice_number", False), ("total_amount", False), ("line_amount", True)]
    assert v2["fields"][0]["label_ar"] == "رقم الفاتورة"
    assert v2["fields"][0]["required"] is True


async def test_org_is_the_callers_own(seed: Seed) -> None:
    org = await _get(seed.org_a, "/org")
    assert org["id"] == str(seed.org_a)
    assert org["name"].startswith("Dash A")
    assert org["vat_number"] == "310122393510003"


async def test_system_exposes_no_secrets(seed: Seed) -> None:
    system = await _get(seed.org_a, "/system")
    assert system["inference_model"] == get_settings().INFERENCE_MODEL
    assert system["max_upload_bytes"] == get_settings().MAX_UPLOAD_BYTES
    text = json.dumps(system).lower()
    for forbidden in ("secret", "password", "database", "http://", "token"):
        assert forbidden not in text


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #
async def test_no_endpoint_shows_another_tenants_data(seed: Seed) -> None:
    """RLS is the only scoping these endpoints have; prove it holds on every one."""
    b_docs = await _get(seed.org_b, "/documents")
    assert [d["filename"] for d in b_docs] == ["b_only.pdf"]

    a_docs = await _get(seed.org_a, "/documents")
    assert "b_only.pdf" not in {d["filename"] for d in a_docs}

    assert await _get(seed.org_b, "/templates") == [], "B has no schemas; A's must not leak"
    assert (await _get(seed.org_b, "/org"))["id"] == str(seed.org_b)
    assert (await _get(seed.org_b, "/stats"))["documents_total"] == 1
