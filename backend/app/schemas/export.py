"""MunsiqInvoiceV1 — the one export contract.

Every export format is a rendering of THIS model. JSON is the model serialized;
CSV and XLSX are built by flattening the same instance (app/services/export.py),
never by querying the database separately. So the three formats cannot drift:
a field present in one is present in all, with the same provenance.

``schema_version`` is a literal, not a free string. A consumer can pin to it, and
a v2 contract is a new model with a new literal rather than a silent change to
this one.

Money and every other value stay strings, exactly as extracted or corrected.
"45320.00" is never round-tripped through a float; typed parsing is the
consumer's decision, informed by ``type``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal["munsiq.invoice.v1"] = "munsiq.invoice.v1"

ExportFormat = Literal["json", "xlsx", "csv"]


class ExportBBox(BaseModel):
    """Normalized 0.0-1.0 page coordinates, never pixels."""

    model_config = ConfigDict(frozen=True)

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class ExportField(BaseModel):
    """One value and everything needed to judge it."""

    key: str
    label_en: str = ""
    label_ar: str = ""
    type: str = "string"
    value: str | None = Field(description="The confirmed value: the reviewer's if corrected.")
    source: str | None = Field(
        description="'ubl_xml' (signed attachment) | 'vlm' (model) | 'ocr_rule' | 'human'."
    )
    confidence: Decimal | None = None
    bbox: ExportBBox | None = None
    reviewed_by: uuid.UUID | None = Field(
        default=None,
        description=(
            "The user who last corrected this field, else the user who confirmed "
            "the document. Null until authentication records user identities."
        ),
    )
    original_value: str | None = Field(
        default=None,
        description="What the pipeline produced, before any human correction.",
    )


class ExportLineItem(BaseModel):
    row_index: int
    fields: list[ExportField]


class MunsiqInvoiceV1(BaseModel):
    schema_version: Literal["munsiq.invoice.v1"] = SCHEMA_VERSION
    annotation_id: uuid.UUID
    document_id: uuid.UUID
    status: Literal["confirmed"]
    confirmed_at: datetime | None
    confirmed_by: uuid.UUID | None
    exported_at: datetime
    model_version: str | None = Field(
        description="The model that extracted the values; null when none was called."
    )
    has_embedded_ubl: bool
    invoice: list[ExportField] = Field(description="Header fields, in schema order.")
    line_items: list[ExportLineItem] = Field(default_factory=list)
