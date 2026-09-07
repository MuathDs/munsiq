"""Document processing pipeline.

Order is deliberate and is the spine of the product:

    1. STEP ZERO   — look for embedded UBL XML. If it is there, the invoice
                     already told us the answer, cryptographically signed. Parse
                     it, write the fields with source='ubl_xml', and DO NOT call
                     the model at all. Zero GPU, zero hallucination risk.
    2. RASTERIZE   — one WebP per page for the review UI's document pane.
    3. TEXT        — text layer per page; OCR only where there is none.
    4. EXTRACT     — schema-conditioned prompting, only when Step Zero did not
                     already answer.
    5. PERSIST     — field rows (including correct nulls), page rows, and
                     validation findings for anything degraded.

Every stage is wrapped so a failure sets the annotation to 'failed' and records
why. A task must never die silently.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import pymupdf
from sqlalchemy import text as sql

from app.config import get_settings
from app.db.session import session_scope
from app.services import storage as storage_mod
from app.services.extraction.client import OllamaClient
from app.services.extraction.prompts import parse_schema
from app.services.extraction.runner import ExtractedValue, ExtractionResult, run_extraction
from app.services.pagetext import PageText, TextSource, extract_page_text
from app.services.raster import TooManyPagesError, rasterize
from app.services.ubl import (
    MalformedPDFError,
    MalformedXMLError,
    extract_embedded_xml,
    parse_ubl_invoice,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineOutcome:
    document_id: uuid.UUID
    annotation_id: uuid.UUID | None = None
    has_embedded_ubl: bool = False
    model_called: bool = False
    page_count: int = 0
    field_count: int = 0
    degraded_pages: list[int] = field(default_factory=list)
    status: str = "to_review"
    error: str | None = None


def sha256_of(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


async def process_document(org_id: uuid.UUID, document_id: uuid.UUID) -> PipelineOutcome:
    """Run the full pipeline for one document. Safe to call from BackgroundTasks."""
    outcome = PipelineOutcome(document_id=document_id)
    try:
        return await _process(org_id, document_id, outcome)
    except Exception as exc:
        logger.exception("pipeline.failed", extra={"document_id": str(document_id)})
        outcome.status = "failed"
        outcome.error = f"{type(exc).__name__}: {exc}"
        await _mark_failed(org_id, document_id, outcome.error)
        return outcome


async def _process(
    org_id: uuid.UUID, document_id: uuid.UUID, outcome: PipelineOutcome
) -> PipelineOutcome:
    settings = get_settings()
    storage = storage_mod.get_storage()

    async with session_scope(org_id) as session:
        row = (
            await session.execute(
                sql("SELECT storage_key, queue_id FROM documents WHERE id = :id"),
                {"id": document_id},
            )
        ).first()
        if row is None:
            raise ValueError(f"document {document_id} not found for this tenant")
        storage_key, queue_id = row.storage_key, row.queue_id
        schema_id, definition = await _load_schema(session, queue_id)

    pdf_bytes = storage.get(storage_key)

    # ---------------------------------------------------------------- #
    # 1. STEP ZERO
    # ---------------------------------------------------------------- #
    ubl_values: dict[str, str] = {}
    embedded_key: str | None = None
    try:
        xml_bytes = extract_embedded_xml(pdf_bytes)
    except MalformedPDFError as exc:
        raise ValueError(f"not a readable PDF: {exc}") from exc

    if xml_bytes is not None:
        embedded_key = storage_mod.document_key(org_id, document_id, "embedded.xml")
        storage.put(embedded_key, xml_bytes)
        try:
            invoice = parse_ubl_invoice(xml_bytes)
            ubl_values = {
                key: field.value
                for key, field in invoice.to_extracted_fields().items()
                if field.value is not None
            }
            outcome.has_embedded_ubl = True
            logger.info(
                "pipeline.step_zero_hit",
                extra={"document_id": str(document_id), "fields": len(ubl_values)},
            )
        except MalformedXMLError as exc:
            # The attachment exists but is unparseable — a supplier-side defect
            # worth reporting, not a reason to abort.
            logger.warning("pipeline.ubl_unparseable", extra={"error": str(exc)})

    # ---------------------------------------------------------------- #
    # 2 + 3. Rasterize and read text
    # ---------------------------------------------------------------- #
    try:
        images = rasterize(pdf_bytes)
    except TooManyPagesError as exc:
        raise ValueError(str(exc)) from exc

    pages: list[PageText] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        for index, page in enumerate(doc, start=1):
            pages.append(extract_page_text(page, index))

    outcome.page_count = len(pages)
    outcome.degraded_pages = [p.page_number for p in pages if p.is_degraded]

    page_keys: dict[int, str] = {}
    for image in images:
        key = storage_mod.page_key(org_id, document_id, image.page_number)
        storage.put(key, image.data)
        page_keys[image.page_number] = key

    # ---------------------------------------------------------------- #
    # 4. Extract — skipped entirely when Step Zero answered
    # ---------------------------------------------------------------- #
    fields = parse_schema(definition)
    if ubl_values:
        result = ExtractionResult(values=[], model="", latency_ms=0, model_called=False)
        covered = 0
        for spec in fields:
            if spec.key in ubl_values:
                covered += 1
                result.values.append(
                    ExtractedValue(
                        field_key=spec.key,
                        value=ubl_values[spec.key],
                        source="ubl_xml",
                        confidence=1.0,
                        validation_state="auto_validated",
                    )
                )
            else:
                # Not in the UBL and the model was never asked. This is NOT a
                # verified absence, so it is not auto_validated — a reviewer
                # decides. Distinct from a model-confirmed null.
                result.values.append(
                    ExtractedValue(
                        field_key=spec.key,
                        value=None,
                        source="ocr_rule",
                        confidence=0.0,
                        validation_state="review_suggested",
                    )
                )
        logger.info(
            "pipeline.model_skipped",
            extra={"document_id": str(document_id), "ubl_fields": covered},
        )
    else:
        client = OllamaClient()
        images_for_model = (
            [images[i].data for i in range(min(len(images), 3))]
            if settings.EXTRACTION_USE_VISION
            else None
        )
        result = run_extraction(
            client=client, fields=fields, pages=pages, page_images=images_for_model
        )

    outcome.model_called = result.model_called
    outcome.field_count = len(result.values)

    # ---------------------------------------------------------------- #
    # 5. Persist
    # ---------------------------------------------------------------- #
    async with session_scope(org_id) as session:
        await session.execute(
            sql(
                "UPDATE documents SET page_count = :n, has_embedded_ubl = :ubl, "
                "embedded_ubl_key = :key, sha256 = :sha WHERE id = :id"
            ),
            {
                "n": len(pages),
                "ubl": outcome.has_embedded_ubl,
                "key": embedded_key,
                "sha": sha256_of(pdf_bytes),
                "id": document_id,
            },
        )

        for page in pages:
            await session.execute(
                sql(
                    "INSERT INTO pages (org_id, document_id, page_number, image_key, "
                    "width_px, height_px, ocr_text, text_source) "
                    "VALUES (:org, :doc, :n, :key, :w, :h, :txt, :src) "
                    "ON CONFLICT (document_id, page_number) DO UPDATE SET "
                    "ocr_text = EXCLUDED.ocr_text, text_source = EXCLUDED.text_source"
                ),
                {
                    "org": org_id,
                    "doc": document_id,
                    "n": page.page_number,
                    "key": page_keys.get(page.page_number),
                    "w": page.width_px,
                    "h": page.height_px,
                    "txt": page.text or None,
                    "src": page.source.value,
                },
            )

        part_id = await session.scalar(
            sql(
                "INSERT INTO document_parts (org_id, document_id, part_index, doc_type, "
                "page_start, page_end) VALUES (:org, :doc, 0, 'invoice', 1, :end) "
                "ON CONFLICT (document_id, part_index) DO UPDATE SET page_end = EXCLUDED.page_end "
                "RETURNING id"
            ),
            {"org": org_id, "doc": document_id, "end": max(1, len(pages))},
        )

        annotation_id = await session.scalar(
            sql(
                "INSERT INTO annotations (org_id, document_id, part_id, schema_id, status, "
                "model_version, automated, latency_ms) "
                "VALUES (:org, :doc, :part, :schema, 'to_review', :model, :auto, :ms) "
                "RETURNING id"
            ),
            {
                "org": org_id,
                "doc": document_id,
                "part": part_id,
                "schema": schema_id,
                "model": result.model or None,
                "auto": outcome.has_embedded_ubl,
                "ms": result.latency_ms or None,
            },
        )
        outcome.annotation_id = annotation_id

        for value in result.values:
            await session.execute(
                sql(
                    "INSERT INTO extracted_fields (org_id, annotation_id, field_key, "
                    "value_extracted, confidence, source, validation_state, bbox) "
                    "VALUES (:org, :ann, :key, :val, :conf, :src, :state, "
                    "CAST(:bbox AS jsonb)) "
                    "ON CONFLICT (annotation_id, field_key, row_index) DO NOTHING"
                ),
                {
                    "org": org_id,
                    "ann": annotation_id,
                    "key": value.field_key,
                    # NULL values are written on purpose — negative examples.
                    "val": value.value,
                    "conf": value.confidence,
                    "src": value.source,
                    "state": value.validation_state,
                    "bbox": _json_or_none(value.bbox),
                },
            )

        await _record_findings(session, org_id, annotation_id, pages, result)

    logger.info(
        "pipeline.done",
        extra={
            "document_id": str(document_id),
            "ubl": outcome.has_embedded_ubl,
            "model_called": outcome.model_called,
            "degraded_pages": len(outcome.degraded_pages),
        },
    )
    return outcome


async def _load_schema(session, queue_id) -> tuple[uuid.UUID | None, dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Read the queue's active extraction schema.

    The field list is INPUT, read at runtime. Never hardcoded, never in weights.
    """
    row = (
        await session.execute(
            sql(
                "SELECT id, definition FROM extraction_schemas WHERE queue_id = :q "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"q": queue_id},
        )
    ).first()
    if row is None:
        raise ValueError("no extraction_schemas row for this queue — run scripts/seed_demo.py")
    return row.id, row.definition


