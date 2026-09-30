"""End-to-end pipeline tests against the real database and filesystem storage.

The headline assertion is the first one: **when a document carries embedded UBL,
the model is never called.** That is the whole economic and correctness argument
for Step Zero — a compliant invoice costs zero GPU and cannot be hallucinated.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
import pytest_asyncio
from sqlalchemy import text as sql

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services import pipeline as pipeline_mod
from app.services import storage as storage_mod
from app.services.extraction.client import ChatResult
from app.services.storage import LocalStorage
from tests import fixtures

pytestmark = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)

SCHEMA = {
    "name": "pipeline test schema",
    "fields": [
        {"key": "invoice_number", "type": "string", "required": True},
        {"key": "seller_trn", "type": "string", "required": True},
        {"key": "total_amount", "type": "decimal", "required": True},
        {"key": "purchase_order_number", "type": "string", "required": False},
    ],
}


class RecordingClient:
    """Stands in for Ollama and counts how often it was actually asked."""

    calls = 0
    init_kwargs: ClassVar[list[dict[str, object]]] = []
    chat_images: ClassVar[list[object]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).init_kwargs.append(kwargs)

    def chat(self, *, system, user, images=None, json_mode=True):  # type: ignore[no-untyped-def]
        type(self).calls += 1
        type(self).chat_images.append(images)
        return ChatResult(
            content=json.dumps(
                {
                    "invoice_number": "SA-2026-0334",
                    "seller_trn": "310122393510003",
                    "total_amount": "52118.00",
                    "purchase_order_number": None,
                }
            ),
            model="fake-model",
            latency_ms=11,
        )


@pytest_asyncio.fixture
async def tenant(tmp_path) -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:  # type: ignore[no-untyped-def]
    """An org with a queue and schema, plus storage rooted in a temp dir."""
    org_id, queue_id = uuid.uuid4(), uuid.uuid4()
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session, session.begin():
        await session.execute(
            sql("INSERT INTO organizations (id, name) VALUES (:id, :n)"),
            {"id": org_id, "n": f"Pipeline Test {org_id}"},
        )
        await session.execute(
            sql("INSERT INTO queues (id, org_id, name) VALUES (:id, :o, 'AP')"),
            {"id": queue_id, "o": org_id},
        )
        await session.execute(
            sql(
                "INSERT INTO extraction_schemas (org_id, queue_id, version, definition) "
                "VALUES (:o, :q, 1, CAST(:d AS jsonb))"
            ),
            {"o": org_id, "q": queue_id, "d": json.dumps(SCHEMA)},
        )

    previous = storage_mod._storage
    storage_mod._storage = LocalStorage(tmp_path / "storage")
    RecordingClient.calls = 0
    RecordingClient.init_kwargs = []
    RecordingClient.chat_images = []
    try:
        yield org_id, queue_id
    finally:
        storage_mod._storage = previous
        async with sessionmaker() as session, session.begin():
            await session.execute(sql("DELETE FROM organizations WHERE id = :id"), {"id": org_id})


async def _insert_document(org_id: uuid.UUID, queue_id: uuid.UUID, pdf: bytes) -> uuid.UUID:
    document_id = uuid.uuid4()
    key = storage_mod.document_key(org_id, document_id, "original.pdf")
    storage_mod.get_storage().put(key, pdf)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            sql(
                "INSERT INTO documents (id, org_id, queue_id, storage_key, source) "
                "VALUES (:id, :o, :q, :k, 'upload')"
            ),
            {"id": document_id, "o": org_id, "q": queue_id, "k": key},
        )
    return document_id


async def _fields(org_id: uuid.UUID, annotation_id: uuid.UUID) -> dict[str, dict]:
    async with get_sessionmaker()() as session, session.begin():
        rows = (
            await session.execute(
                sql(
                    "SELECT field_key, value_extracted, source, validation_state, bbox "
                    "FROM extracted_fields WHERE annotation_id = :a"
                ),
                {"a": annotation_id},
            )
        ).all()
    return {
        r.field_key: {
            "value": r.value_extracted,
            "source": r.source,
            "state": r.validation_state,
            "bbox": r.bbox,
        }
        for r in rows
    }


# --------------------------------------------------------------------------- #
# Step Zero
# --------------------------------------------------------------------------- #
async def test_embedded_ubl_populates_fields_without_calling_the_model(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The whole point of Step Zero: zero GPU on a compliant invoice."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)

    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_embedded_xml())
    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.has_embedded_ubl is True
    assert outcome.model_called is False
    assert RecordingClient.calls == 0, "the model was called despite embedded UBL"

    assert outcome.annotation_id is not None
    fields = await _fields(org_id, outcome.annotation_id)
    assert fields["invoice_number"]["value"] == "SA-2026-0334"
    assert fields["invoice_number"]["source"] == "ubl_xml"
    assert fields["seller_trn"]["value"] == fixtures.SELLER_TRN
    assert fields["total_amount"]["value"] == "52118.00"


async def test_ubl_fields_are_auto_validated_with_full_confidence(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_embedded_xml())
    outcome = await pipeline_mod.process_document(org_id, document_id)
    assert outcome.annotation_id is not None
    fields = await _fields(org_id, outcome.annotation_id)
    assert fields["invoice_number"]["state"] == "auto_validated"


async def test_field_absent_from_ubl_is_not_claimed_as_verified(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The model was never asked, so absence is unverified, not auto_validated."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_embedded_xml())
    outcome = await pipeline_mod.process_document(org_id, document_id)
    assert outcome.annotation_id is not None
    fields = await _fields(org_id, outcome.annotation_id)

    po = fields["purchase_order_number"]
    assert po["value"] is None
    assert po["state"] == "review_suggested"


# --------------------------------------------------------------------------- #
# Model path
# --------------------------------------------------------------------------- #
async def test_document_without_ubl_goes_through_the_model(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)

    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_text_layer())
    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.has_embedded_ubl is False
    assert outcome.model_called is True
    assert RecordingClient.calls == 1

    assert outcome.annotation_id is not None
    fields = await _fields(org_id, outcome.annotation_id)
    assert fields["invoice_number"]["value"] == "SA-2026-0334"
    assert fields["invoice_number"]["source"] == "vlm"


async def test_correct_nulls_are_written_as_rows_not_dropped(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Negative examples must reach the database."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_text_layer())
    outcome = await pipeline_mod.process_document(org_id, document_id)
    assert outcome.annotation_id is not None

    fields = await _fields(org_id, outcome.annotation_id)
    assert len(fields) == len(SCHEMA["fields"]), "every schema field needs a row"
    assert "purchase_order_number" in fields
    assert fields["purchase_order_number"]["value"] is None


class NullTotalClient(RecordingClient):
    """The model returns null for a REQUIRED field."""

    def chat(self, *, system, user, images=None, json_mode=True):  # type: ignore[no-untyped-def]
        result = super().chat(system=system, user=user, images=images, json_mode=json_mode)
        result.content = json.dumps(
            {
                "invoice_number": "SA-2026-0334",
                "seller_trn": "310122393510003",
                "total_amount": None,
                "purchase_order_number": None,
            }
        )
        return result


async def test_a_null_required_field_is_never_left_green(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The schema here gives total_amount no label, so the silent-miss check has
    nothing to look for on the page: before REQUIRED_FIELD_MISSING, this null was
    written auto_validated. The optional null next to it stays a correct null."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", NullTotalClient)
    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_text_layer())

    outcome = await pipeline_mod.process_document(org_id, document_id)
    assert outcome.error is None and outcome.annotation_id is not None

    fields = await _fields(org_id, outcome.annotation_id)
    assert fields["total_amount"]["value"] is None
    assert fields["total_amount"]["state"] == "review_suggested"
    assert fields["purchase_order_number"]["state"] == "auto_validated"

    async with get_sessionmaker()() as session, session.begin():
        findings = (
            await session.execute(
                sql(
                    "SELECT field_key, severity FROM validation_results "
                    "WHERE annotation_id = :a AND rule_code = 'REQUIRED_FIELD_MISSING' "
                    "AND passed = false"
                ),
                {"a": outcome.annotation_id},
            )
        ).all()
    assert [(f.field_key, f.severity) for f in findings] == [("total_amount", "warning")]
    assert "REQUIRED_FIELD_MISSING" not in outcome.blockers


RECEIPT_SCHEMA = {
    "name": "receipt schema",
    "fields": [
        {"key": "invoice_number", "type": "string", "required": True},
        {"key": "subtotal", "type": "decimal", "required": True},
        {"key": "vat_amount", "type": "decimal", "required": True},
        {"key": "total_amount", "type": "decimal", "required": True},
    ],
}


class CopiedTotalClient(RecordingClient):
    """What the model does on a tax-inclusive receipt: subtotal = the total."""

    def chat(self, *, system, user, images=None, json_mode=True):  # type: ignore[no-untyped-def]
        result = super().chat(system=system, user=user, images=images, json_mode=json_mode)
        result.content = json.dumps(
            {
                "invoice_number": "RCPT-0001",
                "subtotal": "17.65",
                "vat_amount": "2.30",
                "total_amount": "17.65",
            }
        )
        return result


async def test_a_copied_receipt_total_is_stored_as_a_computed_subtotal(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Synthetic simplified receipt: 17.65 total, 2.30 VAT. Before the derivation
    it was blocked by GRAND_TOTAL_MISMATCH and VAT_CALC_MISMATCH."""
    org_id, queue_id = tenant
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            sql(
                "INSERT INTO extraction_schemas (org_id, queue_id, version, definition) "
                "VALUES (:o, :q, 2, CAST(:d AS jsonb))"
            ),
            {"o": org_id, "q": queue_id, "d": json.dumps(RECEIPT_SCHEMA)},
        )
    monkeypatch.setattr(pipeline_mod, "OllamaClient", CopiedTotalClient)
    pdf = fixtures.build_pdf_with_text_layer(
        lines=(
            "SIMPLIFIED TAX INVOICE",
            "Invoice No: RCPT-0001",
            "Total incl. VAT: 17.65 SAR",
            "VAT 15%: 2.30",
        )
    )
    document_id = await _insert_document(org_id, queue_id, pdf)

    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None and outcome.annotation_id is not None
    fields = await _fields(org_id, outcome.annotation_id)
    assert fields["subtotal"]["value"] == "15.35"
    assert fields["subtotal"]["source"] == "computed"
    assert fields["subtotal"]["state"] == "review_suggested"
    assert fields["subtotal"]["bbox"] is None
    assert fields["total_amount"]["value"] == "17.65"
    assert outcome.blockers == []
    async with get_sessionmaker()() as session, session.begin():
        failed = {
            r[0]
            for r in (
                await session.execute(
                    sql(
                        "SELECT rule_code FROM validation_results "
                        "WHERE annotation_id = :a AND passed = false"
                    ),
                    {"a": outcome.annotation_id},
                )
            ).all()
        }
    assert not failed & {"GRAND_TOTAL_MISMATCH", "VAT_CALC_MISMATCH", "OCR_SUBSTRING_MISSING"}


