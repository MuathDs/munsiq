"""Assemble a ValidationContext from pipeline outputs.

Kept separate from engine.py so the rules stay decoupled from the pipeline's
data structures — a rule only ever sees the context, which is why every rule is
testable by hand-building one.
"""

from __future__ import annotations

from decimal import Decimal

from app.schemas.invoice import UBLInvoice
from app.services.extraction.prompts import FieldSpec
from app.services.extraction.runner import ExtractedValue
from app.services.normalize import has_arabic
from app.services.pagetext import PageText
from app.services.validation.engine import (
    NUMERIC_TYPES,
    FieldView,
    LineItem,
    ValidationContext,
)


def build_context(
    *,
    values: list[ExtractedValue],
    fields: list[FieldSpec],
    pages: list[PageText],
    invoice: UBLInvoice | None = None,
) -> ValidationContext:
    """Turn what the pipeline produced into what the rules consume."""
    # Header fields only. Rules address fields by key, so line-item cells —
    # which share a key across rows — would collide here; line arithmetic is
    # checked from the parsed UBL lines below instead.
    views = {
        value.field_key: FieldView(
            key=value.field_key,
            value=value.value,
            source=value.source,
            shadow_value=value.shadow_value,
        )
        for value in values
        if value.row_index is None
    }

    numeric_keys = frozenset(
        spec.key for spec in fields if spec.type.strip().lower() in NUMERIC_TYPES
    )
    required_keys = frozenset(spec.key for spec in fields if spec.required)

    page_text = "\n".join(page.text for page in pages if page.text)
    pdf_has_arabic = any(has_arabic(page.text) for page in pages if page.text)

    lines: list[LineItem] = []
    vat_category: str | None = None
    vat_percent: Decimal | None = None
    qr_decoded: dict[int, str] | None = None
    invoice_type_code: str | None = None
    invoice_type_name: str | None = None
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
        pdf_has_arabic=pdf_has_arabic,
    )
