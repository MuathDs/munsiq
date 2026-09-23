"""Which pages get read as text and which as an image.

Reuses TEXT_LAYER_FRAGMENTED's own signature (many single-letter Arabic
tokens, none starting with the definite article) so the routing decision and
the reviewer-facing warning can never disagree about what "looks broken"
means — see test_validation_rules.py for the shared thresholds' own tests.
"""

from __future__ import annotations

from app.services.extraction.routing import (
    classify_pages,
    page_needs_vision,
    page_text_looks_fragmented,
    resolve_mode,
)
from app.services.pagetext import PageText, TextSource

CLEAN_ARABIC = (
    "ملخص المشتريات البائع شركة الأفق للتجارة الإلكترونية المشتري سلمان بن ناصر الحربي " * 3
)
SHATTERED_ARABIC = (
    "ملخص ا لمشتريا ت ا لبائع شركة ا لأفق للتجا رة "
    "ا لإلكترونيا ت ا لمشتر ي سلما ن بن نا صر ا لحر بي "
) * 3


def page(source: TextSource, text: str = "") -> PageText:
    return PageText(page_number=1, source=source, text=text)


# --------------------------------------------------------------------------- #
# page_text_looks_fragmented — the shared low-level signal
# --------------------------------------------------------------------------- #
def test_shattered_text_looks_fragmented() -> None:
    assert page_text_looks_fragmented(SHATTERED_ARABIC) is True


def test_ordinary_arabic_does_not_look_fragmented() -> None:
    assert page_text_looks_fragmented(CLEAN_ARABIC) is False


def test_too_little_arabic_to_judge_is_not_fragmented() -> None:
    assert page_text_looks_fragmented("Invoice SA-2026-0334 total 52118.00") is False


# --------------------------------------------------------------------------- #
# page_needs_vision — per page
# --------------------------------------------------------------------------- #
def test_a_clean_text_layer_page_does_not_need_vision() -> None:
    assert page_needs_vision(page(TextSource.TEXT_LAYER, CLEAN_ARABIC)) is False


def test_a_fragmented_text_layer_page_needs_vision() -> None:
    assert page_needs_vision(page(TextSource.TEXT_LAYER, SHATTERED_ARABIC)) is True


def test_a_page_with_no_text_layer_at_all_needs_vision() -> None:
    """is_degraded, not the fragmentation heuristic: nothing to fragment."""
    assert page_needs_vision(page(TextSource.OCR_UNSUPPORTED_SCRIPT, "")) is True
    assert page_needs_vision(page(TextSource.EMPTY, "")) is True
    assert page_needs_vision(page(TextSource.OCR_UNAVAILABLE, "")) is True


def test_a_plain_ocr_read_that_worked_does_not_need_vision() -> None:
    assert page_needs_vision(page(TextSource.OCR, "Invoice SA-2026-0334 total 52118.00")) is False


# --------------------------------------------------------------------------- #
# classify_pages / resolve_mode — the whole-document decision
# --------------------------------------------------------------------------- #
def test_classify_pages_names_only_the_bad_ones() -> None:
    pages = [
        PageText(page_number=1, source=TextSource.TEXT_LAYER, text=CLEAN_ARABIC),
        PageText(page_number=2, source=TextSource.OCR_UNSUPPORTED_SCRIPT, text=""),
        PageText(page_number=3, source=TextSource.TEXT_LAYER, text=CLEAN_ARABIC),
    ]
    assert classify_pages(pages) == frozenset({2})


def test_forced_text_mode_never_asks_for_vision_however_bad_the_page_is() -> None:
    pages = [PageText(page_number=1, source=TextSource.OCR_UNSUPPORTED_SCRIPT, text="")]
    mode, vision_pages = resolve_mode("text", pages)
    assert (mode, vision_pages) == ("text", frozenset())


def test_forced_vision_mode_sends_every_page_as_an_image() -> None:
    pages = [
        PageText(page_number=1, source=TextSource.TEXT_LAYER, text=CLEAN_ARABIC),
        PageText(page_number=2, source=TextSource.TEXT_LAYER, text=CLEAN_ARABIC),
    ]
    mode, vision_pages = resolve_mode("vision", pages)
    assert mode == "vision"
    assert vision_pages == frozenset({1, 2})


def test_auto_mode_stays_text_when_every_page_is_clean() -> None:
    pages = [PageText(page_number=1, source=TextSource.TEXT_LAYER, text=CLEAN_ARABIC)]
    assert resolve_mode("auto", pages) == ("text", frozenset())


def test_auto_mode_switches_to_vision_when_any_page_is_bad() -> None:
    """The real invoice's own shape: page 1 fine, page 2 unreadable. The WHOLE
    call must use the vision-capable model, since the text model cannot see
    images at all -- but only page 2 is recorded as having NEEDED vision."""
    pages = [
        PageText(page_number=1, source=TextSource.TEXT_LAYER, text="Invoice SA-2026-0334"),
        PageText(page_number=2, source=TextSource.OCR_UNSUPPORTED_SCRIPT, text=""),
    ]
    mode, vision_pages = resolve_mode("auto", pages)
    assert mode == "vision"
    assert vision_pages == frozenset({2})


def test_auto_mode_with_no_pages_stays_text() -> None:
    assert resolve_mode("auto", []) == ("text", frozenset())
