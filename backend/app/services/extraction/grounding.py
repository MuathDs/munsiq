"""Map extracted values back to a location on the page.

Two paths, and the difference matters:

* **Text-layer pages** — the PDF already told us exactly where every word sits.
  A value's box is assembled from the real word boxes it matched. Exact.
* **OCR pages** — boxes come from the OCR engine's own detection, so matching a
  value to them is inherently approximate and uses fuzzy comparison.

Either way, a value that cannot be located anywhere on the page is a
hallucination signal: the model produced text that is not on the document. Those
get ``bbox=None`` and are downgraded to ``review_suggested`` rather than being
quietly accepted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.config import get_settings
from app.services.normalize import normalize_for_match
from app.services.pagetext import PageText, Word

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Grounding:
    bbox: dict[str, float | int] | None
    score: float
    page_number: int | None

    @property
    def matched(self) -> bool:
        return self.bbox is not None


def _union(words: list[Word], page_number: int) -> dict[str, float | int]:
    return {
        "page": page_number,
        "x0": min(w.x0 for w in words),
        "y0": min(w.y0 for w in words),
        "x1": max(w.x1 for w in words),
        "y1": max(w.y1 for w in words),
    }


def ground_value(value: str, pages: list[PageText], *, threshold: int | None = None) -> Grounding:
    """Locate ``value`` on the document and return its bounding box.

    Tries increasing window sizes so a multi-word value ("Jubail Maintenance
    Services Ltd.") is matched as a unit rather than to a single stray word.
    """
    settings = get_settings()
    cutoff = settings.GROUNDING_THRESHOLD if threshold is None else threshold

    needle = normalize_for_match(value)
    if not needle:
        return Grounding(bbox=None, score=0.0, page_number=None)

    best_score = 0.0
    best_words: list[Word] | None = None
    best_page: int | None = None
    target_len = max(1, len(needle.split()))

    for page in pages:
        if not page.words:
            continue
        # Windows around the value's own word count: a value rarely spans more
        # than a couple of extra tokens once normalized.
        for size in range(1, min(target_len + 2, 8) + 1):
            for start in range(0, max(0, len(page.words) - size) + 1):
                window = page.words[start : start + size]
                candidate = normalize_for_match(page.join_words(window))
                if not candidate:
                    continue
                score = fuzz.ratio(needle, candidate)
                if score > best_score:
                    best_score = score
                    best_words = window
                    best_page = page.page_number
                    if score >= 100:
                        break
            if best_score >= 100:
                break
        if best_score >= 100:
            break

    if best_words is None or best_score < cutoff or best_page is None:
        logger.info("grounding.no_match", extra={"best_score": round(best_score, 1)})
        return Grounding(bbox=None, score=best_score, page_number=None)

    return Grounding(bbox=_union(best_words, best_page), score=best_score, page_number=best_page)
