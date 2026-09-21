"""A silent miss is worse than a visible error.

When the model returns null for a field whose LABEL is printed on the page, the
field used to be recorded as a correct null: state ``auto_validated``, confidence
1.0, green in the workspace. On the first real invoice the buyer's name was printed
and came back null, and nothing told the reviewer to look.

The labels come from the schema (``label_ar``, ``label_en`` and ``synonyms``), not
from code, and are matched with the whitespace removed: on that invoice the text
layer had split the Arabic words apart (a space after the alef of the definite
article, for one), so a match on the words as written would have missed the very
label that was there.
"""

from __future__ import annotations

import json

import pytest

from app.services.extraction.client import ChatResult
from app.services.extraction.labels import label_present
from app.services.extraction.prompts import FieldSpec
from app.services.extraction.runner import run_extraction
from app.services.pagetext import PageText, TextSource

BUYER = FieldSpec(
    key="buyer_name",
    label_en="Buyer name",
    label_ar="اسم المشتري",
    synonyms=("Buyer", "Customer", "المشتري", "العميل"),
)


class Replay:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def chat(self, *, system, user, images=None, json_mode=True):  # type: ignore[no-untyped-def]
        return ChatResult(content=json.dumps(self.payload), model="m", latency_ms=1)


def page(text: str) -> PageText:
    return PageText(page_number=1, source=TextSource.TEXT_LAYER, text=text)


def buyer_after(text: str, answer: str | None) -> tuple[str | None, str, float]:
    result = run_extraction(
        client=Replay({"buyer_name": answer}), fields=[BUYER], pages=[page(text)]
    )
    value = result.values[0]
    return value.value, value.validation_state, value.confidence


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #
def test_a_null_next_to_a_printed_label_is_flagged() -> None:
    value, state, confidence = buyer_after("المشتري: سلمان الحربي  الإجمالي 230.00", None)

    assert value is None
    assert state == "review_suggested"
    assert confidence == 0.0


def test_a_synonym_counts_as_the_label() -> None:
    assert buyer_after("Customer: Salman  Total 230.00", None)[1] == "review_suggested"


def test_a_null_with_no_label_anywhere_is_still_a_correct_null() -> None:
    """The point of persisting nulls: absence is information. Do not flag it."""
    assert buyer_after("Invoice SA-2026-0334 total 52118.00", None) == (None, "auto_validated", 1.0)


def test_a_label_split_by_the_text_layer_is_still_found() -> None:
    """The shattered form the first real invoice produced."""
    assert buyer_after("ا لمشتر ي: سلما ن ا لحر بي", None)[1] == "review_suggested"


def test_the_plural_in_a_title_is_not_the_label() -> None:
    """ "ملخص المشتريات" (purchase summary) contains the letters of "المشتري"."""
    assert buyer_after("ملخص المشتريات رقم الطلب 88", None) == (None, "auto_validated", 1.0)


def test_a_value_that_was_returned_is_left_alone() -> None:
    value, state, _ = buyer_after("المشتري: سلمان الحربي", "سلمان الحربي")

    assert value == "سلمان الحربي"
    assert state != "blocking"


def test_a_signed_value_is_never_touched() -> None:
    result = run_extraction(
        client=Replay({"buyer_name": None}),
        fields=[BUYER],
        pages=[page("المشتري: x")],
        ubl_values={"buyer_name": "Signed Buyer"},
    )

    assert result.values[0].source == "ubl_xml"
    assert result.values[0].validation_state == "auto_validated"


# --------------------------------------------------------------------------- #
# The matcher on its own
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("المشتري: x", "المشتري"),
        ("ا لمشتر ي", "المشتري"),
        ("BUYER: x", "Buyer"),
        ("nothing relevant", None),
        ("المشتريات", None),
        ("المشترين", None),
    ],
)
def test_label_present(text: str, expected: str | None) -> None:
    assert label_present(("Buyer", "المشتري"), text) == expected


def test_a_label_too_short_to_be_safe_is_ignored() -> None:
    """ "PO" matches half the alphabet once spaces are gone."""
    assert label_present(("PO",), "a p o and a top") is None
