"""Producer-agnostic word segmentation.

The earlier fix (``_reading_order``) reordered whatever words MuPDF's own
``get_text("words")`` handed back. That tool turned out to be unreliable on its
own terms, independent of any one file:

* it can UNDER-segment — two words separated by a real inter-word gap, drawn
  without an explicit space glyph, come back as a single "word" (reproduced
  below with correctly-measured isolated-form Arabic glyphs and no artificial
  padding: ``get_text("words")`` returns exactly one word for three);
* on the real invoice that started this, it OVER-segmented — Arabic words came
  back as runs of single letters, split disproportionately after a letter that
  does not join forward (``NON_JOINING_LETTERS`` below).

Tuning a threshold to that one file would repeat the fine-tune's mistake this
project exists to fix. So this module builds words itself from raw glyph
positions (``page.get_text("rawdict")``), never from MuPDF's word tokenizer,
using a threshold that is always measured against the glyphs actually on the
page — never a fixed point size — plus a documented, Arabic-shaping-general
allowance (not a number fitted to that invoice) for the seam a script-unaware renderer
leaves after a non-joining letter.

Whether OUR OWN reading-order code (``_fuse_into_rows`` / ``_split_at_gaps``)
contributed to the over-fragmentation is checked directly: those functions may
only reorder words into rows and cut a fragment at a real column gap. They
never look inside a word, so they cannot turn one word into several letters —
``test_reading_order_never_changes_the_word_count`` pins that down.
"""

from __future__ import annotations

import io

import pymupdf
import pytest

from app.services.pagetext import (
    NON_JOINING_LETTERS,
    _RawChar,
    _reading_order,
    _segment_chars,
    extract_page_text,
)
from tests.fixtures import ARIAL, text_width

FONT = pymupdf.Font(fontfile=ARIAL)

# Isolated presentation forms for the letters of "شركة حلول نور" — what a
# renderer that never computes Arabic joining (a common, general failure mode,
# not specific to any one producer) draws for every letter regardless of
# position in the word.
_ISOLATED = {
    "ش": "ﻔ", "ر": "ﺮ", "ك": "ﻞ", "ة": "ﺔ",
    "ح": "ﺢ", "ل": "ﻞ", "و": "ﻮ", "ن": "ﻦ",
}  # fmt: skip


def _char(c: str, x0: float, x1: float, y0: float = 100.0, y1: float = 112.0) -> _RawChar:
    return _RawChar(c=c, x0=x0, y0=y0, x1=x1, y1=y1)


def _texts(groups: list[list[_RawChar]]) -> list[str]:
    return ["".join(c.c for c in g) for g in groups]


# --------------------------------------------------------------------------- #
# 1a. Explicit space glyphs are authoritative
# --------------------------------------------------------------------------- #
def test_an_explicit_space_splits_even_with_a_tiny_gap() -> None:
    """A gap that would NOT clear the relative threshold on its own still
    splits, because a real space character was there."""
    chars = [_char("a", 0, 5), _char(" ", 5, 5.2), _char("b", 5.2, 10.2)]

    assert _texts(_segment_chars(chars)) == ["a", "b"]


def test_a_non_breaking_space_counts_too() -> None:
    """PDF producers routinely emit U+00A0 for a plain space (observed even from
    this project's own PDF writer); it must split exactly like U+0020."""
    chars = [_char("a", 0, 5), _char("\xa0", 5, 5.2), _char("b", 5.2, 10.2)]

    assert _texts(_segment_chars(chars)) == ["a", "b"]


def test_no_gap_at_all_without_a_space_stays_one_word() -> None:
    chars = [_char("a", 0, 5), _char("b", 5, 10)]

    assert _texts(_segment_chars(chars)) == ["ab"]


# --------------------------------------------------------------------------- #
# 1b. Relative, not absolute: the SAME ratio at different font sizes agrees
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scale", [1.0, 4.0, 0.25])
def test_the_same_ratio_is_judged_the_same_at_any_font_size(scale: float) -> None:
    """8pt and 32pt text with proportionally identical spacing must segment
    identically. A fixed-point-size threshold could not do this at both ends."""
    glyph_width = 6.0 * scale
    inter_word_gap = 4.0 * scale  # a real space, well over half a glyph width
    kerning_gap = 0.05 * scale  # ordinary intra-word kerning

    chars = [
        _char("H", 0, glyph_width),
        _char("i", glyph_width + kerning_gap, 2 * glyph_width + kerning_gap),
        _char(
            "T",
            2 * glyph_width + kerning_gap + inter_word_gap,
            3 * glyph_width + kerning_gap + inter_word_gap,
        ),
    ]

    assert _texts(_segment_chars(chars)) == ["Hi", "T"]


def test_a_gap_too_small_to_be_a_word_break_at_any_scale() -> None:
    """The inverse: a gap that is a small FRACTION of the glyph width must never
    split, whether that glyph is 4pt or 400pt."""
    for glyph_width in (4.0, 40.0, 400.0):
        chars = [
            _char("a", 0, glyph_width),
            _char("b", glyph_width + 0.02 * glyph_width, 2 * glyph_width),
        ]
        assert _texts(_segment_chars(chars)) == ["ab"], glyph_width