async def _record_findings(session, org_id, annotation_id, pages, result) -> None:  # type: ignore[no-untyped-def]
    """Write validation_results for degraded pages and UBL/model disagreements."""
    for page in pages:
        if not page.is_degraded:
            continue
        await session.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, severity, "
                "message_ar, message_en, field_key, passed) "
                "VALUES (:org, :ann, :code, :sev, :ar, :en, NULL, false)"
            ),
            {
                "org": org_id,
                "ann": annotation_id,
                "code": _RULE_FOR_SOURCE.get(page.source, "PAGE_TEXT_UNAVAILABLE"),
                "sev": "error" if page.source is TextSource.OCR_UNSUPPORTED_SCRIPT else "warning",
                "ar": _AR_MESSAGE.get(page.source, "تعذّر استخراج نص هذه الصفحة.").format(
                    page=page.page_number
                ),
                "en": (page.note or "No text could be extracted from this page.")
                + f" (page {page.page_number})",
            },
        )

    for mismatch in result.mismatches:
        await session.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, severity, "
                "message_ar, message_en, field_key, passed) "
                "VALUES (:org, :ann, 'XML_PDF_MISMATCH', 'error', :ar, :en, :key, false)"
            ),
            {
                "org": org_id,
                "ann": annotation_id,
                "key": mismatch["field_key"],
                "ar": (
                    f"تعارض في الحقل {mismatch['field_key']}: "
                    f"قيمة XML الموقّعة «{mismatch['ubl_value']}» "
                    f"بينما استخرج النموذج «{mismatch['model_value']}». "
                    f"القيمة المعتمدة هي قيمة XML."
                ),
                "en": (
                    f"Field {mismatch['field_key']} disagrees: signed XML says "
                    f"'{mismatch['ubl_value']}', model read '{mismatch['model_value']}'. "
                    f"The XML value is authoritative."
                ),
            },
        )

    if result.suspicious_content:
        await session.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, severity, "
                "message_ar, message_en, field_key, passed) "
                "VALUES (:org, :ann, 'SUSPICIOUS_DOCUMENT_CONTENT', 'warning', :ar, :en, "
                "NULL, false)"
            ),
            {
                "org": org_id,
                "ann": annotation_id,
                "ar": "يحتوي المستند على نص يشبه التعليمات الموجهة للنموذج. تم تجاهله.",
                "en": (
                    "The document contains instruction-like text aimed at the model. "
                    f"It was ignored. Reported: {result.suspicious_content[:400]}"
                ),
            },
        )


