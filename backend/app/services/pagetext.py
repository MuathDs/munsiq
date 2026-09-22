"""Per-page text and word boxes: text layer first, OCR only as fallback.

WHY THIS ORDER. A digital PDF already contains the exact text and the exact
position of every word. Reading that layer is free, lossless, and works for
Arabic and Latin alike. OCR is a lossy reconstruction of information the file
already carries, so it is a fallback for image-only pages, never the default.

This has a direct consequence for grounding: when a page has a text layer, a
field's bounding box comes from the PDF itself and is exact. Fuzzy matching is
only ever needed for OCR pages. See docs/ingestion.md.

THE ARABIC GAP, MADE LOUD. The bundled RapidOCR recogniser is Chinese/English —
its character dictionary contains zero Arabic codepoints, so it cannot emit
Arabic at all. An image-only Arabic scan therefore has no working path today.
When that happens this module returns ``PageText`` with
``source="ocr_unsupported_script"`` and empty text rather than an empty string
that looks like a successful read. The pipeline turns that into a
validation_results row. Silent empty output is the failure mode being avoided.

READING ORDER. A text layer is a content stream, not a picture, and what comes
out of it is only as ordered as the producer wrote it. A producer that draws a
right-to-left line from its left end hands the extractor the Arabic words in
VISUAL order, and MuPDF puts each on a line of its own, so a printed
"شركة حلول نور" is extracted as "نور حلول شركة". The words are therefore regrouped
into rows by position and put back into logical order; see ``_reading_order``.
Second, a value wrapped after a hyphen must be rejoined WITHOUT a space; see
``join_words``. Both were found on the first real invoice (a marketplace B2C receipt).

WORD SEGMENTATION IS OURS, NOT MUPDF'S. ``get_text("words")`` is not reliable
across producers: it can under-segment (two words with a real gap and no space
glyph come back as one "word" — ``test_mupdf_words_tool_merges_real_gaps_into_
one_word`` reproduces this with nothing but correctly measured glyph widths, no
artificial padding) and, separately, it can over-segment Arabic disproportionately
after a letter that does not join forward. Neither is specific to one file, so
words are built from raw glyph positions (``page.get_text("rawdict")``) with a
threshold measured against the glyphs actually on that page — never a fixed
point size — plus a general allowance (not tuned to any one document) for the
seam a shaping-unaware renderer leaves after a non-joining letter. See
``_segment_chars``. The row-level code below (``_reading_order`` and friends)
only reorders and groups already-built words; it cannot split one, which
``test_reading_order_never_changes_the_word_count`` pins down.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, NamedTuple

import pymupdf

from app.config import get_settings
from app.services.normalize import (
    has_arabic,
    has_arabic_presentation_forms,
    normalize_text,
)
from app.services.ocr import OCRUnavailableError, get_ocr_engine

logger = logging.getLogger(__name__)


class TextSource(StrEnum):
    """How a page's text was obtained. Persisted on pages.text_source."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    OCR_UNSUPPORTED_SCRIPT = "ocr_unsupported_script"
    OCR_UNAVAILABLE = "ocr_unavailable"
    EMPTY = "empty"

    @property
    def is_degraded(self) -> bool:
        """True when the page did NOT yield usable text and the user must know."""
        return self in {
            TextSource.OCR_UNSUPPORTED_SCRIPT,
            TextSource.OCR_UNAVAILABLE,
            TextSource.EMPTY,
        }


@dataclass(frozen=True)
class Word:
    """One word with a normalized bounding box.

    ``text`` is normalized (NFKC-folded, ASCII numerals). ``original`` preserves
    exactly what was on the page, because a reviewer must be able to see what
    was printed rather than what we made of it.
    """

    text: str
    original: str
    x0: float
    y0: float
    x1: float
    y1: float

    def as_bbox(self, page_number: int) -> dict[str, float | int]:
        return {
            "page": page_number,
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
        }


@dataclass
class PageText:
    page_number: int
    source: TextSource
    text: str = ""
    words: list[Word] = field(default_factory=list)
    width_px: int = 0
    height_px: int = 0
    had_presentation_forms: bool = False
    note: str | None = None

    @property
    def is_degraded(self) -> bool:
        return self.source.is_degraded

    def join_words(self, words: Sequence[Word]) -> str:
        """The words as one string, rejoining a value that wrapped after a hyphen.

        Grounding compares a value with runs of consecutive words, so it has to
        see exactly what the reader of ``text`` saw.
        """
        return join_words(words, self.width_px, self.height_px, normalized=True)


