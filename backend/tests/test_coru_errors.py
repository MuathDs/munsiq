"""Why a field was wrong: one of four causes, decided by rules, not by eye.

The question these categories answer is whether an error is the MODEL's (it
misread characters, or picked another field's value) or the DATA's (the label
is in another style than the page, or names a different one of several valid
numbers). Every value here is invented.
"""

from __future__ import annotations

import pytest

from scripts.coru_errors import CATEGORIES, classify

NO_OTHERS: list[tuple[str, str]] = []


def test_nothing_returned_is_empty() -> None:
    assert classify("total_amount", None, ["229.00"], NO_OTHERS) == "empty"
    assert classify("seller_name", "  ", ["Corner Shop"], NO_OTHERS) == "empty"


@pytest.mark.parametrize(
    ("field", "predicted", "truth"),
    [
        ("invoice_number", "11010000000093352", ["110100000000093352"]),  # a dropped zero
        ("seller_trn", "379-458-249", ["379-456-249"]),  # one digit
        ("total_amount", "229.10", ["LE 229.00"]),
        ("issue_date", "2022-09-13", ["14/09/2022"]),  # one digit of the day
        ("seller_name", "CORNER SH0P", ["Corner Shop"]),  # a letter read as a digit
        ("seller_name", "FRESH BASKT MARKET", ["Fresh Basket Market"]),
    ],
)
def test_a_near_copy_of_the_truth_is_a_misread(
    field: str, predicted: str, truth: list[str]
) -> None:
    assert classify(field, predicted, truth, NO_OTHERS) == "misread"


@pytest.mark.parametrize(
    ("predicted", "truth"),
    [
        ("FRESH BASKET MARKET LAKESIDE", ["Fresh Basket"]),  # the branch added
        ("Fresh Basket Trading Co. LLC", ["Fresh Basket"]),  # the legal name
        ("Basket", ["Fresh Basket Market"]),  # a short form of it
        ("صيدلية النور", ["Al Noor Pharmacy"]),  # the page's script, not the label's
    ],
)
def test_the_same_shop_named_another_way_is_label_style(predicted: str, truth: list[str]) -> None:
    assert classify("seller_name", predicted, truth, NO_OTHERS) == "label_style"


def test_another_number_printed_on_the_receipt_is_label_style() -> None:
    """A receipt prints several numbers. Returning its order number where the
    label holds its transaction number is a difference of convention."""
    others = [("What is the order number?", "88213"), ("Who was the cashier?", "07")]
    assert classify("invoice_number", "88213", ["004518"], others) == "label_style"
    assert classify("invoice_number", "#88213", ["004518"], others) == "label_style"


def test_a_name_that_is_the_receipts_company_name_is_label_style() -> None:
    """Our field asks for the seller; the label holds the storefront."""
    others = [("What is the name of the company?", "Lakeside Retail Group")]
    assert classify("seller_name", "Lakeside Retail Group", ["Fresh Basket"], others) == (
        "label_style"
    )


def test_the_same_digits_in_an_unreadable_date_format_is_label_style() -> None:
    assert classify("issue_date", "17|03|2026", ["17/03/2026"], NO_OTHERS) == "label_style"


@pytest.mark.parametrize(
    ("field", "predicted", "truth", "others"),
    [
        # the subtotal returned as the total
        ("total_amount", "425.00", ["484.50"], [("What is the subtotal?", "425.00")]),
        # the delivery date returned as the date
        (
            "issue_date",
            "2026-03-19",
            ["17/03/2026"],
            [("What is the delivery date?", "19/03/2026")],
        ),
        # the cash tendered returned as the VAT
        ("vat_amount", "500", ["59.50"], [("How much cash was paid?", "EGP 500.00")]),
        # a phone number returned as the VAT number
        (
            "seller_trn",
            "0223456789",
            ["512-774-930"],
            [("What is the hotline number?", "0223456789")],
        ),
    ],
)
def test_another_fields_value_is_a_wrong_field(
    field: str, predicted: str, truth: list[str], others: list[tuple[str, str]]
) -> None:
    assert classify(field, predicted, truth, others) == "wrong_field"


def test_a_value_matching_nothing_annotated_is_unclassified() -> None:
    """Neither near the truth nor any other annotated value: it may be invented,
    or simply printed and not annotated. Not guessed into a category."""
    assert classify("total_amount", "9999.99", ["484.50"], NO_OTHERS) == "unclassified"
    assert classify("seller_name", "Harbour Tools", ["Fresh Basket"], NO_OTHERS) == "unclassified"


def test_exactly_another_fields_value_beats_being_near_the_truth() -> None:
    """425.00 is one digit from 426.00, but it IS the receipt's subtotal."""
    others = [("What is the subtotal?", "425.00")]
    assert classify("total_amount", "425.00", ["426.00"], others) == "wrong_field"


def test_the_categories_are_the_five_reported() -> None:
    assert CATEGORIES == ("misread", "label_style", "wrong_field", "empty", "unclassified")


def test_the_same_digits_in_another_number_format_is_label_style() -> None:
    """CORU sometimes writes a decimal comma. The scorer reads '24,44' as 24,
    so a correct '24.44' is marked wrong - the label's format, not the model."""
    assert classify("vat_amount", "24.44", ["*24,44"], NO_OTHERS) == "label_style"
    assert classify("total_amount", "1250.00", ["1.250,00"], NO_OTHERS) == "label_style"
    assert classify("total_amount", "24.45", ["*24,44"], NO_OTHERS) != "label_style"


def test_a_label_that_is_not_itself_a_value_is_label_style() -> None:
    """A date label of '6/24/202-' can match nothing; no answer could be right."""
    assert classify("issue_date", "6/24/2022", ["6/24/202-"], NO_OTHERS) == "label_style"
    assert classify("total_amount", "88.00", ["see receipt"], NO_OTHERS) == "label_style"
