"""Request/response models for the document API."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    filename: str | None = None
    size_bytes: int
    status: str
    annotation_id: uuid.UUID | None = None
    duplicate: bool = Field(
        default=False,
        description=(
            "True when this exact file was already uploaded. The response is 200 and "
            "carries the EXISTING document; nothing was stored and no second "
            "pipeline run was started."
        ),
    )
    retried: bool = Field(
        default=False,
        description=(
            "True when the earlier attempt at this exact file had failed or stalled "
            "and processing was started again on the existing document."
        ),
    )


class UploadAuthorization(BaseModel):
    """A presigned upload: where the browser may POST a PDF, and for how long."""

    upload_url: str = Field(
        description="Path (with a signed token) the browser posts the PDF to, as "
        "multipart field `file`. Relative to the API origin."
    )
    expires_in: int
    max_bytes: int


class PageStatus(BaseModel):
    page_number: int
    text_source: str | None = Field(
        default=None,
        description=(
            "How this page's text was obtained: 'text_layer' (exact, from the PDF), "
            "'ocr', or a degraded value — 'ocr_unsupported_script' when the page is "
            "image-only and the OCR engine cannot read its script, "
            "'ocr_unavailable', or 'empty'. Degraded values mean NO usable text was "
            "extracted; they are reported rather than returned as empty success."
        ),
    )
    width_px: int | None = None
    height_px: int | None = None


class DocumentStatus(BaseModel):
    document_id: uuid.UUID
    status: str
    page_count: int | None = None
    has_embedded_ubl: bool = False
    model_version: str | None = None
    automated: bool = False
    annotation_id: uuid.UUID | None = None
    pages: list[PageStatus] = Field(default_factory=list)
    fields: dict[str, str | None] = Field(
        default_factory=dict,
        description="Extracted field values. A null value is a real result — the "
        "field is absent from the document — not a missing row.",
    )
    findings: list[str] = Field(
        default_factory=list,
        description="Validation rule codes raised during processing.",
    )
