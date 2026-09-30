"""Re-run deterministic validation against the CURRENT state of an annotation.

Why this exists. The confirm endpoint recomputes blockers from
``validation_results`` rather than trusting a cached list, which is the right
design — but it means something has to refresh those rows after a reviewer
edits a field. Without this module, a reviewer could correct the total that
triggered GRAND_TOTAL_MISMATCH and still be refused forever, because the stale
failing row would never go away.

So: apply corrections, revalidate, replace the findings. Fixing the data is
what clears a block.

The context is rebuilt from the database and from the stored UBL attachment, not
from pipeline memory, because by now the pipeline has long finished.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.invoice import UBLInvoice
from app.services import storage as storage_mod
from app.services.normalize import has_arabic
from app.services.pagetext import TextSource
from app.services.ubl import MalformedXMLError, parse_ubl_invoice
from app.services.validation import run_rules
from app.services.validation.engine import (
    NUMERIC_TYPES,
    FieldView,
    LineItem,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationReport,
)
from app.services.validation.page_findings import PageState, missing_required, page_findings

logger = logging.getLogger(__name__)

PRESERVED_CODES: Final[frozenset[str]] = frozenset(
    {
        # The model reported instruction-like text in the document. Needs the
        # model's own output, which is not stored.
        "SUSPICIOUS_DOCUMENT_CONTENT",
        # Why processing failed (pipeline.FAILURE_RULE); the dashboard reads it.
        "PIPELINE_FAILED",
    }
)
"""Findings revalidation cannot recompute from stored state, so it never deletes.

