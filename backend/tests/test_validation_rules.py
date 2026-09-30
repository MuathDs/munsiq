"""Unit tests for every deterministic rule. No database, no model, no network.

Each rule is exercised across three outcomes where they exist:
  * passes            -> returns []
  * fails             -> returns findings, with the right severity and field
  * not applicable    -> returns None (distinct from passing)

That third case matters: a plain scan has no QR code, and recording "QR check
passed" for a document that never had one would be a lie in the compliance panel.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.ubl import QR_TAG_TOTAL_WITH_VAT, QR_TAG_VAT_TOTAL
from app.services.validation.engine import (
    FieldView,
    LineItem,
    RuleResult,
    Severity,
    ValidationContext,
    close_enough,
    money,
    registry,
    run_rules,
    same_value,
    to_date,
    to_decimal,
)
from app.services.validation.rules.arithmetic import (
    amounts_are_not_negative,
    grand_total_adds_up,
    line_item_amounts_are_consistent,
    line_total_matches_subtotal,
    subtotal_is_not_the_total,
    vat_amount_matches_rate,
)
from app.services.validation.rules.completeness import required_fields_are_present
from app.services.validation.rules.provenance import (
    arabic_survived_the_xml,
    numeric_values_appear_on_the_page,
    qr_and_model_agree,
    text_layer_is_intact,
    xml_and_model_agree,
)
from app.services.validation.rules.zatca import (
    qr_totals_match_extracted,
    simplified_invoice_below_threshold,
    standard_invoice_has_sequence_fields,
    trn_tax_type_is_vat,
    trns_are_structurally_valid,
    vat_category_is_known,
    vat_rate_matches_category,
)

VALID_TRN = "310122393500003"  # the official ZATCA documentation sample
OTHER_TRN = "311111111110003"


def ctx(**kwargs) -> ValidationContext:  # type: ignore[no-untyped-def]
    """Build a context from plain values; `fields` accepts key -> value or FieldView."""
    raw = kwargs.pop("fields", {})
    fields = {
        key: (value if isinstance(value, FieldView) else FieldView(key=key, value=value))
        for key, value in raw.items()
    }
    return ValidationContext(fields=fields, **kwargs)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_to_decimal_handles_separators_and_arabic_decimal_mark() -> None:
    assert to_decimal("45,320.00") == Decimal("45320.00")
    assert to_decimal("45320٫50") == Decimal("45320.50")
    assert to_decimal("  ") is None
    assert to_decimal(None) is None
    assert to_decimal("not a number") is None
    assert to_decimal(Decimal("1.5")) == Decimal("1.5")


def test_money_never_uses_float() -> None:
    assert isinstance(money(Decimal("1.005")), Decimal)
    assert money(Decimal("52118")) == Decimal("52118.00")


def test_close_enough_tolerates_one_halala_but_not_two() -> None:
    assert close_enough(Decimal("100.00"), Decimal("100.01")) is True
    assert close_enough(Decimal("100.00"), Decimal("99.99")) is True
    assert close_enough(Decimal("100.00"), Decimal("100.02")) is False


# --------------------------------------------------------------------------- #
# LINE_TOTAL_MISMATCH
# --------------------------------------------------------------------------- #
def test_line_total_passes_when_lines_sum_to_subtotal() -> None:
    context = ctx(
        fields={"subtotal": "45320.00"},
        lines=[
            LineItem(quantity=Decimal("2"), unit_price=Decimal("20000.00")),
            LineItem(quantity=Decimal("4"), unit_price=Decimal("1330.00")),
        ],
    )
    assert line_total_matches_subtotal(context) == []


def test_line_total_fails_and_names_both_numbers() -> None:
    context = ctx(
        fields={"subtotal": "50000.00"},
        lines=[LineItem(quantity=Decimal("2"), unit_price=Decimal("20000.00"))],
    )
    findings = line_total_matches_subtotal(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].field_key == "subtotal"
    assert "40000.00" in findings[0].message_en
    assert "50000.00" in findings[0].message_en


def test_line_total_falls_back_to_line_amount_when_price_missing() -> None:
    context = ctx(
        fields={"subtotal": "45320.00"},
        lines=[LineItem(line_amount=Decimal("45320.00"))],
    )
    assert line_total_matches_subtotal(context) == []


def test_line_total_not_applicable_without_lines() -> None:
    assert line_total_matches_subtotal(ctx(fields={"subtotal": "1.00"})) is None


def test_line_total_not_applicable_without_subtotal() -> None:
    context = ctx(lines=[LineItem(line_amount=Decimal("1.00"))])
    assert line_total_matches_subtotal(context) is None


def test_line_total_not_applicable_when_no_line_is_usable() -> None:
    context = ctx(fields={"subtotal": "1.00"}, lines=[LineItem(name="widget")])
    assert line_total_matches_subtotal(context) is None


# --------------------------------------------------------------------------- #
# LINE_ITEM_PRICE_MISMATCH
# --------------------------------------------------------------------------- #
def test_line_item_prices_consistent() -> None:
    context = ctx(
        lines=[
            LineItem(
                quantity=Decimal("2"),
                unit_price=Decimal("20000.00"),
                line_amount=Decimal("40000.00"),
            )
        ]
    )
    assert line_item_amounts_are_consistent(context) == []


def test_line_item_price_mismatch_is_a_warning_naming_the_row() -> None:
    context = ctx(
        lines=[
            LineItem(
                quantity=Decimal("2"),
                unit_price=Decimal("20000.00"),
                line_amount=Decimal("39000.00"),
            )
        ]
    )
    findings = line_item_amounts_are_consistent(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "Line 1" in findings[0].message_en


def test_line_item_rule_not_applicable_without_lines_or_complete_rows() -> None:
    assert line_item_amounts_are_consistent(ctx()) is None
    assert line_item_amounts_are_consistent(ctx(lines=[LineItem(quantity=Decimal("1"))])) is None


# --------------------------------------------------------------------------- #
# VAT_CALC_MISMATCH
# --------------------------------------------------------------------------- #
def test_vat_calculation_passes_at_fifteen_percent() -> None:
    context = ctx(fields={"subtotal": "45320.00", "vat_amount": "6798.00"})
    assert vat_amount_matches_rate(context) == []


def test_vat_calculation_uses_the_declared_rate_when_present() -> None:
    context = ctx(fields={"subtotal": "1000.00", "vat_amount": "0.00"}, vat_percent=Decimal("0"))
    assert vat_amount_matches_rate(context) == []


def test_vat_calculation_fails_when_amount_is_wrong() -> None:
    context = ctx(fields={"subtotal": "45320.00", "vat_amount": "5000.00"})
    findings = vat_amount_matches_rate(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].field_key == "vat_amount"
    assert findings[0].severity is Severity.ERROR
    assert "6798.00" in findings[0].message_en


@pytest.mark.parametrize(
    "fields",
    [{"subtotal": "1.00"}, {"vat_amount": "1.00"}, {}],
)
def test_vat_calculation_not_applicable_when_an_input_is_missing(fields: dict) -> None:
    assert vat_amount_matches_rate(ctx(fields=fields)) is None


# --------------------------------------------------------------------------- #
# GRAND_TOTAL_MISMATCH
# --------------------------------------------------------------------------- #
def test_grand_total_passes() -> None:
    context = ctx(
        fields={"subtotal": "45320.00", "vat_amount": "6798.00", "total_amount": "52118.00"}
    )
    assert grand_total_adds_up(context) == []


def test_grand_total_fails() -> None:
    context = ctx(
        fields={"subtotal": "45320.00", "vat_amount": "6798.00", "total_amount": "52000.00"}
    )
    findings = grand_total_adds_up(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].field_key == "total_amount"
    assert "52118.00" in findings[0].message_en


def test_grand_total_not_applicable_when_incomplete() -> None:
    assert grand_total_adds_up(ctx(fields={"subtotal": "1.00"})) is None


# --------------------------------------------------------------------------- #
# NEGATIVE_AMOUNT
# --------------------------------------------------------------------------- #
def test_negative_amount_is_an_error_on_an_invoice() -> None:
    findings = amounts_are_not_negative(ctx(fields={"total_amount": "-100.00"}))
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].field_key == "total_amount"


def test_negative_amount_is_allowed_on_a_credit_note() -> None:
    context = ctx(fields={"total_amount": "-100.00"}, invoice_type_code="381")
    assert amounts_are_not_negative(context) is None


def test_positive_amounts_pass() -> None:
    assert amounts_are_not_negative(ctx(fields={"total_amount": "100.00"})) == []


def test_zero_is_not_negative() -> None:
    assert amounts_are_not_negative(ctx(fields={"total_amount": "0.00"})) == []


def test_negative_amount_not_applicable_without_amounts() -> None:
    assert amounts_are_not_negative(ctx(fields={"seller_name": "Acme"})) is None


# --------------------------------------------------------------------------- #
# TRN_FORMAT (renamed from TRN_CHECKSUM: the check digit's algorithm is not
# published, so nothing here ever verified a checksum — the old name claimed a
# check this code cannot do)
# --------------------------------------------------------------------------- #
def test_valid_trns_pass() -> None:
    context = ctx(fields={"seller_trn": VALID_TRN, "buyer_trn": OTHER_TRN})
    assert trns_are_structurally_valid(context) == []


def test_a_head_office_trn_passes() -> None:
    """The bug this rule replaces: it used to require the 11th digit — the
    first of three BRANCH digits — to be '1'. It is '0' for every head office,
    which is most Saudi companies, including the two on a real invoice that
    was wrongly blocked by the old rule."""
    context = ctx(fields={"seller_trn": "399999999900003", "buyer_trn": "388888888800003"})
    assert trns_are_structurally_valid(context) == []


def test_invalid_seller_trn_is_an_error() -> None:
    findings = trns_are_structurally_valid(ctx(fields={"seller_trn": "123"}))
    assert findings is not None and len(findings) == 1
    assert findings[0].field_key == "seller_trn"
    assert findings[0].severity is Severity.ERROR
    assert "15" in findings[0].message_en
    assert "11th" not in findings[0].message_en, "the old, wrong constraint must not be quoted"


def test_both_trns_can_fail_independently() -> None:
    context = ctx(fields={"seller_trn": "123", "buyer_trn": "456"})
    findings = trns_are_structurally_valid(context)
    assert findings is not None and len(findings) == 2
    assert {f.field_key for f in findings} == {"seller_trn", "buyer_trn"}


def test_absent_buyer_trn_is_not_a_failure() -> None:
    """Simplified invoices legitimately omit it."""
    context = ctx(fields={"seller_trn": VALID_TRN, "buyer_trn": None})
    assert trns_are_structurally_valid(context) == []


def test_trn_rule_not_applicable_when_no_trn_present() -> None:
    assert trns_are_structurally_valid(ctx(fields={})) is None


# --------------------------------------------------------------------------- #
# TRN_TAX_TYPE_UNEXPECTED — informational, never blocks
# --------------------------------------------------------------------------- #
def test_a_vat_tax_type_passes_quietly() -> None:
    context = ctx(fields={"seller_trn": VALID_TRN})
    assert trn_tax_type_is_vat(context) == []


def test_a_non_vat_tax_type_is_a_warning_not_an_error() -> None:
    # 15 digits, starts and ends with 3 (TRN_FORMAT-valid); tax type "13", not "03".
    context = ctx(fields={"seller_trn": "310122393500013"})
    findings = trn_tax_type_is_vat(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].field_key == "seller_trn"


def test_a_malformed_trn_is_left_to_the_format_rule() -> None:
    """Not applicable, not passing: nothing to say about the tax type of a TRN
    that is not even shaped like one — TRN_FORMAT already reports that."""
    assert trn_tax_type_is_vat(ctx(fields={"seller_trn": "123"})) is None


def test_tax_type_rule_not_applicable_when_no_trn_present() -> None:
    assert trn_tax_type_is_vat(ctx(fields={})) is None


# --------------------------------------------------------------------------- #
# VAT_CATEGORY_VALID
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("category", ["S", "Z", "E", "O", "s", " z "])
def test_known_vat_categories_pass(category: str) -> None:
    assert vat_category_is_known(ctx(vat_category=category)) == []


def test_unknown_vat_category_is_an_error() -> None:
    findings = vat_category_is_known(ctx(vat_category="X"))
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "S" in findings[0].message_en


def test_vat_category_not_applicable_when_absent() -> None:
    assert vat_category_is_known(ctx()) is None


# --------------------------------------------------------------------------- #
# VAT_RATE_CONSISTENT
# --------------------------------------------------------------------------- #
def test_standard_category_requires_fifteen_percent() -> None:
    assert vat_rate_matches_category(ctx(vat_category="S", vat_percent=Decimal("15"))) == []


def test_standard_category_at_zero_percent_is_an_error() -> None:
    findings = vat_rate_matches_category(ctx(vat_category="S", vat_percent=Decimal("0")))
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "15" in findings[0].message_en


@pytest.mark.parametrize("category", ["Z", "E"])
def test_zero_rated_and_exempt_require_zero_percent(category: str) -> None:
    assert vat_rate_matches_category(ctx(vat_category=category, vat_percent=Decimal("0"))) == []
    findings = vat_rate_matches_category(ctx(vat_category=category, vat_percent=Decimal("15")))
    assert findings is not None and len(findings) == 1


def test_out_of_scope_implies_no_rate() -> None:
    assert vat_rate_matches_category(ctx(vat_category="O", vat_percent=Decimal("7"))) is None


def test_vat_rate_not_applicable_without_both_inputs() -> None:
    assert vat_rate_matches_category(ctx(vat_category="S")) is None
    assert vat_rate_matches_category(ctx(vat_percent=Decimal("15"))) is None


# --------------------------------------------------------------------------- #
# INVOICE_TYPE_THRESHOLD
# --------------------------------------------------------------------------- #
SIMPLIFIED = "0200000"
STANDARD = "0100000"


def test_simplified_invoice_under_threshold_passes() -> None:
    context = ctx(fields={"total_amount": "999.99"}, invoice_type_name=SIMPLIFIED)
    assert simplified_invoice_below_threshold(context) == []


def test_simplified_invoice_at_threshold_warns() -> None:
    """At, not just above — the rule is >= 1000."""
    context = ctx(fields={"total_amount": "1000.00"}, invoice_type_name=SIMPLIFIED)
    findings = simplified_invoice_below_threshold(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_standard_invoice_is_not_subject_to_the_threshold() -> None:
    context = ctx(fields={"total_amount": "500000.00"}, invoice_type_name=STANDARD)
    assert simplified_invoice_below_threshold(context) is None


def test_threshold_not_applicable_without_a_total() -> None:
    assert simplified_invoice_below_threshold(ctx(invoice_type_name=SIMPLIFIED)) is None


# --------------------------------------------------------------------------- #
# QR_TOTAL_MATCH
# --------------------------------------------------------------------------- #
def test_qr_totals_match() -> None:
    context = ctx(
        fields={"total_amount": "52118.00", "vat_amount": "6798.00"},
        qr_decoded={QR_TAG_TOTAL_WITH_VAT: "52118.00", QR_TAG_VAT_TOTAL: "6798.00"},
    )
    assert qr_totals_match_extracted(context) == []


def test_qr_total_disagreement_is_an_error() -> None:
    context = ctx(
        fields={"total_amount": "52118.00", "vat_amount": "6798.00"},
        qr_decoded={QR_TAG_TOTAL_WITH_VAT: "99999.00", QR_TAG_VAT_TOTAL: "6798.00"},
    )
    findings = qr_totals_match_extracted(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].field_key == "total_amount"
    assert findings[0].severity is Severity.ERROR


def test_qr_vat_disagreement_is_reported_separately() -> None:
    context = ctx(
        fields={"total_amount": "52118.00", "vat_amount": "6798.00"},
        qr_decoded={QR_TAG_TOTAL_WITH_VAT: "52118.00", QR_TAG_VAT_TOTAL: "1.00"},
    )
    findings = qr_totals_match_extracted(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].field_key == "vat_amount"


def test_qr_rule_not_applicable_without_a_qr() -> None:
    assert qr_totals_match_extracted(ctx(fields={"total_amount": "1.00"})) is None


def test_qr_rule_not_applicable_when_nothing_comparable() -> None:
    context = ctx(qr_decoded={QR_TAG_TOTAL_WITH_VAT: "52118.00"})
    assert qr_totals_match_extracted(context) is None


# --------------------------------------------------------------------------- #
# SEQUENCE_FIELDS_PRESENT
# --------------------------------------------------------------------------- #
def test_standard_invoice_with_icv_and_pih_passes() -> None:
    context = ctx(invoice_type_name=STANDARD, has_embedded_ubl=True, has_icv=True, has_pih=True)
    assert standard_invoice_has_sequence_fields(context) == []


def test_standard_invoice_missing_both_names_both() -> None:
    context = ctx(invoice_type_name=STANDARD, has_embedded_ubl=True)
    findings = standard_invoice_has_sequence_fields(context)
    assert findings is not None and len(findings) == 1
    assert "ICV" in findings[0].message_en
    assert "PIH" in findings[0].message_en
    assert findings[0].severity is Severity.WARNING


def test_standard_invoice_missing_only_pih() -> None:
    context = ctx(invoice_type_name=STANDARD, has_embedded_ubl=True, has_icv=True)
    findings = standard_invoice_has_sequence_fields(context)
    assert findings is not None
    assert "PIH" in findings[0].message_en
    assert "ICV" not in findings[0].message_en


def test_sequence_rule_not_applicable_without_ubl() -> None:
    """A plain scan lacking ICV says nothing about supplier compliance."""
    context = ctx(invoice_type_name=STANDARD, has_embedded_ubl=False)
    assert standard_invoice_has_sequence_fields(context) is None


def test_sequence_rule_not_applicable_to_simplified_invoices() -> None:
    context = ctx(invoice_type_name=SIMPLIFIED, has_embedded_ubl=True)
    assert standard_invoice_has_sequence_fields(context) is None


# --------------------------------------------------------------------------- #
# XML_PDF_MISMATCH
# --------------------------------------------------------------------------- #
def test_xml_and_model_agreeing_passes() -> None:
    context = ctx(
        fields={
            "invoice_number": FieldView(
                key="invoice_number",
                value="SA-2026-0334",
                source="ubl_xml",
                shadow_value="SA-2026-0334",
            )
        }
    )
    assert xml_and_model_agree(context) == []


def test_xml_and_model_disagreeing_is_an_error_showing_both() -> None:
    context = ctx(
        fields={
            "invoice_number": FieldView(
                key="invoice_number",
                value="SA-2026-0334",
                source="ubl_xml",
                shadow_value="SA-2026-9999",
            )
        }
    )
    findings = xml_and_model_agree(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "SA-2026-0334" in findings[0].message_en
    assert "SA-2026-9999" in findings[0].message_en


def test_formatting_only_difference_is_not_a_mismatch() -> None:
    """Arabic-Indic digits versus ASCII is not a disagreement."""
    context = ctx(
        fields={
            "total_amount": FieldView(
                key="total_amount",
                value="52118.00",
                source="ubl_xml",
                shadow_value="٥٢١١٨.٠٠",
            )
        }
    )
    assert xml_and_model_agree(context) == []


def test_mismatch_rule_not_applicable_without_a_shadow_value() -> None:
    context = ctx(
        fields={"invoice_number": FieldView(key="invoice_number", value="X", source="ubl_xml")}
    )
    assert xml_and_model_agree(context) is None


def test_mismatch_rule_ignores_non_ubl_fields() -> None:
    context = ctx(
        fields={
            "invoice_number": FieldView(
                key="invoice_number", value="A", source="vlm", shadow_value="B"
            )
        }
    )
    assert xml_and_model_agree(context) is None


def test_equal_amounts_written_differently_are_not_a_mismatch() -> None:
    """2.30 in the XML and 2.3 from the model are one number. Compared as
    strings they 'disagree', which blocked a correct invoice."""
    context = ctx(
        fields={
            "vat_amount": FieldView(
                key="vat_amount", value="2.30", source="ubl_xml", shadow_value="2.3"
            )
        },
        numeric_keys=frozenset({"vat_amount"}),
    )
    assert xml_and_model_agree(context) == []


def test_different_amounts_are_still_a_mismatch() -> None:
    context = ctx(
        fields={
            "vat_amount": FieldView(
                key="vat_amount", value="2.30", source="ubl_xml", shadow_value="2.31"
            )
        },
        numeric_keys=frozenset({"vat_amount"}),
    )
    findings = xml_and_model_agree(context)
    assert findings is not None and [f.field_key for f in findings] == ["vat_amount"]


def test_a_non_numeric_field_is_still_compared_as_text() -> None:
    """Decimal comparison is for amounts only: invoice numbers "0012" and "12"
    are different invoices."""
    context = ctx(
        fields={
            "invoice_number": FieldView(
                key="invoice_number", value="0012", source="ubl_xml", shadow_value="12"
            )
        },
        numeric_keys=frozenset({"total_amount"}),
    )
    findings = xml_and_model_agree(context)
    assert findings is not None and len(findings) == 1


# --------------------------------------------------------------------------- #
# OCR_SUBSTRING_MISSING — the anti-hallucination guard
# --------------------------------------------------------------------------- #
PAGE = "TAX INVOICE Invoice No: SA-2026-0334 Subtotal: 45,320.00 VAT: 6798.00 Total: 52118.00"


def test_value_present_on_the_page_passes() -> None:
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="52118.00", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text=PAGE,
    )
    assert numeric_values_appear_on_the_page(context) == []


def test_fabricated_value_is_caught() -> None:
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="99999.99", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text=PAGE,
    )
    findings = numeric_values_appear_on_the_page(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].field_key == "total_amount"
    assert "99999.99" in findings[0].message_en


def test_thousands_separator_difference_is_not_a_hallucination() -> None:
    """The page prints 45,320.00; the model returned 45320.00."""
    context = ctx(
        fields={"subtotal": FieldView(key="subtotal", value="45320.00", source="vlm")},
        numeric_keys=frozenset({"subtotal"}),
        page_text=PAGE,
    )
    assert numeric_values_appear_on_the_page(context) == []


def test_arabic_indic_digits_on_the_page_still_match() -> None:
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="52118.00", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text="الإجمالي ٥٢١١٨٫٠٠",
    )
    assert numeric_values_appear_on_the_page(context) == []


def test_ubl_values_are_exempt_from_the_page_check() -> None:
    """A signed XML value need not be printed on the face of the invoice."""
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="99999.99", source="ubl_xml")},
        numeric_keys=frozenset({"total_amount"}),
        page_text=PAGE,
    )
    assert numeric_values_appear_on_the_page(context) is None


def test_non_numeric_fields_are_not_checked() -> None:
    context = ctx(
        fields={"seller_name": FieldView(key="seller_name", value="Nowhere Ltd", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text=PAGE,
    )
    assert numeric_values_appear_on_the_page(context) is None


def test_null_values_are_not_flagged_as_hallucinations() -> None:
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value=None, source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text=PAGE,
    )
    assert numeric_values_appear_on_the_page(context) is None


def test_rule_not_applicable_when_no_text_was_extracted() -> None:
    """An unreadable page is already reported; per-field noise helps nobody."""
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="1.00", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text="   ",
    )
    assert numeric_values_appear_on_the_page(context) is None


def test_an_amount_printed_with_fewer_decimals_is_found() -> None:
    """The model returned 2.30; the receipt prints 2.3. Same number — neither the
    substring check nor the digits-only check sees it, the Decimal check does."""
    context = ctx(
        fields={"vat_amount": FieldView(key="vat_amount", value="2.30", source="vlm")},
        numeric_keys=frozenset({"vat_amount"}),
        page_text="Total 17.65 VAT 2.3",
    )
    assert numeric_values_appear_on_the_page(context) == []


def test_a_different_amount_is_still_caught_after_the_decimal_check() -> None:
    context = ctx(
        fields={"vat_amount": FieldView(key="vat_amount", value="2.40", source="vlm")},
        numeric_keys=frozenset({"vat_amount"}),
        page_text="Total 17.65 VAT 2.3",
    )
    findings = numeric_values_appear_on_the_page(context)
    assert findings is not None and [f.field_key for f in findings] == ["vat_amount"]


def test_several_amounts_share_one_parse_of_the_page() -> None:
    """Two values that both need the numeric check: the page's numbers are
    parsed once and reused, and both still match."""
    context = ctx(
        fields={
            "vat_amount": FieldView(key="vat_amount", value="2.30", source="vlm"),
            "total_amount": FieldView(key="total_amount", value="17.650", source="vlm"),
        },
        numeric_keys=frozenset({"vat_amount", "total_amount"}),
        page_text="Total 17.65 VAT 2.3",
    )
    assert numeric_values_appear_on_the_page(context) == []


def test_an_amount_that_does_not_parse_is_still_caught() -> None:
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="12.3.4", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text="Total 17.65 VAT 2.3",
    )
    findings = numeric_values_appear_on_the_page(context)
    assert findings is not None and [f.field_key for f in findings] == ["total_amount"]


def test_same_value_falls_back_to_text_for_an_amount_that_does_not_parse() -> None:
    assert same_value("n/a", "N/A", numeric=True) is True
    assert same_value("n/a", "none", numeric=True) is False
    assert same_value("2.3", "2.30", numeric=True) is True
    assert same_value("2.3", "2.30", numeric=False) is False


def test_qr_values_are_exempt_from_the_page_check() -> None:
    """Decoded from the ZATCA QR, which is authoritative like the signed XML —
    and may legitimately format an amount differently from the printed page."""
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="17.65", source="qr")},
        numeric_keys=frozenset({"total_amount"}),
        page_text="Total incl. VAT SAR 17.650",
    )
    assert numeric_values_appear_on_the_page(context) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-02-10", date(2026, 2, 10)),
        ("2026-02-10T09:30:00Z", date(2026, 2, 10)),  # a ZATCA QR timestamp
        ("10/02/2026", date(2026, 2, 10)),  # day first, as Saudi invoices print it
        ("10-2-2026", date(2026, 2, 10)),
        ("١٠/٠٢/٢٠٢٦", date(2026, 2, 10)),
        ("2026-02-30", None),  # shaped like a date, but not one
        ("yesterday", None),
        (None, None),
    ],
)
def test_to_date_reads_the_ways_invoices_print_a_date(raw: str | None, expected: date) -> None:
    assert to_date(raw) == expected


def test_a_qr_date_the_model_read_differently_is_flagged() -> None:
    context = ctx(
        fields={
            "issue_date": FieldView(
                key="issue_date", value="2026-02-10", source="qr", shadow_value="2026-02-11"
            ),
            "seller_trn": FieldView(
                key="seller_trn", value="300000000000003", source="qr",
                shadow_value="300000000000003",
            ),
        },
    )
    findings = qr_and_model_agree(context)
    assert findings is not None
    assert [f.field_key for f in findings] == ["issue_date"]


def test_computed_values_are_exempt_from_the_page_check() -> None:
    """A subtotal derived as total - VAT is, by construction, not printed."""
    context = ctx(
        fields={"subtotal": FieldView(key="subtotal", value="15.35", source="computed")},
        numeric_keys=frozenset({"subtotal"}),
        page_text="Total 17.65 VAT 2.30",
    )
    assert numeric_values_appear_on_the_page(context) is None


# --------------------------------------------------------------------------- #
# ARABIC_ENCODING_SUSPECT
# --------------------------------------------------------------------------- #
ARABIC_PAGE = "فاتورة ضريبية شركة الجزيرة"


def test_arabic_names_present_in_xml_pass() -> None:
    context = ctx(
        fields={
            "seller_name": FieldView(key="seller_name", value="شركة الجزيرة", source="ubl_xml")
        },
        has_embedded_ubl=True,
        pdf_has_arabic=True,
    )
    assert arabic_survived_the_xml(context) == []


def test_empty_xml_name_against_an_arabic_page_is_flagged() -> None:
    context = ctx(
        fields={"seller_name": FieldView(key="seller_name", value="", source="ubl_xml")},
        has_embedded_ubl=True,
        pdf_has_arabic=True,
    )
    findings = arabic_survived_the_xml(context)
    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].field_key == "seller_name"


def test_replacement_characters_are_flagged_as_mojibake() -> None:
    context = ctx(
        fields={"seller_name": FieldView(key="seller_name", value="���", source="ubl_xml")},
        has_embedded_ubl=True,
        pdf_has_arabic=True,
    )
    findings = arabic_survived_the_xml(context)
    assert findings is not None and len(findings) == 1


def test_latin_supplier_name_is_not_mojibake() -> None:
    """A supplier may legitimately have an ASCII name."""
    context = ctx(
        fields={
            "seller_name": FieldView(
                key="seller_name", value="Jubail Maintenance Services Ltd.", source="ubl_xml"
            )
        },
        has_embedded_ubl=True,
        pdf_has_arabic=True,
    )
    assert arabic_survived_the_xml(context) == []


def test_encoding_rule_not_applicable_without_ubl_or_arabic() -> None:
    fields = {"seller_name": FieldView(key="seller_name", value="", source="ubl_xml")}
    assert arabic_survived_the_xml(ctx(fields=fields, pdf_has_arabic=True)) is None
    assert arabic_survived_the_xml(ctx(fields=fields, has_embedded_ubl=True)) is None


def test_encoding_rule_ignores_non_ubl_names() -> None:
    context = ctx(
        fields={"seller_name": FieldView(key="seller_name", value="", source="vlm")},
        has_embedded_ubl=True,
        pdf_has_arabic=True,
    )
    assert arabic_survived_the_xml(context) is None


# --------------------------------------------------------------------------- #
# REQUIRED_FIELD_MISSING — a null required field must never look settled
# --------------------------------------------------------------------------- #
def test_a_null_required_field_is_flagged_for_review() -> None:
    """The gap this closes: on a real invoice the model returned null for a
    required subtotal and the field was recorded auto_validated — green — because
    its label was printed with a generic word the silent-miss check did not know.
    Nothing but an unrelated blank page kept that document from looking done."""
    context = ctx(
        fields={"subtotal": None, "total_amount": "115.00"},
        required_keys=frozenset({"subtotal", "total_amount"}),
    )

    findings = required_fields_are_present(context)

    assert findings is not None and len(findings) == 1
    finding = findings[0]
    assert finding.code == "REQUIRED_FIELD_MISSING"
    assert finding.field_key == "subtotal"
    assert finding.severity is Severity.WARNING, "review_suggested, not blocking"
    assert finding.passed is False
    assert "subtotal" in finding.message_en
    assert "subtotal" in finding.message_ar
    assert any("؀" <= ch <= "ۿ" for ch in finding.message_ar)


def test_every_null_required_field_gets_its_own_finding() -> None:
    context = ctx(
        fields={"subtotal": None, "vat_amount": None, "total_amount": "10.00"},
        required_keys=frozenset({"subtotal", "vat_amount", "total_amount"}),
    )

    findings = required_fields_are_present(context)

    assert findings is not None
    assert sorted(f.field_key or "" for f in findings) == ["subtotal", "vat_amount"]


def test_a_blank_required_value_counts_as_null() -> None:
    """A reviewer clearing a field leaves an empty string, not None."""
    context = ctx(fields={"subtotal": "   "}, required_keys=frozenset({"subtotal"}))

    findings = required_fields_are_present(context)

    assert findings is not None and [f.field_key for f in findings] == ["subtotal"]


def test_a_required_field_with_no_row_at_all_is_flagged() -> None:
    context = ctx(fields={"total_amount": "10.00"}, required_keys=frozenset({"subtotal"}))

    findings = required_fields_are_present(context)

    assert findings is not None and [f.field_key for f in findings] == ["subtotal"]


def test_present_required_fields_pass() -> None:
    context = ctx(
        fields={"subtotal": "100.00", "total_amount": "115.00"},
        required_keys=frozenset({"subtotal", "total_amount"}),
    )

    assert required_fields_are_present(context) == []


def test_a_null_optional_field_is_not_flagged() -> None:
    """A correct null for an optional field is a negative example, not a gap."""
    context = ctx(
        fields={"purchase_order_number": None, "total_amount": "10.00"},
        required_keys=frozenset({"total_amount"}),
    )

    assert required_fields_are_present(context) == []


def test_a_schema_with_no_required_fields_is_not_applicable() -> None:
    assert required_fields_are_present(ctx(fields={"subtotal": None})) is None


def test_a_missing_required_field_marks_the_field_warned_but_never_blocks() -> None:
    """Through the engine, which is what the pipeline and revalidation read:
    the field lands in warned_field_keys (auto_validated -> review_suggested)
    and not in blockers, so a reviewer can still confirm a genuinely absent
    field after checking it."""
    report = run_rules(ctx(fields={"subtotal": None}, required_keys=frozenset({"subtotal"})))

    assert "subtotal" in report.warned_field_keys
    assert "subtotal" not in report.blocking_field_keys
    assert "REQUIRED_FIELD_MISSING" not in report.blockers


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
def test_every_rule_has_bilingual_messages() -> None:
    """Arabic messages are a product requirement, not a nice-to-have."""
    for code, spec in registry().items():
        assert spec.message_en.strip(), f"{code} has no English message"
        assert spec.message_ar.strip(), f"{code} has no Arabic message"
        assert any("؀" <= ch <= "ۿ" for ch in spec.message_ar), (
            f"{code}'s Arabic message contains no Arabic script"
        )


def test_clean_invoice_produces_no_blockers() -> None:
    context = ctx(
        fields={
            "subtotal": FieldView(key="subtotal", value="45320.00", source="vlm"),
            "vat_amount": FieldView(key="vat_amount", value="6798.00", source="vlm"),
            "total_amount": FieldView(key="total_amount", value="52118.00", source="vlm"),
            "seller_trn": FieldView(key="seller_trn", value=VALID_TRN, source="vlm"),
        },
        numeric_keys=frozenset({"subtotal", "vat_amount", "total_amount"}),
        page_text=PAGE,
        vat_category="S",
        vat_percent=Decimal("15"),
    )
    report = run_rules(context)
    assert report.blockers == []
    assert report.is_confirmable is True


def test_broken_invoice_reports_blockers_and_blocks_confirmation() -> None:
    context = ctx(
        fields={
            "subtotal": FieldView(key="subtotal", value="45320.00", source="vlm"),
            "vat_amount": FieldView(key="vat_amount", value="6798.00", source="vlm"),
            "total_amount": FieldView(key="total_amount", value="52000.00", source="vlm"),
            "seller_trn": FieldView(key="seller_trn", value="123", source="vlm"),
        },
        numeric_keys=frozenset({"subtotal", "vat_amount", "total_amount"}),
        page_text=PAGE,
    )
    report = run_rules(context)

    assert "GRAND_TOTAL_MISMATCH" in report.blockers
    assert "TRN_FORMAT" in report.blockers
    assert report.is_confirmable is False
    assert "total_amount" in report.blocking_field_keys
    assert "seller_trn" in report.blocking_field_keys


def test_warnings_do_not_block_confirmation() -> None:
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="5000.00", source="vlm")},
        numeric_keys=frozenset(),
        invoice_type_name=SIMPLIFIED,
        page_text=PAGE,
    )
    report = run_rules(context)
    codes = {r.code for r in report.failures}
    assert "INVOICE_TYPE_THRESHOLD" in codes
    assert report.blockers == []
    assert report.is_confirmable is True


def test_not_applicable_rules_record_nothing() -> None:
    """An empty context should not manufacture passing rows for absent checks."""
    report = run_rules(ctx())
    assert "QR_TOTAL_MATCH" not in {r.code for r in report.results}
    assert "TRN_FORMAT" not in {r.code for r in report.results}


def test_blockers_are_deduplicated_in_order() -> None:
    context = ctx(
        fields={
            "seller_trn": FieldView(key="seller_trn", value="1", source="vlm"),
            "buyer_trn": FieldView(key="buyer_trn", value="2", source="vlm"),
        }
    )
    report = run_rules(context)
    assert report.blockers.count("TRN_FORMAT") == 1


def test_value_that_normalizes_to_nothing_is_skipped() -> None:
    """A value of only invisible characters has nothing to look for."""
    context = ctx(
        fields={"total_amount": FieldView(key="total_amount", value="\u200b\ufeff", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text=PAGE,
    )
    assert numeric_values_appear_on_the_page(context) is None


def test_standard_invoice_missing_only_icv() -> None:
    context = ctx(invoice_type_name=STANDARD, has_embedded_ubl=True, has_pih=True)
    findings = standard_invoice_has_sequence_fields(context)
    assert findings is not None
    assert "ICV" in findings[0].message_en
    assert "PIH" not in findings[0].message_en


def test_duplicate_rule_code_is_rejected_at_import_time() -> None:
    """Two rules sharing a code would silently overwrite one another."""
    from app.services.validation.engine import rule as rule_decorator

    with pytest.raises(ValueError, match="duplicate rule code"):

        @rule_decorator("TRN_FORMAT", Severity.ERROR, message_ar="مكرر", message_en="duplicate")
        def _clash(_ctx: ValidationContext) -> list[RuleResult] | None:  # pragma: no cover
            return None


def test_human_corrections_are_exempt_from_the_ocr_guard() -> None:
    """A reviewer must be able to fix a value OCR misread.

    OCR_SUBSTRING_MISSING exists because MODELS fabricate. A reviewer is looking
    at the rendered page and has authority the model does not — including the
    authority to correct a value the OCR got wrong, which by definition will not
    appear in the OCR text.

    Without this exemption a bad OCR read is permanently unfixable: every
    correction re-triggers the very blocker it was meant to clear, and confirm
    refuses forever.
    """
    ctx = ValidationContext(
        fields={"total_amount": FieldView(key="total_amount", value="51750.00", source="human")},
        numeric_keys=frozenset({"total_amount"}),
        page_text="the page says 99999.00 because OCR misread it",
    )
    assert numeric_values_appear_on_the_page(ctx) is None


def test_a_model_value_absent_from_the_page_still_fails() -> None:
    """The exemption is for humans only — the guard still bites on model output."""
    ctx = ValidationContext(
        fields={"total_amount": FieldView(key="total_amount", value="51750.00", source="vlm")},
        numeric_keys=frozenset({"total_amount"}),
        page_text="the page says 99999.00",
    )
    findings = numeric_values_appear_on_the_page(ctx)
    assert findings
    assert findings[0].code == "OCR_SUBSTRING_MISSING"


# --------------------------------------------------------------------------- #
# SUBTOTAL_EQUALS_TOTAL
#
# Found on a marketplace "purchase summary": it states one amount, the
# tax-INCLUSIVE total, and the model copied it into the subtotal as well.
# --------------------------------------------------------------------------- #
def test_subtotal_equal_to_total_with_no_vat_is_flagged() -> None:
    findings = subtotal_is_not_the_total(
        ctx(fields={"subtotal": "230.00", "total_amount": "230.00"})
    )

    assert findings is not None and len(findings) == 1
    assert findings[0].field_key == "subtotal"
    assert findings[0].severity is Severity.WARNING
    assert not findings[0].passed


def test_a_stated_vat_of_zero_is_a_zero_rated_invoice_not_a_copy() -> None:
    fields = {"subtotal": "230.00", "vat_amount": "0.00", "total_amount": "230.00"}

    assert subtotal_is_not_the_total(ctx(fields=fields)) == []


def test_a_subtotal_below_the_total_passes() -> None:
    fields = {"subtotal": "200.00", "vat_amount": "30.00", "total_amount": "230.00"}

    assert subtotal_is_not_the_total(ctx(fields=fields)) == []


def test_subtotal_rule_does_not_apply_without_both_amounts() -> None:
    assert subtotal_is_not_the_total(ctx(fields={"total_amount": "230.00"})) is None
    assert subtotal_is_not_the_total(ctx(fields={"subtotal": "230.00"})) is None


def test_a_reviewers_own_subtotal_is_not_second_guessed() -> None:
    fields = {
        "subtotal": FieldView(key="subtotal", value="230.00", source="human"),
        "total_amount": "230.00",
    }

    assert subtotal_is_not_the_total(ctx(fields=fields)) is None


def test_a_warned_field_is_reported_for_the_pipeline_to_downgrade() -> None:
    report = run_rules(ctx(fields={"subtotal": "230.00", "total_amount": "230.00"}))

    assert report.warned_field_keys == {"subtotal"}
    assert "SUBTOTAL_EQUALS_TOTAL" not in report.blockers


# --------------------------------------------------------------------------- #
# TEXT_LAYER_FRAGMENTED
#
# The first real invoice's text layer cut Arabic words apart after non-joining
# letters: 40% of its Arabic tokens were single letters and none began with the
# definite article. The model then misread or missed fields. This says so.
# --------------------------------------------------------------------------- #
CLEAN_ARABIC = (
    "ملخص المشتريات البائع شركة الأفق للتجارة الإلكترونية المشتري سلمان بن ناصر الحربي " * 3
)
SHATTERED_ARABIC = (
    "ملخص ا لمشتريا ت ا لبائع شركة ا لأفق للتجا رة "
    "ا لإلكترونيا ت ا لمشتر ي سلما ن بن نا صر ا لحر بي "
) * 3


def test_a_shattered_arabic_text_layer_is_flagged() -> None:
    findings = text_layer_is_intact(ctx(page_text=SHATTERED_ARABIC))

    assert findings is not None and len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].field_key is None


def test_ordinary_arabic_text_passes() -> None:
    assert text_layer_is_intact(ctx(page_text=CLEAN_ARABIC)) == []


def test_a_page_with_almost_no_arabic_is_not_judged() -> None:
    assert text_layer_is_intact(ctx(page_text="Invoice SA-2026-0334 total 52118.00")) is None
    assert text_layer_is_intact(ctx(page_text="ا ب ت ث")) is None
