"""Response and request models for the validation workspace.

One shape, one round trip. The workspace needs fields, their provenance, their
boxes, the page images and every validation finding to render its first frame —
so ``AnnotationDetail`` carries all of it. A reviewer must never have to wait on
a second request to learn *why* a document is blocked.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

FieldSource = Literal["ubl_xml", "vlm", "ocr_rule", "human"]
CorrectionAction = Literal["edit", "delete", "add", "rebox"]


class BBox(BaseModel):
    """Normalized 0.0-1.0, never pixels.

    The document overlay is an SVG with viewBox="0 0 1 1", so these drop
    straight in with no arithmetic on the client.
    """

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class ExtractedFieldOut(BaseModel):
    field_key: str
    row_index: int | None = None
    value_extracted: str | None = None
    value_final: str | None = None
    confidence: Decimal | None = None
    source: FieldSource | None = Field(
        default=None,
        description=(
            "Drives the provenance badge. 'ubl_xml' is read from the supplier's "
            "signed attachment and is authoritative; 'vlm' is a model reading and "
            "is advisory; 'human' is a reviewer correction."
        ),
    )
    validation_state: str | None = Field(
        default=None,
        description="'blocking' | 'review_suggested' | 'auto_validated'.",
    )
    bbox: BBox | None = None

    @property
    def value(self) -> str | None:
        return self.value_final if self.value_final is not None else self.value_extracted


class ValidationFinding(BaseModel):
    rule_code: str
    severity: Literal["info", "warning", "error"]
    passed: bool
    message_ar: str | None = None
    message_en: str | None = None
    field_key: str | None = None


class PageOut(BaseModel):
    page_number: int
    text_source: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    image_url: str | None = Field(
        default=None,
        description=(
            "Short-lived signed URL. Authorization travels in the signature, which "
            "covers the tenant, so a leaked URL cannot be replayed across tenants."
        ),
    )


class AnnotationDetail(BaseModel):
    annotation_id: uuid.UUID
    document_id: uuid.UUID
    status: str
    model_version: str | None = None
    automated: bool = False
    created_at: datetime
    confirmed_at: datetime | None = None

    has_embedded_ubl: bool = False
    page_count: int | None = None

    blockers: list[str] = Field(
        default_factory=list,
        description="Rule codes preventing confirmation. Explains why a document "
        "was not automated.",
    )
    fields: list[ExtractedFieldOut] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)
    pages: list[PageOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Corrections
# --------------------------------------------------------------------------- #
class CorrectionEvent(BaseModel):
    """One reviewer edit.

    The workspace sends a BATCH of these, not the whole annotation: the event
    log is the payload, so two reviewers touching different fields cannot
    silently overwrite each other's work with a stale snapshot.
    """

    field_key: str
    row_index: int | None = None
    new_value: str | None = None
    action: CorrectionAction = "edit"


class CorrectionBatch(BaseModel):
    events: list[CorrectionEvent] = Field(min_length=1, max_length=200)


class CorrectionResult(BaseModel):
    annotation_id: uuid.UUID
    applied: int
    blockers: list[str] = Field(
        default_factory=list,
        description="Recomputed after applying the batch. Correcting the field "
        "that caused a blocker is what clears it.",
    )
    fields: list[ExtractedFieldOut] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)


def bbox_from_json(raw: Any) -> BBox | None:
    if not isinstance(raw, dict):
        return None
    try:
        return BBox(
            page=int(raw["page"]),
            x0=float(raw["x0"]),
            y0=float(raw["y0"]),
            x1=float(raw["x1"]),
            y1=float(raw["y1"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
