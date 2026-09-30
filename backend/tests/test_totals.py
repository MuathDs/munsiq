"""Deriving a tax-exclusive subtotal the model copied from the total.

A simplified (B2C) receipt is tax-inclusive: it prints the total and the VAT
inside it, never a subtotal. The model then copies the total into `subtotal`,
and GRAND_TOTAL_MISMATCH and VAT_CALC_MISMATCH both fire on a receipt that is
perfectly consistent. This is fixed deterministically after extraction, not by
asking the model more nicely, and the derived value is marked `computed` so a
reviewer can see it was calculated rather than read.

All amounts here are synthetic.
"""

from __future__ import annotations

from app.services.extraction.prompts import FieldSpec
from app.services.extraction.runner import ExtractedValue
from app.services.extraction.totals import COMPUTED, derive_tax_exclusive_subtotal
from app.services.pagetext import PageText, TextSource
from app.services.validation import run_rules
from app.services.validation.context import build_context

FIELDS = [
    FieldSpec(key="subtotal", type="decimal", required=True),
    FieldSpec(key="vat_amount", type="decimal", required=True),
    FieldSpec(key="total_amount", type="decimal", required=True),
]

# What a simplified receipt prints: the total and the VAT inside it. No 15.35.
RECEIPT_PAGE = PageText(
    page_number=1,
    source=TextSource.TEXT_LAYER,
    text="Simplified tax invoice Total incl. VAT 17.65 SAR VAT 15% 2.30",
)
BOX = {"page": 1, "x0": 0.6, "y0": 0.4, "x1": 0.7, "y1": 0.42}


def model_value(key: str, value: str | None, *, source: str = "vlm") -> ExtractedValue:
    return ExtractedValue(
        field_key=key,
        value=value,
        source=source,
        confidence=0.97,
        validation_state="auto_validated",
        bbox=BOX if value is not None else None,
        original_value=value,
    )


def receipt(subtotal: str | None = "17.65", vat: str | None = "2.30", total: str | None = "17.65"):  # type: ignore[no-untyped-def]
    return [
        model_value("subtotal", subtotal),
        model_value("vat_amount", vat),
        model_value("total_amount", total),
    ]


def by_key(values: list[ExtractedValue]) -> dict[str, ExtractedValue]:
    return {v.field_key: v for v in values}


# --------------------------------------------------------------------------- #
# The derivation
# --------------------------------------------------------------------------- #
def test_a_copied_total_becomes_total_minus_vat() -> None:
    values = receipt()

    assert derive_tax_exclusive_subtotal(values) is True

    subtotal = by_key(values)["subtotal"]
    assert subtotal.value == "15.35"
    assert subtotal.source == COMPUTED == "computed"


def test_the_derived_value_is_marked_for_review_and_points_nowhere() -> None:
    """It was calculated, not read: it is not printed anywhere, so the box the
    copied total was grounded to must go, and it is not settled on its own."""
    values = receipt()
    derive_tax_exclusive_subtotal(values)

    subtotal = by_key(values)["subtotal"]
    assert subtotal.bbox is None
    assert subtotal.validation_state == "review_suggested"
    assert subtotal.original_value == "17.65", "what the model returned is kept"


def test_the_receipt_then_passes_the_arithmetic_rules() -> None:
    """The acceptance case: 17.65 total, 2.30 VAT -> 15.35, and neither
    GRAND_TOTAL_MISMATCH nor VAT_CALC_MISMATCH fires — nor OCR_SUBSTRING_MISSING,
    though 15.35 is printed nowhere on the receipt."""
    values = receipt()
    derive_tax_exclusive_subtotal(values)

    report = run_rules(build_context(values=values, fields=FIELDS, pages=[RECEIPT_PAGE]))

    failed = {r.code for r in report.failures}
    assert "GRAND_TOTAL_MISMATCH" not in failed
    assert "VAT_CALC_MISMATCH" not in failed
    assert "OCR_SUBSTRING_MISSING" not in failed
    assert "SUBTOTAL_EQUALS_TOTAL" not in failed
    assert report.blockers == []


def test_without_the_derivation_the_same_receipt_is_blocked() -> None:
    """Guards the test above: it must be the derivation that clears the block."""
    report = run_rules(build_context(values=receipt(), fields=FIELDS, pages=[RECEIPT_PAGE]))

    assert {"GRAND_TOTAL_MISMATCH", "VAT_CALC_MISMATCH"} <= set(report.blockers)


def test_equal_amounts_are_compared_as_decimals_not_strings() -> None:
    values = receipt(subtotal="17.650", total="17.65")

    assert derive_tax_exclusive_subtotal(values) is True
    assert by_key(values)["subtotal"].value == "15.35"


def test_the_result_is_rounded_to_two_places() -> None:
    values = receipt(subtotal="100", vat="13.045", total="100")

    derive_tax_exclusive_subtotal(values)

    assert by_key(values)["subtotal"].value == "86.96"


# --------------------------------------------------------------------------- #
# Everything that must be left alone
# --------------------------------------------------------------------------- #
def test_a_normal_invoice_is_untouched() -> None:
    values = receipt(subtotal="45320.00", vat="6798.00", total="52118.00")

    assert derive_tax_exclusive_subtotal(values) is False

    subtotal = by_key(values)["subtotal"]
    assert (subtotal.value, subtotal.source, subtotal.bbox) == ("45320.00", "vlm", BOX)
    assert subtotal.validation_state == "auto_validated"


def test_a_zero_rated_invoice_is_untouched() -> None:
    """Subtotal == total is correct when the VAT really is zero."""
    values = receipt(subtotal="500.00", vat="0.00", total="500.00")

    assert derive_tax_exclusive_subtotal(values) is False
    assert by_key(values)["subtotal"].value == "500.00"


def test_no_vat_stated_is_untouched() -> None:
    """Nothing to subtract: SUBTOTAL_EQUALS_TOTAL is the warning for this case."""
    values = receipt(vat=None)

    assert derive_tax_exclusive_subtotal(values) is False
    assert by_key(values)["subtotal"].value == "17.65"


def test_a_vat_as_large_as_the_total_is_untouched() -> None:
    """total - VAT must stay positive; anything else is a misread, not a receipt."""
    values = receipt(subtotal="10.00", vat="10.00", total="10.00")

    assert derive_tax_exclusive_subtotal(values) is False


def test_a_null_subtotal_is_left_for_the_reviewer() -> None:
    """Only a COPIED total is corrected. A null is REQUIRED_FIELD_MISSING's case."""
    values = receipt(subtotal=None)

    assert derive_tax_exclusive_subtotal(values) is False
    assert by_key(values)["subtotal"].value is None


def test_a_signed_xml_subtotal_is_never_overridden() -> None:
    values = receipt()
    values[0] = model_value("subtotal", "17.65", source="ubl_xml")

    assert derive_tax_exclusive_subtotal(values) is False
    assert by_key(values)["subtotal"].value == "17.65"


def test_unparseable_amounts_are_left_alone() -> None:
    values = receipt(subtotal="seventeen", total="seventeen")

    assert derive_tax_exclusive_subtotal(values) is False