_MIN_TEXT_LAYER_CHARS = 8
"""Below this, treat the "text layer" as an artefact (a stray header, a page
number stamped on a scan) rather than real content, and fall back to OCR."""


def extract_page_text(page: pymupdf.Page, page_number: int) -> PageText:
    """Read one page: text layer if it has one, OCR if it does not."""
    width, height = page.rect.width, page.rect.height
    words = _words_from_text_layer(page)
    raw = page.get_text().strip()  # type: ignore[no-untyped-call]

    if words and len(raw) >= _MIN_TEXT_LAYER_CHARS:
        return PageText(
            page_number=page_number,
            source=TextSource.TEXT_LAYER,
            # Built from the reordered words, not from ``raw``: raw is in stream
            # order, which is exactly what is wrong for a right-to-left line.
            text=normalize_text(
                join_words(words, width, height, normalized=False), fold_diacritics=False
            ),
            words=words,
            width_px=int(width),
            height_px=int(height),
            had_presentation_forms=has_arabic_presentation_forms(raw),
        )

    return _ocr_page(page, page_number, int(width), int(height))


def _words_from_text_layer(page: pymupdf.Page) -> list[Word]:
    """Words with boxes normalized to 0.0-1.0, never pixels, in READING order."""
    width, height = page.rect.width, page.rect.height
    if width <= 0 or height <= 0:
        return []

    raw = page.get_text("rawdict")  # type: ignore[no-untyped-call]
    fragments: dict[tuple[int, int], list[Word]] = {}
    for block_index, block in enumerate(raw.get("blocks", ())):
        if block.get("type") != 0:  # an image block; no text to read
            continue
        for line_index, line in enumerate(block.get("lines", ())):
            words = _words_from_line(line, width, height)
            if words:
                fragments[(block_index, line_index)] = words
    return _reading_order(list(fragments.values()), width, height)


def _words_from_line(line: dict[str, object], width: float, height: float) -> list[Word]:
    chars: list[_RawChar] = []
    for span in line.get("spans", ()):  # type: ignore[attr-defined]
        span_chars = span.get("chars")
        if span_chars:
            for c in span_chars:
                x0, y0, x1, y1 = c["bbox"]
                chars.append(_RawChar(c=c["c"], x0=x0, y0=y0, x1=x1, y1=y1))
        else:
            # No char-level detail (seen for some Type3/embedded fonts): fall
            # back to the span as a single unit rather than dropping it.
            text = span.get("text")
            bbox = span.get("bbox")
            if text and bbox:
                x0, y0, x1, y1 = bbox
                chars.append(_RawChar(c=text, x0=x0, y0=y0, x1=x1, y1=y1))
    chars.sort(key=lambda c: c.x0)

    words: list[Word] = []
    for spatial_group in _segment_chars(chars):
        # Grouped by physical (x-ascending) adjacency, which is backwards for a
        # right-to-left word: its first letter sits at the largest x. Put the
        # group's own characters back into logical (reading) order before
        # joining them — the row-level reordering below this function only
        # handles the order of WHOLE words, not the letters inside one.
        group = (
            list(reversed(spatial_group))
            if any(_is_rtl_letter(c.c) for c in spatial_group)
            else spatial_group
        )
        original = "".join(c.c for c in group)
        text = normalize_text(original)
        if not text:
            continue
        gx0 = min(c.x0 for c in group)
        gy0 = min(c.y0 for c in group)
        gx1 = max(c.x1 for c in group)
        gy1 = max(c.y1 for c in group)
        words.append(
            Word(
                text=text,
                original=original,
                x0=max(0.0, min(1.0, gx0 / width)),
                y0=max(0.0, min(1.0, gy0 / height)),
                x1=max(0.0, min(1.0, gx1 / width)),
                y1=max(0.0, min(1.0, gy1 / height)),
            )
        )
    return words


# --------------------------------------------------------------------------- #
# Word segmentation — glyph positions to words, relative thresholds only
# --------------------------------------------------------------------------- #
class _RawChar(NamedTuple):
    c: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0


NON_JOINING_LETTERS: Final = frozenset("اأإآدذرزو")
"""Arabic letters that never connect to the letter after them (the alef family,
دذ, ر ز, و). A word can legitimately have one anywhere inside it — most Arabic
words end in one — so the gap that follows gets a looser allowance below."""