_RULE_FOR_SOURCE = {
    TextSource.OCR_UNSUPPORTED_SCRIPT: "OCR_SCRIPT_UNSUPPORTED",
    TextSource.OCR_UNAVAILABLE: "OCR_ENGINE_UNAVAILABLE",
    TextSource.EMPTY: "PAGE_TEXT_EMPTY",
}

_AR_MESSAGE = {
    TextSource.OCR_UNSUPPORTED_SCRIPT: (
        "الصفحة {page}: لا تحتوي على طبقة نصية، ولم يتعرّف المحرك على أي نص. "
        "محرك التعرّف الضوئي الحالي لا يدعم اللغة العربية، لذلك لا يمكن تمييز "
        "الصفحة العربية الممسوحة ضوئياً عن الصفحة الفارغة."
    ),
    TextSource.OCR_UNAVAILABLE: "الصفحة {page}: محرك التعرّف الضوئي غير متاح.",
    TextSource.EMPTY: "الصفحة {page}: لم يُعثر على أي نص.",
}


def _json_or_none(value: dict[str, float | int] | None) -> str | None:
    import json

    return None if value is None else json.dumps(value)


async def _mark_failed(org_id: uuid.UUID, document_id: uuid.UUID, error: str) -> None:
    """Record the failure against the document's annotation, if one exists."""
    try:
        async with session_scope(org_id) as session:
            await session.execute(
                sql("UPDATE annotations SET status = 'failed' WHERE document_id = :doc"),
                {"doc": document_id},
            )
    except Exception:
        logger.exception("pipeline.mark_failed_failed")
