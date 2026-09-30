"""Extraction orchestration: prompt -> model -> ground -> field rows.

Two rules here are load-bearing and must not be "simplified" later.

**UBL values are authoritative.** Fields already populated from the signed UBL
attachment are never overwritten. The model is still asked for them — its answer
is kept for comparison and any disagreement becomes an XML_PDF_MISMATCH finding
— but a ``source='ubl_xml'`` value wins, always. It was read from a
cryptographically signed document; the model's was inferred.

**Correct nulls are persisted, not dropped.** When the model correctly returns
null for a field that genuinely is not on the document, that row is WRITTEN with
``value_extracted=NULL``. It is a negative example. A corpus of only positives
cannot teach a future fine-tune that a field can be absent — it can only learn a
fixed key set, which is the exact failure of the previous approach. This costs
one boolean decision now and is unrecoverable later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.extraction.client import InferenceClient, InferenceError
from app.services.extraction.grounding import ground_value
from app.services.extraction.labels import label_present
from app.services.extraction.prompts import (
    SUSPICIOUS_KEY,
    SYSTEM_PROMPT,
    FieldSpec,
    build_user_prompt,
)
from app.services.pagetext import PageText
from app.services.validation.engine import NUMERIC_TYPES, same_value

logger = logging.getLogger(__name__)


@dataclass
class ExtractedValue:
    """One field ready to be written to extracted_fields."""

    field_key: str
    value: str | None
    source: str
    confidence: float
    validation_state: str
    bbox: dict[str, float | int] | None = None
    original_value: str | None = None
    shadow_value: str | None = None
    """The model's answer for a field that UBL already owns. Kept for comparison,
    never promoted to the field's value."""
    row_index: int | None = None
    """None for a header field; the zero-based line number for a line-item cell."""


@dataclass
class ExtractionResult:
    values: list[ExtractedValue] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    mismatches: list[dict[str, str]] = field(default_factory=list)
    suspicious_content: str | None = None
    model_called: bool = False


def _document_text(pages: list[PageText], vision_page_numbers: frozenset[int] = frozenset()) -> str:
    """Text pages are inlined as before. A page routed to vision contributes no
    text here — its own text layer is exactly what was judged unreliable — and
    gets a marker instead, in the same ascending-page-number order the
    corresponding images are attached in (see pipeline.py), so the model can
    match each marker to the image that follows it."""
    chunks: list[str] = []
    for page in pages:
        if page.page_number in vision_page_numbers:
            chunks.append(
                f"--- page {page.page_number}: no reliable text layer; read this "
                "page from its attached image instead ---"
            )
        elif page.text:
            chunks.append(f"--- page {page.page_number} ---\n{page.text}")
    return "\n\n".join(chunks)


