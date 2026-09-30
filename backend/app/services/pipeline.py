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
import json
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
from app.services.extraction.grounding import ground_value
from app.services.extraction.prompts import parse_line_item_schema, parse_schema
from app.services.extraction.qr_values import apply_deterministic_sources
from app.services.extraction.routing import resolve_mode
from app.services.extraction.runner import ExtractedValue, ExtractionResult, run_extraction
from app.services.pagetext import PageText, extract_page_text
from app.services.qr import find_zatca_qr
from app.services.raster import TooManyPagesError, rasterize, rasterize_pages
from app.services.ubl import (
    MalformedPDFError,
    MalformedXMLError,
    extract_embedded_xml,
    parse_ubl_invoice,
)
from app.services.validation import run_rules
from app.services.validation.context import build_context
from app.services.validation.page_findings import PageState, missing_required, page_findings

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
    vision_pages: list[int] = field(default_factory=list)
    """Pages actually sent to the model as an image. Empty whenever Step Zero
    answered (no model call) or every page's text was trusted as-is."""
    blockers: list[str] = field(default_factory=list)
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
    ubl_invoice = None
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
            ubl_invoice = invoice
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
    # Per-page provenance for the pages table. None means "no model call was
    # made for this page" — Step Zero answered, so no routing decision was ever
    # needed. Set in the model branch below when the model actually runs.
    extraction_paths: dict[int, str | None] = {p.page_number: None for p in pages}
    if ubl_values:
        result = ExtractionResult(values=[], model="", latency_ms=0, model_called=False)
        covered = 0
        for spec in fields:
            if spec.key in ubl_values:
                covered += 1
                # Provenance is the signed XML, full stop: source and confidence
                # are fixed whatever grounding finds. Grounding only answers
                # WHERE the value is printed, so the review UI can point at it.
                # A value the page does not print (an Arabic XML name on an
                # English-printed invoice, say) simply gets no box — it is not
                # downgraded, because the XML, not the page, is its authority.
                grounding = ground_value(ubl_values[spec.key], pages)
                result.values.append(
                    ExtractedValue(
                        field_key=spec.key,
                        value=ubl_values[spec.key],
                        source="ubl_xml",
                        confidence=1.0,
                        validation_state="auto_validated",
                        bbox=grounding.bbox,
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
        # Line items, when the schema asks for them. Same provenance rules as the
        # header: signed XML, confidence 1.0, grounded only to say WHERE.
        line_specs = parse_line_item_schema(definition)
        if ubl_invoice is not None and line_specs:
            for row_index, line in enumerate(ubl_invoice.to_line_item_values()):
                for spec in line_specs:
                    raw = line.get(spec.key)
                    if raw is None:
                        continue
                    # A one- or two-character value ("2", "PCE") matches half
                    # the page; a box on the wrong "2" is worse than no box.
                    bbox = ground_value(raw, pages).bbox if len(raw.strip()) >= 3 else None
                    result.values.append(
                        ExtractedValue(
                            field_key=spec.key,
                            value=raw,
                            source="ubl_xml",
                            confidence=1.0,
                            validation_state="auto_validated",
                            bbox=bbox,
                            row_index=row_index,
                        )
                    )
        logger.info(
            "pipeline.model_skipped",
            extra={"document_id": str(document_id), "ubl_fields": covered},
        )
    else:
        mode, wants_vision = resolve_mode(settings.EXTRACTION_MODE, pages)
        # Cap the number of pages actually rasterized and attached as images: a
        # page beyond the cap falls back to being inlined as plain text (its own,
        # possibly unreliable, text layer) rather than being marked "see the
        # attached image" with no image behind it — see MAX_VISION_PAGES.
        vision_pages = frozenset(sorted(wants_vision)[: settings.MAX_VISION_PAGES])
        outcome.vision_pages = sorted(vision_pages)

        vision_images: list[bytes] | None = None
        if vision_pages:
            rasters = rasterize_pages(
                pdf_bytes,
                vision_pages,
                dpi=settings.VISION_RASTER_DPI,
                quality=settings.WEBP_QUALITY,
            )
            vision_images = [r.data for r in sorted(rasters, key=lambda r: r.page_number)]

        if mode == "vision":
            # A separate model, base URL and context budget — see config.py.
            # Falls back to the text endpoint when no vision-specific one is set,
            # so a local single-Ollama setup needs no extra configuration.
            client = OllamaClient(
                base_url=settings.VISION_INFERENCE_BASE_URL or settings.INFERENCE_BASE_URL,
                model=settings.VISION_MODEL,
                num_ctx=settings.VISION_NUM_CTX,
            )
        else:
            client = OllamaClient()

        result = run_extraction(
            client=client,
            fields=fields,
            pages=pages,
            page_images=vision_images,
            vision_page_numbers=vision_pages,
        )
        for p in pages:
            extraction_paths[p.page_number] = "vision" if p.page_number in vision_pages else "text"
        logger.info(
            "pipeline.extraction_routed",
            extra={
                "document_id": str(document_id),
                "mode": mode,
                "vision_pages": outcome.vision_pages,
                "model": result.model,
            },
        )

    outcome.model_called = result.model_called
    outcome.field_count = len(result.values)

    # Deterministic sources after the model, decided without it: the ZATCA QR
    # printed on the page (when there is no signed XML), then a subtotal the
    # model copied from the total on a tax-inclusive receipt.
    zatca_qr = find_zatca_qr(pdf_bytes) if settings.QR_READING and not ubl_values else None
    apply_deterministic_sources(result.values, qr=zatca_qr, pages=pages)

    # ---------------------------------------------------------------- #
    # 4b. Deterministic validation — runs before the annotation reaches
    # 'to_review', so a reviewer never sees an unchecked document.
    # ---------------------------------------------------------------- #
    context = build_context(values=result.values, fields=fields, pages=pages, invoice=ubl_invoice)
    report = run_rules(context)
    # Page-level findings join the report, so the blocker list, `automated` and
    # the stored rows all see them — the same function revalidation uses.
    report.results.extend(
        page_findings(
            [PageState(p.page_number, p.source, p.note) for p in pages],
            missing_required=missing_required(context),
        )
    )
    blocking_keys = report.blocking_field_keys
    outcome.blockers = report.blockers
    for value in result.values:
        if value.field_key in blocking_keys:
            # An unresolved error freezes the field: the confirm endpoint
            # refuses while any blocking state remains.
            value.validation_state = "blocking"
        elif (
            value.field_key in report.warned_field_keys
            and value.validation_state == "auto_validated"
        ):
            # A warning does not stop confirmation, but it must not leave the
            # field looking settled either.
            value.validation_state = "review_suggested"

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
                    "width_px, height_px, ocr_text, text_source, extraction_path) "
                    "VALUES (:org, :doc, :n, :key, :w, :h, :txt, :src, :path) "
                    "ON CONFLICT (document_id, page_number) DO UPDATE SET "
                    "ocr_text = EXCLUDED.ocr_text, text_source = EXCLUDED.text_source, "
                    "extraction_path = EXCLUDED.extraction_path"
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
                    "path": extraction_paths.get(page.page_number),
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
                "model_version, automated, latency_ms, blockers) "
                "VALUES (:org, :doc, :part, :schema, 'to_review', :model, :auto, :ms, "
                "CAST(:blockers AS jsonb)) "
                "RETURNING id"
            ),
            {
                "org": org_id,
                "doc": document_id,
                "part": part_id,
                "schema": schema_id,
                "model": result.model or None,
                # Automated only if UBL answered AND nothing blocks it.
                "auto": outcome.has_embedded_ubl and not report.blockers,
                "ms": result.latency_ms or None,
                # The UI reads this to explain WHY a document was not automated.
                "blockers": json.dumps(report.blockers),
            },
        )
        outcome.annotation_id = annotation_id

        for value in result.values:
            await session.execute(
                sql(
                    "INSERT INTO extracted_fields (org_id, annotation_id, field_key, "
                    "row_index, value_extracted, model_value, confidence, source, "
                    "validation_state, bbox) "
                    "VALUES (:org, :ann, :key, :row, :val, :model, :conf, :src, :state, "
                    "CAST(:bbox AS jsonb)) "
                    "ON CONFLICT (annotation_id, field_key, row_index) DO NOTHING"
                ),
                {
                    "org": org_id,
                    "ann": annotation_id,
                    "key": value.field_key,
                    "row": value.row_index,
                    # NULL values are written on purpose — negative examples.
                    "val": value.value,
                    # The model's reading of a field signed XML or the QR owns, so
                    # the disagreement rules can be recomputed on revalidation.
                    "model": value.shadow_value,
                    "conf": value.confidence,
                    "src": value.source,
                    "state": value.validation_state,
                    "bbox": _json_or_none(value.bbox),
                },
            )

        await _record_findings(session, org_id, annotation_id, result)
        await _record_rule_results(session, org_id, annotation_id, report)

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


