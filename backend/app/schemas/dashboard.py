"""Response models for the dashboard: the document list, stats, templates.

Everything here is a read model. Nothing is invented: a field that cannot be
computed is None, and the frontend hides what is None rather than showing a
placeholder number.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.workspace import SchemaFieldOut


class DocumentListItem(BaseModel):
    """One uploaded document, whatever stage it is at."""

    document_id: uuid.UUID
    annotation_id: uuid.UUID | None = Field(
        default=None,
        description="Null until the pipeline finishes (or fails) — there is nothing to open yet.",
    )
    filename: str | None = Field(
        default=None, description="As uploaded. Null for documents that predate the column."
    )
    created_at: datetime
    state: str = Field(
        description=(
            "'processing' (no annotation yet), 'stalled' (no annotation and past "
            "STALLED_AFTER_S — the process probably died), or the latest annotation's "
            "status: 'to_review', 'reviewing', 'confirmed', 'failed', ..."
        )
    )
    has_embedded_ubl: bool = False
    model_version: str | None = Field(
        default=None, description="Null when Step Zero answered and no model was called."
    )
    page_count: int | None = None
    invoice_number: str | None = None
    seller_name: str | None = None
    total_amount: str | None = Field(
        default=None, description="Exactly as extracted or corrected. Never a float."
    )
    currency: str | None = None
    blocking_count: int = Field(
        default=0, description="Unresolved error-severity findings. Above zero blocks confirmation."
    )
    error_en: str | None = None
    error_ar: str | None = None


class AccuracyStats(BaseModel):
    """Share of fields no human had to correct.

    Computed ONLY over annotations a reviewer has confirmed, because "nobody
    corrected it" means nothing until somebody has actually reviewed it. Counting
    a field in a document still waiting for review as "correct" would inflate the
    figure with values nobody has checked.
    """

    annotations: int
    fields_total: int = Field(
        description="Fields that carried a value or were corrected. A field correctly "
        "absent on both sides makes no claim and is not counted."
    )
    fields_corrected: int


class Stats(BaseModel):
    documents_total: int
    processed: int = Field(
        description="Reached review or beyond: not processing, failed or stalled."
    )
    in_progress: int
    awaiting_review: int
    blocked: int = Field(description="Awaiting review with at least one unresolved error.")
    confirmed: int
    failed: int = Field(description="Failed plus stalled.")
    from_signed_xml: int = Field(
        description="Processed documents answered by Step Zero — no model was called."
    )
    accuracy: AccuracyStats | None = Field(
        default=None,
        description="Null until at least one confirmed annotation exists: not computable, "
        "so hidden.",
    )


class TemplateOut(BaseModel):
    """An extraction schema. Read-only: editing one is a database row edit today."""

    id: uuid.UUID
    version: int
    name: str | None = None
    queue_id: uuid.UUID | None = None
    queue_name: str | None = None
    in_use: bool = Field(
        description="The highest version for its queue — the one the pipeline reads for "
        "new documents."
    )
    created_at: datetime
    fields: list[SchemaFieldOut] = Field(
        description="Header fields then line-item fields, in schema order; "
        "`line_item` marks the repeating group."
    )


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    vat_number: str | None = None
    data_region: str | None = None


class SystemInfo(BaseModel):
    """Non-secret runtime configuration, for the read-only settings page."""

    environment: str
    inference_model: str
    extraction_use_vision: bool
    ocr_engine: str
    max_upload_bytes: int
    grounding_threshold: int
    stalled_after_s: int