# --------------------------------------------------------------------------- #
# 1c. Arabic-aware: a non-joining letter tolerates a bigger seam
# --------------------------------------------------------------------------- #
def test_a_seam_after_a_non_joining_letter_stays_in_the_word() -> None:
    """A renderer that shapes Arabic in separate connected-run pieces (general
    behaviour, not this one document) can leave a small positioning seam right
    where a non-joining letter ends a run. That seam must not read as a space."""
    glyph = 6.0
    for letter in NON_JOINING_LETTERS:
        seam = 0.7 * glyph  # bigger than ordinary kerning, smaller than a real space
        chars = [_char(letter, 0, glyph), _char("x", glyph + seam, glyph + seam + glyph)]
        assert _texts(_segment_chars(chars)) == [f"{letter}x"], letter


def test_a_seam_after_a_joining_letter_is_held_to_the_ordinary_threshold() -> None:
    """The allowance is specifically for non-joining letters. The same seam
    after an ordinary joining letter is a real break."""
    glyph = 6.0
    seam = 0.7 * glyph
    chars = [_char("م", 0, glyph), _char("x", glyph + seam, glyph + seam + glyph)]

    assert _texts(_segment_chars(chars)) == ["م", "x"]


def test_a_true_inter_word_gap_after_a_non_joining_letter_still_splits() -> None:
    """The allowance is bounded: a genuine word boundary right after a
    non-joining letter (a very common position — many words END in one) must
    still split."""
    glyph = 6.0
    real_gap = 2.0 * glyph  # comfortably a whole word-space, not a rendering seam
    chars = [_char("ر", 0, glyph), _char("x", glyph + real_gap, glyph + real_gap + glyph)]

    assert _texts(_segment_chars(chars)) == ["ر", "x"]


# --------------------------------------------------------------------------- #
# 1. MuPDF's own tokenizer, shown unreliable independent of any one file
# --------------------------------------------------------------------------- #
def _isolated_form_pdf(words: list[str]) -> bytes:
    """Three Arabic words, each letter its OWN isolated presentation form at its
    OWN correctly measured advance width (no artificial padding anywhere), one
    real inter-word space between words. This is what a renderer that skips
    Arabic shaping (uses isolated forms unconditionally) produces — a whole
    class of producer, not a specific one."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    right = 520.0
    for word in words:
        letters = [_ISOLATED.get(ch, ch) for ch in word]
        cursor = right
        positions = []
        for ch in letters:
            cursor -= FONT.text_length(ch, fontsize=12)
            positions.append((ch, cursor))
        right = cursor - text_width(" ")
        for ch, x in positions:
            page.insert_text((x, 120), ch, fontsize=12, fontfile=ARIAL, fontname="F0")
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return buffer.getvalue()


def test_mupdf_words_tool_merges_real_gaps_into_one_word() -> None:
    """Documents the failure this module works around — not a test of our code."""
    pdf = _isolated_form_pdf(["شركة", "حلول", "نور"])
    with pymupdf.open(stream=io.BytesIO(pdf), filetype="pdf") as doc:
        mupdf_words = doc[0].get_text("words")  # type: ignore[no-untyped-call]

    assert len(mupdf_words) == 1, "if this starts failing, MuPDF's tool improved"


def test_our_segmentation_finds_all_three_words() -> None:
    pdf = _isolated_form_pdf(["شركة", "حلول", "نور"])
    with pymupdf.open(stream=io.BytesIO(pdf), filetype="pdf") as doc:
        page_text = extract_page_text(doc[0], 1)

    assert len(page_text.words) == 3


# --------------------------------------------------------------------------- #
# Did our own reading-order code cause the fragmentation? No: it cannot split
# a word, only reorder and group already-built words into rows.
# --------------------------------------------------------------------------- #
def test_reading_order_never_changes_the_word_count() -> None:
    from app.services.pagetext import Word

    fragment = [
        Word(text=str(i), original=str(i), x0=0.1 * i, y0=0.1, x1=0.1 * i + 0.05, y1=0.12)
        for i in range(8)
    ]
    # Half look Arabic (by giving them an RTL codepoint in `original`) so the
    # row-fusion/column-split path — which only activates for Arabic — is
    # actually exercised, not skipped.
    arabic_fragment = [
        Word(text=w.text, original="م" + w.original, x0=w.x0, y0=w.y0, x1=w.x1, y1=w.y1)
        for w in fragment
    ]

    ordered = _reading_order([arabic_fragment], width=1000.0, height=1000.0)

    assert len(ordered) == len(arabic_fragment)
    assert {w.original for w in ordered} == {w.original for w in arabic_fragment}


# --------------------------------------------------------------------------- #
# Regression: the existing generated invoices are unaffected
# --------------------------------------------------------------------------- #
def test_plain_english_text_is_unaffected() -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (72, 120), "Invoice No: SA-2026-0334", fontsize=12, fontfile=ARIAL, fontname="F0"
    )
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()

    with pymupdf.open(stream=io.BytesIO(buffer.getvalue()), filetype="pdf") as reopened:
        page_text = extract_page_text(reopened[0], 1)

    assert page_text.text == "Invoice No: SA-2026-0334"
    # .original, not .text: Arial maps a drawn "-" onto the soft hyphen glyph
    # (docs/ingestion.md), which normalize_text folds back to "-" in .text.
    assert [w.text for w in page_text.words] == ["Invoice", "No:", "SA-2026-0334"]
