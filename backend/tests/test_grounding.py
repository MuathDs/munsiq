"""Grounding extracted values to page coordinates."""

from __future__ import annotations

from app.services.extraction.grounding import ground_value
from app.services.pagetext import PageText, TextSource, Word


def _page(words: list[tuple[str, float, float, float, float]]) -> PageText:
    return PageText(
        page_number=1,
        source=TextSource.TEXT_LAYER,
        text=" ".join(w[0] for w in words),
        words=[Word(text=t, original=t, x0=x0, y0=y0, x1=x1, y1=y1) for t, x0, y0, x1, y1 in words],
    )


PAGE = _page(
    [
        ("Invoice", 0.10, 0.10, 0.20, 0.12),
        ("SA-2026-0334", 0.22, 0.10, 0.38, 0.12),
        ("Jubail", 0.10, 0.20, 0.18, 0.22),
        ("Maintenance", 0.19, 0.20, 0.34, 0.22),
        ("Services", 0.35, 0.20, 0.45, 0.22),
        ("45,320.00", 0.60, 0.30, 0.75, 0.32),
    ]
)


def test_single_word_value_is_located() -> None:
    result = ground_value("SA-2026-0334", [PAGE])
    assert result.matched
    assert result.score >= 99
    assert result.bbox is not None
    assert result.bbox["page"] == 1
    assert abs(float(result.bbox["x0"]) - 0.22) < 1e-6


def test_multi_word_value_spans_its_words() -> None:
    """The box must cover the whole phrase, not just its first token."""
    result = ground_value("Jubail Maintenance Services", [PAGE])
    assert result.matched
    assert result.bbox is not None
    assert abs(float(result.bbox["x0"]) - 0.10) < 1e-6
    assert abs(float(result.bbox["x1"]) - 0.45) < 1e-6


def test_value_absent_from_the_page_is_not_grounded() -> None:
    """A hallucination signal: the model produced text that is not on the page."""
    result = ground_value("Completely Different Supplier Ltd", [PAGE])
    assert not result.matched
    assert result.bbox is None


def test_arabic_indic_digits_still_match_ascii_amount() -> None:
    """The page says 45,320.00; the model returned Arabic-Indic digits."""
    result = ground_value("٤٥,٣٢٠.٠٠", [PAGE])
    assert result.matched
    assert result.bbox is not None
    assert abs(float(result.bbox["x0"]) - 0.60) < 1e-6


def test_empty_value_is_not_grounded() -> None:
    assert ground_value("", [PAGE]).matched is False
    assert ground_value("   ", [PAGE]).matched is False


def test_page_without_words_is_skipped_safely() -> None:
    blank = PageText(page_number=2, source=TextSource.OCR_UNSUPPORTED_SCRIPT)
    result = ground_value("SA-2026-0334", [blank, PAGE])
    assert result.matched
    assert result.bbox is not None
    assert result.bbox["page"] == 1


def test_bboxes_stay_normalized() -> None:
    result = ground_value("45,320.00", [PAGE])
    assert result.bbox is not None
    for key in ("x0", "y0", "x1", "y1"):
        assert 0.0 <= float(result.bbox[key]) <= 1.0
