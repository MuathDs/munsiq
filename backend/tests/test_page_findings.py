"""Page-level findings, as one pure function the pipeline and revalidation share.

These were computed only inside the pipeline, so revalidation — which replaces a
document's findings after every reviewer edit — could not recompute them and
simply dropped them, blocking ones included. They now come from the pages'
stored `text_source` alone, so both paths judge a page identically.
"""

from __future__ import annotations

from app.services.pagetext import TextSource
from app.services.validation.engine import FieldView, Severity, ValidationContext
from app.services.validation.page_findings import (
    PAGE_FINDING_CODES,
    PageState,
    missing_required,
    page_findings,
)

UNREADABLE = TextSource.OCR_UNSUPPORTED_SCRIPT


def test_readable_pages_produce_nothing() -> None:
    pages = [PageState(1, TextSource.TEXT_LAYER), PageState(2, TextSource.OCR)]
    assert page_findings(pages, missing_required=True) == []


def test_an_unreadable_page_blocks_when_nothing_else_is_readable() -> None:
    [finding] = page_findings([PageState(1, UNREADABLE)], missing_required=False)

    assert finding.code == "OCR_SCRIPT_UNSUPPORTED"
    assert finding.severity is Severity.ERROR
    assert finding.passed is False and finding.field_key is None


def test_an_unreadable_filler_page_next_to_a_readable_one_only_warns() -> None:
    pages = [PageState(1, TextSource.TEXT_LAYER), PageState(2, UNREADABLE)]

    [finding] = page_findings(pages, missing_required=False)

    assert finding.severity is Severity.WARNING


def test_it_blocks_again_when_a_required_field_is_missing() -> None:
    """The value that page was supposed to carry may never have arrived."""
    pages = [PageState(1, TextSource.TEXT_LAYER), PageState(2, UNREADABLE)]

    [finding] = page_findings(pages, missing_required=True)

    assert finding.severity is Severity.ERROR


def test_blank_and_engine_unavailable_pages_only_ever_warn() -> None:
    for source, code in (
        (TextSource.EMPTY, "PAGE_TEXT_EMPTY"),
        (TextSource.OCR_UNAVAILABLE, "OCR_ENGINE_UNAVAILABLE"),
    ):
        [finding] = page_findings([PageState(1, source)], missing_required=True)
        assert (finding.code, finding.severity) == (code, Severity.WARNING)


def test_messages_are_bilingual_and_name_the_page() -> None:
    [finding] = page_findings(
        [PageState(1, TextSource.TEXT_LAYER), PageState(2, UNREADABLE)], missing_required=False
    )
    assert "(page 2)" in finding.message_en
    assert "2" in finding.message_ar
    assert any("؀" <= ch <= "ۿ" for ch in finding.message_ar)


def test_a_runtime_note_is_used_when_the_pipeline_has_one() -> None:
    """Revalidation has only the stored source, so it falls back to a fixed
    message; the pipeline passes the OCR step's own, more specific note."""
    noted = PageState(1, UNREADABLE, note="Engine X saw nothing.")
    with_note = page_findings([noted], missing_required=False)
    without = page_findings([PageState(1, UNREADABLE)], missing_required=False)

    assert with_note[0].message_en.startswith("Engine X saw nothing.")
    assert without[0].message_en and "Engine X" not in without[0].message_en


def test_missing_required_uses_the_same_test_as_the_required_field_rule() -> None:
    """None, blank, or no row at all — exactly REQUIRED_FIELD_MISSING's view, so
    the page rule and that rule can never disagree about a field."""

    def ctx(**values: str | None) -> ValidationContext:
        return ValidationContext(
            fields={k: FieldView(key=k, value=v) for k, v in values.items()},
            required_keys=frozenset({"subtotal", "total_amount"}),
        )

    assert missing_required(ctx(subtotal="100.00", total_amount="115.00")) is False
    assert missing_required(ctx(subtotal=None, total_amount="115.00")) is True
    assert missing_required(ctx(subtotal="  ", total_amount="115.00")) is True
    assert missing_required(ctx(total_amount="115.00")) is True, "no row at all"
    assert missing_required(ValidationContext(fields={})) is False, "nothing required"


def test_the_code_set_covers_every_code_it_can_produce() -> None:
    produced = {
        f.code
        for source in TextSource
        for f in page_findings([PageState(1, source)], missing_required=True)
    }
    assert produced <= PAGE_FINDING_CODES
