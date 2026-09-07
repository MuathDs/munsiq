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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

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
            text=normalize_text(raw, fold_diacritics=False),
            words=words,
            width_px=int(width),
            height_px=int(height),
            had_presentation_forms=has_arabic_presentation_forms(raw),
        )

    return _ocr_page(page, page_number, int(width), int(height))


def _words_from_text_layer(page: pymupdf.Page) -> list[Word]:
    """Words with boxes normalized to 0.0-1.0, never pixels."""
    width, height = page.rect.width, page.rect.height
    if width <= 0 or height <= 0:
        return []

    words: list[Word] = []
    for x0, y0, x1, y1, raw, *_ in page.get_text("words"):  # type: ignore[no-untyped-call]
        text = normalize_text(raw)
        if not text:
            continue
        words.append(
            Word(
                text=text,
                original=raw,
                x0=max(0.0, min(1.0, x0 / width)),
                y0=max(0.0, min(1.0, y0 / height)),
                x1=max(0.0, min(1.0, x1 / width)),
                y1=max(0.0, min(1.0, y1 / height)),
            )
        )
    return words


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