_GAP_FACTOR: Final = 0.5
"""A gap this many times the average width of its two neighbouring glyphs is a
word break, when no explicit space character separates them. Relative to the
glyphs actually on the page, never a fixed point size, so it holds at 8pt and
at 80pt alike. Calibrated against a real inter-word gap (one space-character
width in 12pt Arial: ratio of roughly 0.55-0.8 against neighbouring glyph
widths) and against ordinary intra-word kerning (ratio of roughly 0)."""

_NONJOIN_GAP_FACTOR: Final = 1.1
"""The same test, loosened after a non-joining letter. A renderer that shapes
Arabic in separate connected-run pieces (a general failure mode: it can leave a
positioning seam exactly where a run ends, which is exactly after a non-joining
letter) must not have that seam read as a space. Bounded well under 2.0 — a
real word boundary, roughly a full glyph width or more, still splits."""


def _is_space_char(ch: str) -> bool:
    return ch.isspace()


def _local_scale(a: _RawChar, b: _RawChar) -> float:
    widths = [w for w in (a.width, b.width) if w > 0]
    return (sum(widths) / len(widths)) if widths else 1.0


def _segment_chars(chars: list[_RawChar]) -> list[list[_RawChar]]:
    """Group characters — already sorted by x — into words.

    1. An explicit space character always breaks, regardless of the gap either
       side of it (``_is_space_char``): a producer that bothered to draw a space
       said so, and that beats any geometric guess.
    2. Otherwise the gap since the previous glyph is compared with the average
       width of the two glyphs on either side of it — relative, never absolute.
    3. That comparison is looser right after a non-joining letter.
    """
    words: list[list[_RawChar]] = []
    current: list[_RawChar] = []
    previous: _RawChar | None = None
    for char in chars:
        if _is_space_char(char.c):
            if current:
                words.append(current)
            current = []
            previous = None
            continue
        if current and previous is not None:
            gap = char.x0 - previous.x1
            factor = _NONJOIN_GAP_FACTOR if previous.c in NON_JOINING_LETTERS else _GAP_FACTOR
            if gap > factor * _local_scale(previous, char):
                words.append(current)
                current = []
        current.append(char)
        previous = char
    if current:
        words.append(current)
    return words


# --------------------------------------------------------------------------- #
# Reading order
# --------------------------------------------------------------------------- #

_ROW_GAP_LINE_HEIGHTS: Final = 0.5
"""Two fragments are one row only if the space between them is at most this many
line heights. A word space is about a quarter of one; the padding between two
table cells is more than half (measured on the generated Arabic invoices, where
a looser value fused the "Quantity" and "Unit price" headers into one phrase)."""

_WRAP_GAP_LINE_HEIGHTS: Final = 1.0
"""A line wraps onto the next only if the next starts within this many line
heights of the bottom of the first. Anything further is a paragraph break."""


def _is_rtl_letter(ch: str) -> bool:
    return unicodedata.bidirectional(ch) in {"R", "AL"}


def _is_rtl_word(word: Word) -> bool:
    return any(_is_rtl_letter(ch) for ch in word.original)


def _is_latin_word(word: Word) -> bool:
    """A word carrying a letter that is NOT right-to-left. Digits alone do not count."""
    return any(ch.isalpha() and not _is_rtl_letter(ch) for ch in word.original)


def _reading_order(fragments: list[list[Word]], width: float, height: float) -> list[Word]:
    """Words in the order a person reads them.

    ``fragments`` are MuPDF's lines, in stream order. That is not good enough,
    for two reasons that both come from the stream being written in visual order:

    * MuPDF starts a new line for every word of a right-to-left run that the
      producer drew left to right, so one printed line arrives as several.
    * Even where it keeps them together, the stream order of an Arabic run is the
      reverse of the order it is read in.

    So fragments are first fused into rows by position (only where Arabic is
    involved, so an English page keeps MuPDF's lines exactly), and each row that
    contains Arabic is then put into logical order from the x coordinates alone.
    Sorting by position, rather than reversing whatever came out, is what keeps
    this correct for a producer that already wrote logical order.
    """
    stream = {id(w): n for n, w in enumerate(w for f in fragments for w in f)}
    rows = _fuse_into_rows(fragments, width, height)
    page_is_rtl = _page_is_rtl(rows)
    ordered: list[Word] = []
    for row in rows:
        has_arabic = any(map(_is_rtl_word, row))
        ordered.extend(_logical_order(row, page_is_rtl, stream) if has_arabic else row)
    return ordered


