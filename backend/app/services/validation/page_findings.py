"""Page-level findings: a page that yielded no usable text.

Not a registry rule — it judges pages, not fields — but deterministic like one,
and shared by the pipeline and revalidation so both judge a page identically.
It needs only each page's stored `text_source` and whether a required field is
missing. Before this lived here, only the pipeline could compute it, so every
revalidation (every reviewer edit) deleted these findings, blocking ones
included, and a document blocked by an unreadable page became confirmable after
an unrelated correction.

When it blocks: an unreadable-script page blocks only if nothing in the
document is readable, or a required field is still missing — a plausible sign
the value that page carried never arrived. A blank filler page next to a
readable invoice only warns, and so do blank or engine-unavailable pages.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.services.pagetext import TextSource
from app.services.validation.engine import RuleResult, Severity, ValidationContext

_CODE_FOR_SOURCE: Final[dict[TextSource, str]] = {
    TextSource.OCR_UNSUPPORTED_SCRIPT: "OCR_SCRIPT_UNSUPPORTED",
    TextSource.OCR_UNAVAILABLE: "OCR_ENGINE_UNAVAILABLE",
    TextSource.EMPTY: "PAGE_TEXT_EMPTY",
}
_FALLBACK_CODE: Final = "PAGE_TEXT_UNAVAILABLE"

PAGE_FINDING_CODES: Final[frozenset[str]] = frozenset({*_CODE_FOR_SOURCE.values(), _FALLBACK_CODE})
"""Every code this module can write — revalidation deletes and recomputes these."""

_AR_MESSAGE: Final[dict[TextSource, str]] = {
    TextSource.OCR_UNSUPPORTED_SCRIPT: (
        "الصفحة {page}: لا تحتوي على طبقة نصية، ولم يتعرّف المحرك على أي نص. "
        "محرك التعرّف الضوئي الحالي لا يدعم اللغة العربية، لذلك لا يمكن تمييز "
        "الصفحة العربية الممسوحة ضوئياً عن الصفحة الفارغة."
    ),
    TextSource.OCR_UNAVAILABLE: "الصفحة {page}: محرك التعرّف الضوئي غير متاح.",
    TextSource.EMPTY: "الصفحة {page}: لم يُعثر على أي نص.",
}
_AR_FALLBACK: Final = "تعذّر استخراج نص هذه الصفحة."

# Used when there is no runtime note — revalidation has only the stored source.
_EN_MESSAGE: Final[dict[TextSource, str]] = {
    TextSource.OCR_UNSUPPORTED_SCRIPT: (
        "No text layer, and OCR recognised nothing. The configured OCR engine cannot "
        "read Arabic, so an image-only Arabic page produces this same result as a "
        "blank one. This page could not be processed."
    ),
    TextSource.OCR_UNAVAILABLE: "No text layer, and the OCR engine was unavailable.",
    TextSource.EMPTY: "No text layer and OCR recognised nothing on this page.",
}
_EN_FALLBACK: Final = "No text could be extracted from this page."


@dataclass(frozen=True)
class PageState:
    page_number: int
    source: TextSource
    note: str | None = None
    """The OCR step's own explanation, when the pipeline has one."""


def page_findings(pages: Sequence[PageState], *, missing_required: bool) -> list[RuleResult]:
    """One failed finding per degraded page; nothing for a readable one."""
    any_usable_page = any(not page.source.is_degraded for page in pages)
    findings: list[RuleResult] = []
    for page in pages:
        if not page.source.is_degraded:
            continue
        blocking = page.source is TextSource.OCR_UNSUPPORTED_SCRIPT and (
            not any_usable_page or missing_required
        )
        english = page.note or _EN_MESSAGE.get(page.source, _EN_FALLBACK)
        findings.append(
            RuleResult(
                code=_CODE_FOR_SOURCE.get(page.source, _FALLBACK_CODE),
                severity=Severity.ERROR if blocking else Severity.WARNING,
                passed=False,
                message_ar=_AR_MESSAGE.get(page.source, _AR_FALLBACK).format(
                    page=page.page_number
                ),
                message_en=f"{english} (page {page.page_number})",
                field_key=None,
            )
        )
    return findings


def missing_required(ctx: ValidationContext) -> bool:
    """A required header field with no non-blank value — REQUIRED_FIELD_MISSING's
    own test, so the page rule and that rule never disagree."""
    return any(not (ctx.value(key) or "").strip() for key in ctx.required_keys)
