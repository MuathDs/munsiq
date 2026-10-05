"""Scoring a public receipt set (CORU) against its ground truth.

Exact match AFTER normalization — amounts as Decimals, dates as dates — and the
validation catch rate: of the fields the model got wrong, how many the rules
flagged. Every value here is invented; no CORU receipt appears in a test.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from scripts.coru_eval import (
    FieldOutcome,
    Scoreboard,
    date_readings,
    fuzzy_name_match,
    matches,
    parse_amount,
    render,
    score_field,
)


# --------------------------------------------------------------------------- #
# Amounts
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("LE 3,754.00", Decimal("3754.00")),
        ("EGP 88.00", Decimal("88.00")),
        ("153.51 EGP", Decimal("153.51")),
        ("*299.00", Decimal("299.00")),
        ("LE124.50", Decimal("124.50")),
        ("36.72", Decimal("36.72")),
        ("٨٨٫٥٠", Decimal("88.50")),  # Arabic-Indic digits and decimal separator
        ("n/a", None),
        ("", None),
    ],
)
def test_an_amount_is_read_past_its_currency_marker(raw: str, expected: Decimal | None) -> None:
    assert parse_amount(raw) == expected


def test_amounts_match_as_numbers_not_as_text() -> None:
    assert matches("total_amount", "229", ["LE 229.00"])
    assert matches("vat_amount", "0", ["0.00"])
    assert not matches("total_amount", "229.10", ["LE 229.00"])
    assert not matches("total_amount", "two hundred", ["LE 229.00"])


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2023-11-18", {date(2023, 11, 18)}),
        ("14/09/2022", {date(2022, 9, 14)}),  # only day-first is a real date
        ("11/29/2022", {date(2022, 11, 29)}),  # only month-first is
        ("6/11/2022 3:21:27 PM", {date(2022, 11, 6), date(2022, 6, 11)}),  # either
        ("19-03-2022", {date(2022, 3, 19)}),
        ("Sep 9, 2022", {date(2022, 9, 9)}),
        ("9 September 2022", {date(2022, 9, 9)}),
        ("16-May-21", {date(2021, 5, 16)}),
        ("03.11.21", {date(2021, 11, 3), date(2021, 3, 11)}),
        ("12:00:00 AM", set()),
        ("yesterday", set()),
    ],
)
def test_a_date_is_read_in_every_way_it_could_have_been_meant(
    raw: str, expected: set[date]
) -> None:
    assert date_readings(raw) == expected


def test_a_date_matches_when_any_reading_agrees() -> None:
    """The ground truth mixes day-first and month-first with no marker, so an
    ambiguous one is accepted under either reading rather than guessed."""
    assert matches("issue_date", "2022-11-06", ["6/11/2022"])
    assert matches("issue_date", "2022-06-11", ["6/11/2022"])
    assert matches("issue_date", "06/11/2022", ["6/11/2022 3:21:27 PM"])
    assert not matches("issue_date", "2022-09-13", ["14/09/2022"])
    assert not matches("issue_date", "no date", ["14/09/2022"])


# --------------------------------------------------------------------------- #
# Text fields
# --------------------------------------------------------------------------- #
def test_a_name_matches_whatever_its_case_and_spacing() -> None:
    assert matches("seller_name", "Gourmet  Food Stores", ["GOURMET FOOD STORES"])
    assert matches("seller_name", "Gourmet Food Stores.", ["GOURMET FOOD STORES"])
    assert not matches("seller_name", "Gourmet", ["GOURMET FOOD STORES"])


def test_the_fuzzy_name_column_accepts_a_near_miss_but_not_another_store() -> None:
    """Reported NEXT TO the strict column, never instead of it."""
    assert fuzzy_name_match("Gourmet Food Store", ["GOURMET FOOD STORES"])
    assert fuzzy_name_match("Gourmet", ["GOURMET FOOD STORES"])  # the printed short name
    assert not fuzzy_name_match("Al Noor Pharmacy", ["GOURMET FOOD STORES"])
    assert not fuzzy_name_match(None, ["GOURMET FOOD STORES"])


def test_any_printed_receipt_number_is_a_right_answer() -> None:
    """A receipt can print a transaction number and a receipt number; the
    ground truth lists both and either counts."""
    assert matches("invoice_number", "#214679", ["000-88", "214679"])
    assert matches("invoice_number", "inv 77a", ["INV-77A"])
    assert not matches("invoice_number", "214670", ["000-88", "214679"])


def test_a_vat_number_matches_through_spaces_and_hyphens() -> None:
    assert matches("seller_trn", "310-122-393", ["310 122 393"])
    assert not matches("seller_trn", "310122394", ["310 122 393"])


# --------------------------------------------------------------------------- #
# One field's outcome
# --------------------------------------------------------------------------- #
def test_a_field_is_correct_wrong_or_missing() -> None:
    assert score_field("total_amount", "229.00", ["LE 229.00"]).status == "correct"
    assert score_field("total_amount", "230.00", ["LE 229.00"]).status == "wrong"
    assert score_field("total_amount", None, ["LE 229.00"]).status == "missing"
    assert score_field("total_amount", "  ", ["LE 229.00"]).status == "missing"


def test_the_flags_ride_along_with_the_outcome() -> None:
    outcome = score_field(
        "total_amount", "230.00", ["LE 229.00"], rule_flagged=True, shown_green=False
    )
    assert (outcome.status, outcome.rule_flagged, outcome.shown_green) == ("wrong", True, False)


# --------------------------------------------------------------------------- #
# The scoreboard
# --------------------------------------------------------------------------- #
def outcome(
    field: str, status: str, *, flagged: bool = False, green: bool = True, fuzzy: bool = False
) -> FieldOutcome:
    return FieldOutcome(
        field=field, status=status, rule_flagged=flagged, shown_green=green, fuzzy_correct=fuzzy
    )


def board() -> Scoreboard:
    scores = Scoreboard(label="test")
    for item in [
        outcome("total_amount", "correct"),
        outcome("total_amount", "correct", flagged=True, green=False),  # a false alarm
        outcome("total_amount", "wrong", flagged=True, green=False),  # caught by a rule
        outcome("total_amount", "missing", green=False),  # amber, but no rule named it
        outcome("seller_name", "wrong", fuzzy=True),  # silent: wrong and shown green
        outcome("seller_name", "correct", fuzzy=True),
        outcome("seller_trn", "wrong", flagged=True, green=False),
        outcome("seller_trn", "correct", flagged=True, green=False),
    ]:
        scores.add(item)
    scores.documents, scores.seconds = 2, 50.0
    return scores


def test_accuracy_is_correct_over_fields_with_ground_truth() -> None:
    scores = board()
    assert scores.accuracy("total_amount") == pytest.approx(2 / 4)
    assert scores.accuracy() == pytest.approx(4 / 8)
    assert scores.fuzzy_accuracy("seller_name") == pytest.approx(2 / 2)


def test_catch_rate_is_flagged_wrong_fields_over_wrong_fields() -> None:
    """Wrong means not correct: a wrong value or a missing one."""
    scores = board()
    # 4 not-correct fields: total wrong (flagged), total missing (not),
    # name wrong (not), trn wrong (flagged).
    assert scores.catch_rate() == pytest.approx(2 / 4)
    assert scores.catch_rate(exclude=frozenset({"seller_trn"})) == pytest.approx(1 / 3)


def test_not_shown_green_is_the_wider_catch() -> None:
    """A field can be amber with no rule naming it (low confidence, a silent
    miss). Counted separately so the two are never confused."""
    assert board().not_green_rate() == pytest.approx(3 / 4)


def test_false_alarms_are_correct_fields_a_rule_flagged() -> None:
    scores = board()
    assert scores.false_alarm_rate() == pytest.approx(2 / 4)
    assert scores.false_alarm_rate(exclude=frozenset({"seller_trn"})) == pytest.approx(1 / 3)


def test_rates_over_nothing_are_none_not_a_division_error() -> None:
    empty = Scoreboard(label="empty")
    assert empty.accuracy() is None
    assert empty.catch_rate() is None
    assert empty.false_alarm_rate() is None
    assert empty.seconds_per_document is None


def test_the_report_is_a_markdown_table_with_every_headline_number() -> None:
    text = render(board())
    assert "| total_amount | 4 | 2 | 1 | 1 | 50% |" in text
    assert "| **All fields** | 8 | 4 | 3 | 1 | **50%** |" in text
    assert "seller_name, fuzzy" in text and "100%" in text
    assert "Catch rate" in text and "2 of 4" in text
    assert "25.0 s" in text


# --------------------------------------------------------------------------- #
# Wrapping a photo as a scanned page
# --------------------------------------------------------------------------- #
def _jpeg(width: int, height: int, *, orientation: int | None = None) -> bytes:
    import io

    from PIL import Image

    image = Image.new("RGB", (width, height), "white")
    image.paste((255, 0, 0), (0, 0, width // 6, height // 3))  # a red mark, stored top-left
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _page_size(pdf: bytes) -> tuple[float, float]:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        rect = doc[0].rect
        assert doc[0].get_text().strip() == "", "a scanned page has no text layer"
        return rect.width, rect.height


def test_a_photo_becomes_one_page_fitted_to_a4s_long_side() -> None:
    from scripts.coru_eval import image_to_pdf

    width, height = _page_size(image_to_pdf(_jpeg(300, 600)))
    assert height == pytest.approx(842.0) and width == pytest.approx(421.0)


def test_a_photo_stored_sideways_is_turned_upright() -> None:
    """Phone cameras store a portrait shot as landscape pixels plus an EXIF
    'rotate' flag (48 of the 100 sampled receipts). Every viewer honours the
    flag; a page that ignored it would show the model a sideways receipt."""
    from scripts.coru_eval import image_to_pdf

    upright = image_to_pdf(_jpeg(600, 300, orientation=6))
    width, height = _page_size(upright)
    assert height > width
    # Orientation 6 means "turn 90 degrees clockwise to view": the mark stored
    # top-left must be DRAWN top-right. A page of the right shape with the
    # picture letterboxed sideways inside it would pass the size check alone.
    assert _is_red(upright, 0.95, 0.03) and not _is_red(upright, 0.05, 0.03)

    flat = image_to_pdf(_jpeg(600, 300))
    width, height = _page_size(flat)
    assert width > height, "a photo with no flag is left as it is"
    assert _is_red(flat, 0.03, 0.05)


def _is_red(pdf: bytes, x: float, y: float) -> bool:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=36)
    red, green, _blue = pix.pixel(int(x * (pix.width - 1)), int(y * (pix.height - 1)))[:3]
    return bool(red > 200 and green < 80)