def _fuse_into_rows(fragments: list[list[Word]], width: float, height: float) -> list[list[Word]]:
    rows: list[list[Word]] = []
    for fragment in (seg for f in fragments for seg in _split_at_gaps(f, width, height)):
        if rows and _same_row(rows[-1], fragment, width, height):
            rows[-1].extend(fragment)
        else:
            rows.append(list(fragment))
    return rows


def _split_at_gaps(fragment: list[Word], width: float, height: float) -> list[list[Word]]:
    """Cut a fragment that contains Arabic wherever a table column separates it.

    MuPDF keeps consecutive words on one line however far apart they are, so a
    single fragment can span two columns. Segments come back in the order their
    first word appeared in the stream, so column order is the producer's.
    """
    if not any(map(_is_rtl_word, fragment)):
        return [fragment]
    line_height = max(w.y1 - w.y0 for w in fragment) * height
    by_position = sorted(enumerate(fragment), key=lambda item: (item[1].x0, item[1].x1))
    segments: list[list[tuple[int, Word]]] = [[by_position[0]]]
    reach = by_position[0][1].x1
    for item in by_position[1:]:
        if (item[1].x0 - reach) * width > _ROW_GAP_LINE_HEIGHTS * line_height:
            segments.append([])
        segments[-1].append(item)
        reach = max(reach, item[1].x1)
    segments.sort(key=lambda seg: min(index for index, _ in seg))
    return [[word for _, word in seg] for seg in segments]


def _same_row(row: list[Word], fragment: list[Word], width: float, height: float) -> bool:
    if not (any(map(_is_rtl_word, row)) or any(map(_is_rtl_word, fragment))):
        return False
    r_top, r_bottom = min(w.y0 for w in row), max(w.y1 for w in row)
    f_top, f_bottom = min(w.y0 for w in fragment), max(w.y1 for w in fragment)
    overlap = (min(r_bottom, f_bottom) - max(r_top, f_top)) * height
    line_height = min(r_bottom - r_top, f_bottom - f_top) * height
    if line_height <= 0 or overlap < 0.5 * line_height:
        return False
    r_left, r_right = min(w.x0 for w in row), max(w.x1 for w in row)
    f_left, f_right = min(w.x0 for w in fragment), max(w.x1 for w in fragment)
    gap = max(0.0, max(r_left, f_left) - min(r_right, f_right)) * width
    return gap <= _ROW_GAP_LINE_HEIGHTS * line_height


def _page_is_rtl(rows: Iterable[list[Word]]) -> bool:
    """Whether the page as a whole reads right to left.

    A mixed row is ambiguous on its own: "Seller:" at the left of an Arabic name
    is a label followed by its value on an English invoice, and a value followed
    by its label on an Arabic one. The pixels are identical. The rest of the page
    decides, by which script has more words on it.
    """
    words = [w for row in rows for w in row]
    return sum(map(_is_rtl_word, words)) > sum(map(_is_latin_word, words))


def _logical_order(row: list[Word], rtl: bool, stream: dict[int, int]) -> list[Word]:
    """One row in reading order.

    A word-level version of the Unicode bidirectional algorithm: consecutive
    words of one kind form a run, an Arabic run is read right to left, and in a
    right-to-left paragraph the runs themselves are read right to left.

    Only the Arabic runs and the order of the runs are taken from position. A
    left-to-right run (Latin words, numbers, a date) keeps the order the stream
    gave it: there is no evidence that order is wrong, and the generated Arabic
    invoices carry dates whose pieces MuPDF's own HTML engine lays out right to
    left, which a sort by x would turn into "09 - 04 - 2026".
    """
    visual = sorted(row, key=lambda w: (w.x0, w.x1))

    runs: list[tuple[bool, list[Word]]] = []
    for word, is_rtl in zip(visual, _kinds(visual), strict=True):
        if runs and runs[-1][0] == is_rtl:
            runs[-1][1].append(word)
        else:
            runs.append((is_rtl, [word]))

    ordered: list[Word] = []
    for is_rtl, run in reversed(runs) if rtl else runs:
        ordered.extend(reversed(run) if is_rtl else sorted(run, key=lambda w: stream[id(w)]))
    return ordered


