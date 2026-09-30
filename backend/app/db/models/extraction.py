"""Annotations, extracted fields, and the correction log."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, created_at_col, org_fk, uuid_pk
from app.db.models.enums import ANNOTATION_STATUS, CORRECTION_ACTION


class Annotation(Base, OrgScopedMixin):
    """One extraction run over one document part."""

    __tablename__ = "annotations"
    __table_args__ = (
        # The queue view: "org's documents in status X, newest first".
        Index(
            "ix_annotations_org_status_created",
            "org_id",
            "status",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    # NOT NULL by design: every annotation belongs to exactly one part, even
    # when that part spans the whole document.
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_parts.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_schemas.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        ANNOTATION_STATUS, nullable=False, server_default=text("'importing'")
    )
    model_version: Mapped[str | None] = mapped_column(Text)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL")
    )
    automated: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    # Rule codes that prevented automation, so the UI can explain WHY a document
    # was not automated instead of just showing that it wasn't.
    blockers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class ExtractedField(Base, OrgScopedMixin):
    """One field value, with its provenance.

    ``source`` mirrors the ExtractedField schema in app/schemas/invoice.py:
    'ubl_xml' | 'vlm' | 'ocr_rule' | 'human' | 'computed'. A 'ubl_xml' value came out of the
    signed attachment and must never be overwritten by a model.

    NOTE for Phase 4: rows with ``value_extracted IS NULL`` are meaningful and
    must be written, not dropped. A model correctly returning null for a field
    that genuinely is not on the document is a negative training example, and a
    corpus of only positives cannot teach "this field is absent".
    """

    __tablename__ = "extracted_fields"
    __table_args__ = (
        UniqueConstraint("annotation_id", "field_key", "row_index"),
        # Partial index over only the rows a human changed. Drives the
        # correction-rate metric; the predicate keeps the index proportional to
        # the error rate rather than to the table.
        Index(
            "ix_extracted_fields_org_field_corrected",
            "org_id",
            "field_key",
            postgresql_where=text("value_final IS DISTINCT FROM value_extracted"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    annotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("annotations.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)
    value_extracted: Mapped[str | None] = mapped_column(Text)
    value_final: Mapped[str | None] = mapped_column(Text)
    value_normalized: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source: Mapped[str | None] = mapped_column(Text)
    validation_state: Mapped[str | None] = mapped_column(Text)
    # Normalized 0.0-1.0 floats, never pixels.
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class FieldCorrection(Base, OrgScopedMixin):
    """Append-only log of every human edit. The raw material for the data flywheel."""

    __tablename__ = "field_corrections"
    __table_args__ = (
        # "Which fields do reviewers keep fixing?" — the model-improvement backlog.
        Index(
            "ix_field_corrections_org_field_created",
            "org_id",
            "field_key",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = org_fk()
    annotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("annotations.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(CORRECTION_ACTION, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()


__all__ = ["Annotation", "ExtractedField", "FieldCorrection"]
