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
from app.services.extraction.prompts import (
    SUSPICIOUS_KEY,
    SYSTEM_PROMPT,
    FieldSpec,
    build_user_prompt,
)
from app.services.pagetext import PageText

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


def _document_text(pages: list[PageText]) -> str:
    chunks: list[str] = []
    for page in pages:
        if page.text:
            chunks.append(f"--- page {page.page_number} ---\n{page.text}")
    return "\n\n".join(chunks)


def run_extraction(
    *,
    client: InferenceClient,
    fields: list[FieldSpec],
    pages: list[PageText],
    ubl_values: dict[str, str] | None = None,
    page_images: list[bytes] | None = None,
) -> ExtractionResult:
    """Extract every requested field, honouring UBL precedence."""
    ubl_values = ubl_values or {}
    result = ExtractionResult()

    document_text = _document_text(pages)
    if not document_text.strip():
        # Nothing readable. Do not call the model on an empty document — it
        # would have nothing to work from and could only hallucinate.
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
            if model_value is not None and model_value.strip() != authoritative.strip():
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
            # A correct null. Persisted deliberately — see the module docstring.
            result.values.append(
                ExtractedValue(
                    field_key=spec.key,
                    value=None,
                    source="vlm",
                    confidence=1.0,
                    validation_state="auto_validated",
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
