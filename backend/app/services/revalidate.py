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
from decimal import Decimal

from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.invoice import UBLInvoice
from app.services import storage as storage_mod
from app.services.normalize import has_arabic
from app.services.ubl import MalformedXMLError, parse_ubl_invoice
from app.services.validation import run_rules
from app.services.validation.engine import (
    FieldView,
    LineItem,
    ValidationContext,
    ValidationReport,
)

logger = logging.getLogger(__name__)

NUMERIC_TYPES = frozenset({"decimal", "number", "integer", "money"})


async def revalidate_annotation(
    session: AsyncSession, org_id: uuid.UUID, annotation_id: uuid.UUID
) -> ValidationReport:
    """Rebuild the context from stored state, re-run every rule, replace findings.

    Returns the fresh report. The caller is inside a transaction, so either all
    of it lands or none of it does — an annotation is never left with half its
    findings replaced.
    """
    context = await _context_from_db(session, org_id, annotation_id)
    report = run_rules(context)

    # Replace rather than append: a finding that no longer fires must disappear,
    # otherwise the fix would never clear the block.
    await session.execute(
        sql("DELETE FROM validation_results WHERE annotation_id = :a"),
        {"a": annotation_id},
    )
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
        sql("UPDATE annotations SET blockers = CAST(:b AS jsonb), automated = :auto WHERE id = :a"),
        {
            "a": annotation_id,
            "b": _json(report.blockers),
            "auto": False,  # A human has touched it; it is no longer straight-through.
        },
    )

    logger.info(
        "revalidate.done",
        extra={"annotation_id": str(annotation_id), "blockers": len(report.blockers)},
    )
    return report


async def _context_from_db(
    session: AsyncSession, org_id: uuid.UUID, annotation_id: uuid.UUID
) -> ValidationContext:
    """Assemble a ValidationContext from persisted state."""
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

    numeric_keys = await _numeric_keys(session, header.schema_id, set(views))

    page_rows = (
        await session.execute(
            sql("SELECT ocr_text FROM pages WHERE document_id = :d ORDER BY page_number"),
            {"d": header.document_id},
        )
    ).all()
    page_text = "\n".join(row.ocr_text for row in page_rows if row.ocr_text)

    invoice = _load_ubl(header.embedded_ubl_key)
    return _assemble(views, numeric_keys, page_text, invoice)


async def _numeric_keys(
    session: AsyncSession, schema_id: uuid.UUID | None, present: set[str]
) -> frozenset[str]:
    """Which fields the schema declares numeric.

    OCR_SUBSTRING_MISSING only applies to these, so getting it wrong either
    skips the anti-hallucination guard or applies it to prose.
    """
    if schema_id is None:
        return frozenset()
    definition = await session.scalar(
        sql("SELECT definition FROM extraction_schemas WHERE id = :s"), {"s": schema_id}
    )
    if not isinstance(definition, dict):
        return frozenset()
    fields = definition.get("fields")
    if not isinstance(fields, list):
        return frozenset()
    return frozenset(
        str(spec["key"])
        for spec in fields
        if isinstance(spec, dict)
        and "key" in spec
        and str(spec.get("type", "")).strip().lower() in NUMERIC_TYPES
        and str(spec["key"]) in present
    )


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
