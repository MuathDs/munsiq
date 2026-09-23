"""Which pages get read as text and which as an image.

WHY PER PAGE. A schema-conditioned text prompt is cheap, exact (word boxes
come straight from the PDF) and works well — right up until the text layer is
unreadable (an image-only scan) or looks cut apart (the reading-order bug this
project found and fixed once already; a producer that emits one is not
guaranteed never to emit another). Routing those specific pages to a vision
model, while leaving pages that are already fine on the cheap, exact text
path, is the ZATCA-invoice equivalent of "read the XML when it is there, use
the model only when it is not": don't call an expensive, approximate path for
a page that a cheap, exact one already answers correctly.

THE SIGNAL IS SHARED, ON PURPOSE. "Fragmented" here is exactly what
TEXT_LAYER_FRAGMENTED warns the reviewer about (rules/provenance.py) — many
single-letter Arabic tokens, none beginning with the definite article. Using
the same threshold in both places means the routing decision and the warning
a reviewer sees can never quietly disagree about what "looks broken" means.

A MIXED DOCUMENT STILL MAKES ONE MODEL CALL. The text model cannot see images
at all, so the moment ANY page needs vision, the whole call goes through the
vision-capable model — but pages that were already fine keep contributing
their TEXT to that same prompt rather than being re-read as an image too; see
``app/services/extraction/runner.py``. What is recorded per page is which
INPUT that page actually contributed, not which model answered.
"""

from __future__ import annotations

from typing import Final, Literal

from app.services.normalize import has_arabic
from app.services.pagetext import PageText

MIN_ARABIC_TOKENS_TO_JUDGE: Final = 20
"""Fewer than this and a few short words would decide the verdict. Matches
rules/provenance.py's TEXT_LAYER_FRAGMENTED exactly — see its docstring."""

SHATTERED_SINGLE_LETTER_SHARE: Final = 0.25
ARTICLE_SHARE_OF_REAL_TEXT: Final = 0.05

ExtractionMode = Literal["text", "vision", "auto"]
Path = Literal["text", "vision"]


def fragmentation_ratios(text: str) -> tuple[float, float] | None:
    """(single-letter share, definite-article share) of this text's Arabic
    tokens, or None when there are too few to judge. The TEXT_LAYER_FRAGMENTED
    validation rule uses this directly so its message quotes the same numbers
    routing decided on, not a second, independently-computed pair."""
    tokens = [t for t in text.split() if has_arabic(t)]
    if len(tokens) < MIN_ARABIC_TOKENS_TO_JUDGE:
        return None
    single = sum(1 for t in tokens if len(t) == 1) / len(tokens)
    article = sum(1 for t in tokens if t.startswith("ال")) / len(tokens)
    return single, article


def page_text_looks_fragmented(text: str) -> bool:
    """The TEXT_LAYER_FRAGMENTED signature, as a plain predicate over a string
    rather than a ValidationContext, so routing can ask it before any field has
    been extracted."""
    ratios = fragmentation_ratios(text)
    if ratios is None:
        return False
    single, article = ratios
    return single >= SHATTERED_SINGLE_LETTER_SHARE and article < ARTICLE_SHARE_OF_REAL_TEXT


def page_needs_vision(page: PageText) -> bool:
    """Whether THIS page's text is unreliable enough to read the image instead.

    Either of two independent signs is enough: no usable text at all
    (``page.is_degraded`` — no text layer, OCR unsupported/unavailable/empty),
    or a text layer that exists but looks cut apart.
    """
    return page.is_degraded or page_text_looks_fragmented(page.text)


def classify_pages(pages: list[PageText]) -> frozenset[int]:
    """Page numbers whose text is unreliable enough to read as an image."""
    return frozenset(p.page_number for p in pages if page_needs_vision(p))


def resolve_mode(
    configured_mode: ExtractionMode, pages: list[PageText]
) -> tuple[Path, frozenset[int]]:
    """Turn EXTRACTION_MODE and this document's pages into an actual decision.

    Returns ``(path, vision_pages)``: ``path`` is the document-level label
    ("text" or "vision") used for benchmarking and for ``pages.extraction_path``
    on pages that were not individually degraded; ``vision_pages`` is exactly
    which page numbers should be sent as images.

    * "text"   — every page as text, however bad. The forced baseline.
    * "vision" — every page as an image, however good the text is. The forced
      comparison arm.
    * "auto"   — per page, by ``classify_pages``. Labelled "vision" overall the
      moment any page needed it, because that is what decides which model the
      one call to make uses; pages that stayed on text are still recorded as
      "text" individually (see the pipeline's per-page persistence).
    """
    if configured_mode == "text":
        return "text", frozenset()
    if configured_mode == "vision":
        return "vision", frozenset(p.page_number for p in pages)
    vision_pages = classify_pages(pages)
    return ("vision" if vision_pages else "text"), vision_pages