async def test_values_are_grounded_to_the_text_layer(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Grounding on a text-layer page comes from the PDF's own word boxes."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_text_layer())
    outcome = await pipeline_mod.process_document(org_id, document_id)
    assert outcome.annotation_id is not None

    fields = await _fields(org_id, outcome.annotation_id)
    bbox = fields["invoice_number"]["bbox"]
    assert bbox is not None, "a value present on the page must be grounded"
    for key in ("x0", "y0", "x1", "y1"):
        assert 0.0 <= float(bbox[key]) <= 1.0, "bboxes must be normalized, never pixels"


# --------------------------------------------------------------------------- #
# The Arabic gap must be loud
# --------------------------------------------------------------------------- #
async def test_page_without_text_layer_is_recorded_not_silently_empty(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A page we could not read must say so, on the page row AND as a finding.

    Returning empty text as though the read succeeded is the failure mode this
    asserts against.
    """
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)

    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_without_attachment())
    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.degraded_pages == [1]

    async with get_sessionmaker()() as session, session.begin():
        source = await session.scalar(
            sql("SELECT text_source FROM pages WHERE document_id = :d"), {"d": document_id}
        )
        codes = [
            r.rule_code
            for r in (
                await session.execute(
                    sql("SELECT rule_code FROM validation_results WHERE annotation_id = :a"),
                    {"a": outcome.annotation_id},
                )
            ).all()
        ]

    assert source in {"ocr_unsupported_script", "ocr_unavailable", "empty"}
    assert source != "text_layer"
    assert any(
        code in {"OCR_SCRIPT_UNSUPPORTED", "OCR_ENGINE_UNAVAILABLE", "PAGE_TEXT_EMPTY"}
        for code in codes
    ), f"an unreadable page produced no validation finding: {codes}"


async def test_a_degraded_filler_page_warns_instead_of_blocking(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A real invoice's nearly-empty page 2 raised OCR_SCRIPT_UNSUPPORTED as a
    BLOCKING error, even though every required field was read from page 1's
    signed UBL and page 2 held nothing the schema needed. A degraded page must
    only block when the document as a whole has nothing readable, or a
    required field is missing and this page is a plausible reason why.
    """
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)

    document_id = await _insert_document(
        org_id, queue_id, fixtures.build_pdf_with_embedded_xml_and_blank_page()
    )
    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.has_embedded_ubl is True
    assert 2 in outcome.degraded_pages, "page 2 must still be recorded as degraded"

    async with get_sessionmaker()() as session, session.begin():
        rows = (
            await session.execute(
                sql(
                    "SELECT rule_code, severity FROM validation_results "
                    "WHERE annotation_id = :a AND rule_code = 'OCR_SCRIPT_UNSUPPORTED'"
                ),
                {"a": outcome.annotation_id},
            )
        ).all()
        # The two fields the schema requires (seller_trn, total_amount) plus
        # invoice_number came from page 1's XML, so nothing required is missing.
        missing_required = await session.scalar(
            sql(
                "SELECT count(*) FROM extracted_fields WHERE annotation_id = :a "
                "AND field_key IN ('seller_trn', 'total_amount') AND value_extracted IS NULL"
            ),
            {"a": outcome.annotation_id},
        )

    assert rows, "the blank page must still be recorded as a finding"
    assert missing_required == 0
    assert all(r.severity == "warning" for r in rows), (
        "no required field is missing, so a blank filler page must warn, not block"
    )


async def test_text_layer_page_is_recorded_as_such(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_text_layer())
    await pipeline_mod.process_document(org_id, document_id)

    async with get_sessionmaker()() as session, session.begin():
        source = await session.scalar(
            sql("SELECT text_source FROM pages WHERE document_id = :d"), {"d": document_id}
        )
    assert source == "text_layer"


# --------------------------------------------------------------------------- #
# Vision routing (Part B)
# --------------------------------------------------------------------------- #
async def test_a_clean_text_document_never_touches_the_vision_path(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The default EXTRACTION_MODE is 'auto', but a single clean page must stay
    on the cheap, exact text path — no image, no vision client kwargs."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(org_id, queue_id, fixtures.build_pdf_with_text_layer())

    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.vision_pages == []
    assert RecordingClient.chat_images == [None]
    assert RecordingClient.init_kwargs == [{}], "the plain text client takes no overrides"

    async with get_sessionmaker()() as session, session.begin():
        path = await session.scalar(
            sql("SELECT extraction_path FROM pages WHERE document_id = :d AND page_number = 1"),
            {"d": document_id},
        )
    assert path == "text"


async def test_a_document_with_one_bad_page_routes_only_that_page_to_vision(
    tenant, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """The real-invoice shape: page 1 fine, page 2 unreadable. The whole call
    must use the vision-capable model (a text model cannot see images at all),
    but only page 2 is rasterized, attached and recorded as 'vision'."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(
        org_id, queue_id, fixtures.build_pdf_with_text_layer_and_blank_second_page()
    )

    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.vision_pages == [2]
    assert RecordingClient.calls == 1

    settings = get_settings()
    assert RecordingClient.init_kwargs == [
        {
            "base_url": settings.VISION_INFERENCE_BASE_URL or settings.INFERENCE_BASE_URL,
            "model": settings.VISION_MODEL,
            "num_ctx": settings.VISION_NUM_CTX,
        }
    ]
    (images,) = RecordingClient.chat_images
    assert images is not None and len(images) == 1

    async with get_sessionmaker()() as session, session.begin():
        rows = (
            await session.execute(
                sql(
                    "SELECT page_number, extraction_path FROM pages "
                    "WHERE document_id = :d ORDER BY page_number"
                ),
                {"d": document_id},
            )
        ).all()
    assert [(r.page_number, r.extraction_path) for r in rows] == [(1, "text"), (2, "vision")]


async def test_forced_text_mode_ignores_a_bad_page(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    monkeypatch.setattr(get_settings(), "EXTRACTION_MODE", "text")
    document_id = await _insert_document(
        org_id, queue_id, fixtures.build_pdf_with_text_layer_and_blank_second_page()
    )

    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.vision_pages == []
    assert RecordingClient.chat_images == [None]


async def test_step_zero_leaves_extraction_path_null(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No model call at all means no routing decision was ever made — a page
    the signed XML alone answered must not claim a text/vision path it never
    walked."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)
    document_id = await _insert_document(
        org_id, queue_id, fixtures.build_pdf_with_text_layer_and_ubl()
    )

    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.error is None
    assert outcome.has_embedded_ubl is True
    assert RecordingClient.calls == 0

    async with get_sessionmaker()() as session, session.begin():
        path = await session.scalar(
            sql("SELECT extraction_path FROM pages WHERE document_id = :d AND page_number = 1"),
            {"d": document_id},
        )
    assert path is None


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #
async def test_unreadable_pdf_fails_loudly_and_records_status(tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A task must never die silently."""
    org_id, queue_id = tenant
    monkeypatch.setattr(pipeline_mod, "OllamaClient", RecordingClient)

    document_id = await _insert_document(org_id, queue_id, b"this is not a PDF")
    outcome = await pipeline_mod.process_document(org_id, document_id)

    assert outcome.status == "failed"
    assert outcome.error is not None