def run_extraction(
    *,
    client: InferenceClient,
    fields: list[FieldSpec],
    pages: list[PageText],
    ubl_values: dict[str, str] | None = None,
    page_images: list[bytes] | None = None,
    vision_page_numbers: frozenset[int] = frozenset(),
) -> ExtractionResult:
    """Extract every requested field, honouring UBL precedence.

    ``vision_page_numbers`` (from ``extraction.routing.resolve_mode``) says
    which pages' TEXT is unreliable — those are described by a marker instead
    of inlined, and must be covered by ``page_images`` instead. A page not in
    this set is inlined as text even when ``page_images`` is also given: mixed
    mode sends each page by whichever path suits it, not everything through
    the more expensive one.
    """
    ubl_values = ubl_values or {}
    result = ExtractionResult()

    document_text = _document_text(pages, vision_page_numbers)
    has_inline_text = any(
        page.text and page.page_number not in vision_page_numbers for page in pages
    )
    if not has_inline_text and not page_images:
        # Nothing readable and nothing to look at either. Do not call the model
        # on an empty document — it would have nothing to work from and could
        # only hallucinate.
        logger.warning("extraction.no_text", extra={"pages": len(pages)})
        for spec in fields:
            result.values.append(_from_ubl_or_null(spec, ubl_values))
        return result

    prompt = build_user_prompt(fields, document_text)
    try:
        chat = client.chat(system=SYSTEM_PROMPT, user=prompt, images=page_images)
        payload = chat.as_json()
    except InferenceError as exc:
        logger.error("extraction.failed", extra={"error": str(exc)})
        raise

    result.model = chat.model
    result.latency_ms = chat.latency_ms
    result.model_called = True

    suspicious = payload.get(SUSPICIOUS_KEY)
    if isinstance(suspicious, str) and suspicious.strip():
        # The model reported instruction-like text inside the document. Surface
        # it; do not act on it.
        result.suspicious_content = suspicious.strip()
        logger.warning("extraction.suspicious_content_reported")

    for spec in fields:
        raw = payload.get(spec.key)
        model_value = _coerce(raw)

        if spec.key in ubl_values:
            authoritative = ubl_values[spec.key]
            value = ExtractedValue(
                field_key=spec.key,
                value=authoritative,
                source="ubl_xml",
                confidence=1.0,
                validation_state="auto_validated",
                shadow_value=model_value,
            )
            numeric = spec.type.strip().lower() in NUMERIC_TYPES
            if model_value is not None and not same_value(
                model_value, authoritative, numeric=numeric
            ):
                result.mismatches.append(
                    {
                        "field_key": spec.key,
                        "ubl_value": authoritative,
                        "model_value": model_value,
                    }
                )
            result.values.append(value)
            continue

        if model_value is None:
            # Persisted deliberately either way — see the module docstring. But a
            # null is only CORRECT if the field is absent. If its label is printed
            # on the page the model missed it, and a miss that shows up green is
            # worse than a visible error.
            printed_as = label_present(spec.search_labels(), document_text)
            if printed_as is not None:
                logger.warning(
                    "extraction.silent_miss",
                    extra={"field_key": spec.key, "label": printed_as},
                )
            result.values.append(
                ExtractedValue(
                    field_key=spec.key,
                    value=None,
                    source="vlm",
                    confidence=0.0 if printed_as else 1.0,
                    validation_state="review_suggested" if printed_as else "auto_validated",
                )
            )
            continue

        grounding = ground_value(model_value, pages)
        result.values.append(
            ExtractedValue(
                field_key=spec.key,
                value=model_value,
                source="vlm",
                confidence=round(min(1.0, grounding.score / 100.0), 4),
                # A value that appears nowhere on the page is a hallucination
                # signal, so it is never auto-validated on the model's say-so.
                validation_state=(
                    "auto_validated"
                    if grounding.matched and grounding.score >= 99
                    else "review_suggested"
                ),
                bbox=grounding.bbox,
                original_value=model_value,
            )
        )

    return result


def _from_ubl_or_null(spec: FieldSpec, ubl_values: dict[str, str]) -> ExtractedValue:
    if spec.key in ubl_values:
        return ExtractedValue(
            field_key=spec.key,
            value=ubl_values[spec.key],
            source="ubl_xml",
            confidence=1.0,
            validation_state="auto_validated",
        )
    return ExtractedValue(
        field_key=spec.key,
        value=None,
        source="ocr_rule",
        confidence=0.0,
        validation_state="review_suggested",
    )


def _coerce(raw: Any) -> str | None:
    """Model output is untrusted: normalise its shape before trusting its type."""
    if raw is None:
        return None
    if isinstance(raw, str):
        stripped = raw.strip()
        # Models sometimes spell null as text.
        if not stripped or stripped.lower() in {"null", "none", "n/a", "na", "-"}:
            return None
        return stripped
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, int | float):
        return str(raw)
    if isinstance(raw, list | dict):
        logger.warning("extraction.unexpected_shape", extra={"type": type(raw).__name__})
        return None
    return str(raw)
