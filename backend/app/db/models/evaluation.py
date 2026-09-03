"""Evaluation sets and ground truth.

RATIONALE: this is the held-out test set. Without it there is no way to tell
whether a prompt change or a model swap improved or regressed anything — you get
opinions instead of measurements. The tables exist from the start because
labelling effort accumulates over time and cannot be reconstructed later.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, created_at_col, org_fk, uuid_pk


class EvalSet(Base, OrgScopedMixin):
    __tablename__ = "eval_sets"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Once frozen, the set is immutable — otherwise "the benchmark improved"
    # can mean "the benchmark changed".
    frozen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class GroundTruthField(Base, OrgScopedMixin):
    __tablename__ = "ground_truth_fields"
    __table_args__ = (
        UniqueConstraint("eval_set_id", "document_id", "field_key", "row_index"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    eval_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)
    expected_value: Mapped[str | None] = mapped_column(Text)
    expected_bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()