async def _record_findings(session, org_id, annotation_id, result) -> None:  # type: ignore[no-untyped-def]
    """Write the one finding only the model run can produce: its report of
    instruction-like text in the document. Revalidation preserves it.

    Signed-XML and QR disagreements are NOT written here: the registry rules
    (XML_PDF_MISMATCH, QR_MODEL_MISMATCH) produce them from the model's reading,
    which is persisted as `model_value` so revalidation recomputes them too.
    This used to also insert XML_PDF_MISMATCH rows from the runner's list,
    duplicating the rule's. Page-level findings are part of the rule report —
    see validation/page_findings.
    """
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


def _json_or_none(value: dict[str, float | int] | None) -> str | None:
    return None if value is None else json.dumps(value)


FAILURE_RULE = "PIPELINE_FAILED"
_MAX_ERROR_CHARS = 500


async def _mark_failed(org_id: uuid.UUID, document_id: uuid.UUID, error: str) -> None:
    """Make a failed document VISIBLE as a failed annotation with a reason.

    The annotation row is normally created at the very end of the pipeline, so a
    failure earlier than that — an unreadable PDF, the model being down — leaves
    no annotation for a bare UPDATE to mark. The document would then look like it
    is still processing, forever, and nothing would say why. So when there is no
    annotation, create one (status 'failed', with the one part every annotation
    needs) and attach the reason as a finding in both languages.
    """
    reason = error[:_MAX_ERROR_CHARS]
    try:
        async with session_scope(org_id) as session:
            marked = (
                await session.execute(
                    sql(
                        "UPDATE annotations SET status = 'failed', "
                        "blockers = CAST(:blockers AS jsonb), automated = false "
                        "WHERE document_id = :doc RETURNING id"
                    ),
                    {"doc": document_id, "blockers": json.dumps([FAILURE_RULE])},
                )
            ).first()

            if marked is None:
                part_id = await session.scalar(
                    sql(
                        "INSERT INTO document_parts (org_id, document_id, part_index, "
                        "doc_type, page_start, page_end) VALUES (:org, :doc, 0, 'invoice', 1, 1) "
                        "ON CONFLICT (document_id, part_index) DO UPDATE "
                        "SET page_end = document_parts.page_end RETURNING id"
                    ),
                    {"org": org_id, "doc": document_id},
                )
                annotation_id = await session.scalar(
                    sql(
                        "INSERT INTO annotations (org_id, document_id, part_id, status, "
                        "automated, blockers) VALUES (:org, :doc, :part, 'failed', false, "
                        "CAST(:blockers AS jsonb)) RETURNING id"
                    ),
                    {
                        "org": org_id,
                        "doc": document_id,
                        "part": part_id,
                        "blockers": json.dumps([FAILURE_RULE]),
                    },
                )
            else:
                annotation_id = marked.id

            await session.execute(
                sql(
                    "DELETE FROM validation_results WHERE annotation_id = :a AND rule_code = :code"
                ),
                {"a": annotation_id, "code": FAILURE_RULE},
            )
            await session.execute(
                sql(
                    "INSERT INTO validation_results (org_id, annotation_id, rule_code, "
                    "severity, message_ar, message_en, field_key, passed) "
                    "VALUES (:org, :ann, :code, 'error', :ar, :en, NULL, false)"
                ),
                {
                    "org": org_id,
                    "ann": annotation_id,
                    "code": FAILURE_RULE,
                    # The technical reason stays in its original language on
                    # purpose: it is an exception message, not prose to translate.
                    "ar": f"تعذّرت معالجة هذا المستند. السبب التقني: {reason}",
                    "en": f"Processing failed: {reason}",
                },
            )
    except Exception:
        logger.exception("pipeline.mark_failed_failed")


async def _record_rule_results(session, org_id, annotation_id, report) -> None:  # type: ignore[no-untyped-def]
    """Write one validation_results row per rule outcome, passes included.

    Passing rows are kept deliberately: the compliance panel needs to show that
    a check ran and succeeded, which is different from the check never running.
    """
    for result in report.results:
        await session.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, severity, "
                "message_ar, message_en, field_key, passed) "
                "VALUES (:org, :ann, :code, :sev, :ar, :en, :key, :passed)"
            ),
            {
                "org": org_id,
                "ann": annotation_id,
                "code": result.code,
                "sev": result.severity.value,
                "ar": result.message_ar,
                "en": result.message_en,
                "key": result.field_key,
                "passed": result.passed,
            },
        )