def _kinds(visual: list[Word]) -> list[bool]:
    """True where a word belongs to a right-to-left run.

    A word with no letters (a number, a colon, a dash) takes the direction of the
    Arabic on both sides of it, because between two Arabic words it is part of
    that phrase; anywhere else it stays with the left-to-right side.
    """
    kinds = [_is_rtl_word(w) for w in visual]
    settled = list(kinds)
    for i, word in enumerate(visual):
        if kinds[i] or any(ch.isalpha() for ch in word.original):
            continue
        if 0 < i < len(visual) - 1 and kinds[i - 1] and kinds[i + 1]:
            settled[i] = True
    return settled


def _wraps(prev: Word, nxt: Word, width: float, height: float) -> bool:
    """Whether ``nxt`` continues ``prev`` after a line break inside one value.

    Deliberately narrow, because getting it wrong glues two fields together. The
    first must end in a hyphen that follows a letter or digit (a lone "-" is a
    separator and is left alone), the second must start with one and must not be
    a label ("Total:"), and it must sit directly below: a wrap, not a paragraph
    break.
    """
    if width <= 0 or height <= 0:
        return False
    if len(prev.text) < 2 or not prev.text.endswith("-") or not prev.text[-2].isalnum():
        return False
    if not nxt.text[0].isalnum() or nxt.text.endswith(":"):
        return False
    line_height = (prev.y1 - prev.y0) * height
    if line_height <= 0:
        return False
    below = (nxt.y0 - prev.y0) * height >= 0.5 * line_height
    close = (nxt.y0 - prev.y1) * height <= _WRAP_GAP_LINE_HEIGHTS * line_height
    return below and close


def join_words(words: Sequence[Word], width: float, height: float, *, normalized: bool) -> str:
    """Words as one string: a space between them, except where a value wrapped.

    ``normalized`` picks ``Word.text`` (NFKC, ASCII numerals: what grounding
    compares) or ``Word.original`` (what the page printed: what is stored).
    """
    parts: list[str] = []
    previous: Word | None = None
    for word in words:
        if previous is not None and not _wraps(previous, word, width, height):
            parts.append(" ")
        parts.append(word.text if normalized else word.original)
        previous = word
    return "".join(parts)


def _ocr_page(page: pymupdf.Page, page_number: int, width: int, height: int) -> PageText:
    """OCR fallback, with the Arabic limitation reported rather than hidden."""
    settings = get_settings()
    try:
        engine = get_ocr_engine(settings.OCR_ENGINE)
    except OCRUnavailableError as exc:
        logger.warning("ocr.unavailable", extra={"page": page_number, "error": str(exc)})
        return PageText(
            page_number=page_number,
            source=TextSource.OCR_UNAVAILABLE,
            width_px=width,
            height_px=height,
            note=str(exc),
        )

    pixmap = page.get_pixmap(dpi=settings.RASTER_DPI)
    image_bytes = pixmap.tobytes("png")  # type: ignore[no-untyped-call]
    result = engine.run(image_bytes)

    if not result.words:
        # Nothing recognised. Distinguish "the page is blank" from "the engine
        # cannot read this script" — the second is our known Arabic gap and a
        # reviewer must be told, not shown an empty field set.
        if not engine.supports_arabic:
            # Careful with the claim: OCR returned nothing, so we cannot know
            # what script the page holds. What we CAN state is that this engine
            # could not have read Arabic even if it were there. Say exactly
            # that, rather than asserting the page is Arabic or that it is blank.
            note = (
                f"No text layer, and OCR engine '{engine.name}' recognised nothing. "
                f"That engine cannot read Arabic (its recogniser contains no Arabic "
                f"characters), so an image-only Arabic page would produce this same "
                f"result as a blank one. This page could not be processed. Configure "
                f"an Arabic-capable OCR engine to tell these cases apart."
            )
            logger.warning("ocr.unsupported_script", extra={"page": page_number})
            return PageText(
                page_number=page_number,
                source=TextSource.OCR_UNSUPPORTED_SCRIPT,
                width_px=width,
                height_px=height,
                note=note,
            )
        return PageText(
            page_number=page_number,
            source=TextSource.EMPTY,
            width_px=width,
            height_px=height,
            note="No text layer and OCR recognised nothing on this page.",
        )

    text = normalize_text(" ".join(w.text for w in result.words), fold_diacritics=False)

    # The engine produced something, but if the document is Arabic and the
    # engine cannot do Arabic, what came back is Latin fragments at best.
    if not engine.supports_arabic and has_arabic(text):
        logger.warning("ocr.partial_script", extra={"page": page_number})

    return PageText(
        page_number=page_number,
        source=TextSource.OCR,
        text=text,
        words=result.words,
        width_px=width,
        height_px=height,
    )