Not in this set, on purpose: XML_PDF_MISMATCH. It needs the model's reading
alongside the signed value, and that reading is not persisted, so a revalidation
cannot re-check it — but keeping the row would make it unclearable by any
correction. It is replaced like any rule (and so cleared on revalidation);
recorded as a known gap in CLAUDE.md."""


@dataclass(frozen=True)
class RevalidateOutcome:
    report: ValidationReport
    finding_ids: list[uuid.UUID]
    """The validation_results row id each ``report.results[i]`` was written
    under, same order, same length. RuleResult itself carries no id — it is
    computed in memory before anything is persisted — so this is the only way
    a caller can tell two same-rule-code findings apart."""


async def revalidate_annotation(
    session: AsyncSession,
    org_id: uuid.UUID,
    annotation_id: uuid.UUID,
    *,
    by_reviewer: bool = True,
) -> RevalidateOutcome:
    """Rebuild the context from stored state, re-run every rule, replace findings.

    What is replaced: every registry rule and every page-level finding, both
    recomputed from stored state with TODAY's logic — so a code a rule no
    longer emits (TRN_CHECKSUM, renamed TRN_FORMAT) disappears, and a page
    finding recorded under an older rule is re-judged rather than kept or lost.
    What is kept: ``PRESERVED_CODES``, the findings only a model run can
    produce, which nothing stored lets us recompute.

    ``by_reviewer=False`` is a system refresh (re-checking old annotations
    after a rule change): it does not mark the annotation as human-touched,
    and it only clears `automated` if the refresh finds a blocker.

    Returns the fresh report AND the database id each result was written under,
    aligned 1:1 with ``report.results`` (preserved findings included, last) — a
    rule firing on two fields shares a code, and a caller rendering a list of
    findings needs something else to key on. The caller is inside a
    transaction, so either all of it lands or none of it does.
    """
    context, pages = await _context_from_db(session, org_id, annotation_id)
    report = run_rules(context)
    report.results.extend(page_findings(pages, missing_required=missing_required(context)))

    # Replace rather than append: a finding that no longer fires must disappear,
    # otherwise the fix would never clear the block.
    await session.execute(
        sql(
            "DELETE FROM validation_results "
            "WHERE annotation_id = :a AND NOT (rule_code = ANY(:keep))"
        ),
        {"a": annotation_id, "keep": sorted(PRESERVED_CODES)},
    )
    finding_ids: list[uuid.UUID] = []
    for result in report.results:
        finding_id = await session.scalar(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, severity, "
                "message_ar, message_en, field_key, passed) "
                "VALUES (:org, :ann, :code, :sev, :ar, :en, :key, :passed) RETURNING id"
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
        assert finding_id is not None  # RETURNING id always yields exactly one row
        finding_ids.append(finding_id)

    preserved = (
        await session.execute(
            sql(
                "SELECT id, rule_code, severity, passed, message_ar, message_en, field_key "
                "FROM validation_results WHERE annotation_id = :a AND rule_code = ANY(:keep) "
                "ORDER BY created_at"
            ),
            {"a": annotation_id, "keep": sorted(PRESERVED_CODES)},
        )
    ).all()
    for row in preserved:
        report.results.append(
            RuleResult(
                code=row.rule_code,
                severity=Severity(row.severity),
                passed=bool(row.passed),
                message_ar=row.message_ar or "",
                message_en=row.message_en or "",
                field_key=row.field_key,
            )
        )
        finding_ids.append(row.id)

    blocking = report.blocking_field_keys
    await session.execute(
        sql(
            "UPDATE extracted_fields SET validation_state = CASE "
            "  WHEN field_key = ANY(:blocking) THEN 'blocking' "
            "  WHEN validation_state = 'blocking' THEN 'review_suggested' "
            "  WHEN field_key = ANY(:warned) AND validation_state = 'auto_validated' "
            "    THEN 'review_suggested' "
            "  ELSE validation_state END "
            "WHERE annotation_id = :a"
        ),
        {"a": annotation_id, "blocking": list(blocking), "warned": list(report.warned_field_keys)},
    )
    await session.execute(
        sql(
            "UPDATE annotations SET blockers = CAST(:b AS jsonb), "
            # A reviewer's edit means it is no longer straight-through. A system
            # refresh keeps the flag unless it found something blocking.
            "automated = CASE WHEN :by_reviewer THEN false ELSE automated AND :clear END "
            "WHERE id = :a"
        ),
        {
            "a": annotation_id,
            "b": _json(report.blockers),
            "by_reviewer": by_reviewer,
            "clear": not report.blockers,
        },
    )

    logger.info(
        "revalidate.done",
        extra={"annotation_id": str(annotation_id), "blockers": len(report.blockers)},
    )
    return RevalidateOutcome(report=report, finding_ids=finding_ids)


async def _context_from_db(
    session: AsyncSession, org_id: uuid.UUID, annotation_id: uuid.UUID
) -> tuple[ValidationContext, list[PageState]]:
    """Assemble a ValidationContext, and each page's stored text source, from
    persisted state."""
    header = (
        await session.execute(
            sql(
                "SELECT a.document_id, a.schema_id, d.embedded_ubl_key "
                "FROM annotations a JOIN documents d ON d.id = a.document_id "
                "WHERE a.id = :a"
            ),
            {"a": annotation_id},
        )
    ).first()
    if header is None:
        raise ValueError(f"annotation {annotation_id} not found for this tenant")

    field_rows = (
        await session.execute(
            sql(
                # Header fields only — see build_context for why line-item
                # cells stay out of the rules' key-addressed view.
                "SELECT field_key, value_extracted, value_final, source "
                "FROM extracted_fields WHERE annotation_id = :a AND row_index IS NULL"
            ),
            {"a": annotation_id},
        )
    ).all()

    views = {
        row.field_key: FieldView(
            key=row.field_key,
            # A human correction supersedes the extracted value. Validation must
            # judge what the reviewer is about to confirm, not what arrived.
            value=row.value_final if row.value_final is not None else row.value_extracted,
            source="human" if row.value_final is not None else row.source,
            shadow_value=None,
        )
        for row in field_rows
    }

    numeric_keys, required_keys = await _schema_keys(session, header.schema_id, set(views))

    page_rows = (
        await session.execute(
            sql(
                "SELECT page_number, ocr_text, text_source FROM pages "
                "WHERE document_id = :d ORDER BY page_number"
            ),
            {"d": header.document_id},
        )
    ).all()
    page_text = "\n".join(row.ocr_text for row in page_rows if row.ocr_text)
    pages = [
        PageState(row.page_number, source)
        for row in page_rows
        if (source := _text_source(row.text_source)) is not None
    ]

    invoice = _load_ubl(header.embedded_ubl_key)
    return _assemble(views, numeric_keys, required_keys, page_text, invoice), pages


def _text_source(raw: str | None) -> TextSource | None:
    """A page from before `text_source` was recorded cannot be judged; skip it
    rather than guess it degraded."""
    try:
        return TextSource(raw) if raw else None
    except ValueError:
        logger.warning("revalidate.unknown_text_source", extra={"value": raw})
        return None


async def _schema_keys(
    session: AsyncSession, schema_id: uuid.UUID | None, present: set[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """Which fields the annotation's own schema declares numeric, and required.

    OCR_SUBSTRING_MISSING only applies to numeric ones, so getting that wrong
    either skips the anti-hallucination guard or applies it to prose. Required
    ones back REQUIRED_FIELD_MISSING, and are NOT narrowed to `present`: a
    required field with no row at all is missing too.
    """
    empty: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
    if schema_id is None:
        return empty
    definition = await session.scalar(
        sql("SELECT definition FROM extraction_schemas WHERE id = :s"), {"s": schema_id}
    )
    if not isinstance(definition, dict):
        return empty
    fields = definition.get("fields")
    if not isinstance(fields, list):
        return empty
    specs = [spec for spec in fields if isinstance(spec, dict) and "key" in spec]
    numeric = frozenset(
        str(spec["key"])
        for spec in specs
        if str(spec.get("type", "")).strip().lower() in NUMERIC_TYPES
        and str(spec["key"]) in present
    )
    # bool(), exactly as FieldSpec.from_definition reads it, so the pipeline and
    # revalidation can never disagree about which fields are required.
    required = frozenset(str(spec["key"]) for spec in specs if bool(spec.get("required", False)))
    return numeric, required


def _load_ubl(embedded_ubl_key: str | None) -> UBLInvoice | None:
    """Re-parse the stored attachment.

    The UBL carries line items, VAT category, QR payload and the ICV/PIH markers
    — none of which are stored as columns. Re-parsing keeps a revalidation as
    complete as the original run instead of quietly dropping half the rules.
    """
    if not embedded_ubl_key:
        return None
    try:
        return parse_ubl_invoice(storage_mod.get_storage().get(embedded_ubl_key))
    except (MalformedXMLError, storage_mod.StorageError) as exc:
        logger.warning("revalidate.ubl_unavailable", extra={"error": str(exc)})
        return None


def _assemble(
    views: dict[str, FieldView],
    numeric_keys: frozenset[str],
    required_keys: frozenset[str],
    page_text: str,
    invoice: UBLInvoice | None,
) -> ValidationContext:
    lines: list[LineItem] = []
    vat_category: str | None = None
    vat_percent: Decimal | None = None
    qr_decoded: dict[int, str] | None = None
    invoice_type_code = invoice_type_name = None
    has_icv = has_pih = has_embedded_ubl = False

    if invoice is not None:
        has_embedded_ubl = True
        invoice_type_code = invoice.invoice_type_code
        invoice_type_name = invoice.invoice_type_name
        has_icv, has_pih = invoice.has_icv, invoice.has_pih
        qr_decoded = invoice.qr_decoded
        lines = [
            LineItem(
                quantity=line.invoiced_quantity,
                unit_price=line.price_amount,
                line_amount=line.line_extension_amount,
                name=line.item_name,
            )
            for line in invoice.lines
        ]
        if invoice.tax_subtotals:
            first = invoice.tax_subtotals[0]
            vat_category = first.category_id
            vat_percent = first.percent

    return ValidationContext(
        fields=views,
        numeric_keys=numeric_keys,
        required_keys=required_keys,
        lines=lines,
        page_text=page_text,
        invoice_type_code=invoice_type_code,
        invoice_type_name=invoice_type_name,
        vat_category=vat_category,
        vat_percent=vat_percent,
        qr_decoded=qr_decoded,
        has_icv=has_icv,
        has_pih=has_pih,
        has_embedded_ubl=has_embedded_ubl,
        pdf_has_arabic=has_arabic(page_text),
    )


def _json(value: list[str]) -> str:
    import json

    return json.dumps(value)
