"""Building a ValidationContext from pipeline outputs. No database."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.invoice import (
    UBLInvoice,
    UBLLine,
    UBLMonetaryTotal,
    UBLTaxSubtotal,
)
from app.services.extraction.prompts import FieldSpec
from app.services.extraction.runner import ExtractedValue
from app.services.pagetext import PageText, TextSource
from app.services.validation.context import build_context

FIELDS = [
    FieldSpec(key="invoice_number", type="string"),
    FieldSpec(key="total_amount", type="decimal"),
    FieldSpec(key="vat_amount", type="decimal"),
    FieldSpec(key="seller_name", type="string"),
]

PAGES = [
    PageText(
        page_number=1,
        source=TextSource.TEXT_LAYER,
        text="Invoice SA-2026-0334 total 52118.00",
    )
]


def _values() -> list[ExtractedValue]:
    return [
        ExtractedValue(
            field_key="invoice_number",
            value="SA-2026-0334",
            source="ubl_xml",
            confidence=1.0,
            validation_state="auto_validated",
            shadow_value="SA-2026-9999",
        ),
        ExtractedValue(
            field_key="total_amount",
            value="52118.00",
            source="vlm",
            confidence=0.9,
            validation_state="auto_validated",
        ),
    ]


def test_required_keys_come_from_the_schema() -> None:
    """REQUIRED_FIELD_MISSING is schema-driven: `required` is schema data, like
    the labels, and nothing in the rules hardcodes which fields matter."""
    fields = [
        FieldSpec(key="invoice_number", required=True),
        FieldSpec(key="total_amount", type="decimal", required=True),
        FieldSpec(key="purchase_order_number"),
    ]

    context = build_context(values=_values(), fields=fields, pages=PAGES)

    assert context.required_keys == frozenset({"invoice_number", "total_amount"})


def test_numeric_keys_come_from_the_schema_types() -> None:
    """Which fields get the anti-hallucination check is schema-driven."""
    context = build_context(values=_values(), fields=FIELDS, pages=PAGES)
    assert context.numeric_keys == frozenset({"total_amount", "vat_amount"})
    assert "seller_name" not in context.numeric_keys


def test_field_views_carry_source_and_shadow_value() -> None:
    context = build_context(values=_values(), fields=FIELDS, pages=PAGES)
    entry = context.fields["invoice_number"]
    assert entry.from_ubl is True
    assert entry.shadow_value == "SA-2026-9999"
    assert context.fields["total_amount"].from_ubl is False


def test_page_text_is_concatenated_and_arabic_is_detected() -> None:
    pages = [
        PageText(page_number=1, source=TextSource.TEXT_LAYER, text="فاتورة ضريبية"),
        PageText(page_number=2, source=TextSource.TEXT_LAYER, text="Total 52118.00"),
        PageText(page_number=3, source=TextSource.OCR_UNSUPPORTED_SCRIPT, text=""),
    ]
    context = build_context(values=_values(), fields=FIELDS, pages=pages)
    assert "فاتورة" in context.page_text
    assert "52118.00" in context.page_text
    assert context.pdf_has_arabic is True


def test_latin_only_document_is_not_flagged_as_arabic() -> None:
    context = build_context(values=_values(), fields=FIELDS, pages=PAGES)
    assert context.pdf_has_arabic is False


def test_without_ubl_the_compliance_inputs_stay_empty() -> None:
    context = build_context(values=_values(), fields=FIELDS, pages=PAGES)
    assert context.has_embedded_ubl is False
    assert context.lines == []
    assert context.qr_decoded is None
    assert context.vat_category is None
    assert context.invoice_type_code is None


def test_ubl_invoice_populates_lines_category_and_qr() -> None:
    invoice = UBLInvoice(
        id="SA-2026-0334",
        invoice_type_code="388",
        invoice_type_name="0100000",
        has_icv=True,
        has_pih=True,
        qr_decoded={1: "شركة", 4: "52118.00"},
        tax_subtotals=[
            UBLTaxSubtotal(category_id="S", percent=Decimal("15.00")),
            UBLTaxSubtotal(category_id="Z", percent=Decimal("0")),
        ],
        monetary_total=UBLMonetaryTotal(tax_inclusive_amount=Decimal("52118.00")),
        lines=[
            UBLLine(
                id="1",
                invoiced_quantity=Decimal("2"),
                price_amount=Decimal("20000.00"),
                line_extension_amount=Decimal("40000.00"),
                item_name="Centrifugal pump",
            )
        ],
    )
    context = build_context(values=_values(), fields=FIELDS, pages=PAGES, invoice=invoice)

    assert context.has_embedded_ubl is True
    assert context.invoice_type_code == "388"
    assert context.is_standard is True
    assert context.has_icv and context.has_pih
    assert context.qr_decoded == {1: "شركة", 4: "52118.00"}

    # The first tax subtotal drives the category rules.
    assert context.vat_category == "S"
    assert context.vat_percent == Decimal("15.00")

    assert len(context.lines) == 1
    line = context.lines[0]
    assert line.quantity == Decimal("2")
    assert line.unit_price == Decimal("20000.00")
    assert line.line_amount == Decimal("40000.00")
    assert line.name == "Centrifugal pump"


def test_ubl_without_tax_subtotals_leaves_category_unset() -> None:
    invoice = UBLInvoice(id="X", tax_subtotals=[])
    context = build_context(values=_values(), fields=FIELDS, pages=PAGES, invoice=invoice)
    assert context.has_embedded_ubl is True
    assert context.vat_category is None
    assert context.vat_percent is None


def test_amount_helper_parses_through_decimal() -> None:
    context = build_context(values=_values(), fields=FIELDS, pages=PAGES)
    assert context.amount("total_amount") == Decimal("52118.00")
    assert context.amount("does_not_exist") is None
    assert context.value("invoice_number") == "SA-2026-0334"
