"""Queues, extraction schemas, vendors."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, created_at_col, jsonb, org_fk, uuid_pk
from app.db.models.enums import AUTOMATION_LEVEL


class Queue(Base, OrgScopedMixin):
    __tablename__ = "queues"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    automation_level: Mapped[str] = mapped_column(
        AUTOMATION_LEVEL, nullable=False, server_default=text("'confident'")
    )
    # No FK to extraction_schemas: that table references queues, and a hard FK
    # both ways would make the initial insert order circular.
    active_schema_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at_col()


class ExtractionSchema(Base, OrgScopedMixin):
    """A versioned field definition. Schemas are INPUT to the model, never baked in.

    ``definition`` holds field keys, types, label_ar, label_en, a required flag, a
    per-field confidence_threshold, and a natural-language guideline string.
    Editing a schema creates a new version rather than mutating a row, so any
    annotation can always be replayed against the schema that produced it.
    """

    __tablename__ = "extraction_schemas"
    __table_args__ = (UniqueConstraint("queue_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    queue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queues.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = jsonb()
    created_at: Mapped[datetime] = created_at_col()


class Vendor(Base, OrgScopedMixin):
    """A supplier, keyed by TRN within a tenant.

    ``known_values`` accumulates values previously confirmed for this vendor and
    feeds one of the three confidence sources in Phase 4.
    """

    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("org_id", "trn"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    trn: Mapped[str | None] = mapped_column(Text)
    name_ar: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    known_values: Mapped[dict[str, Any]] = jsonb()
    created_at: Mapped[datetime] = created_at_col()
