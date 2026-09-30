"""add extracted_fields.model_value

Revision ID: b7c1e2d3f4a5
Revises: a1b2c3d4e5f6
Create Date: 2026-09-30 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c1e2d3f4a5"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # What the model read for a field that signed XML or the ZATCA QR owns.
    # Without it, revalidation cannot recompute XML_PDF_MISMATCH or
    # QR_MODEL_MISMATCH and those findings vanished on the first edit.
    op.add_column("extracted_fields", sa.Column("model_value", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("extracted_fields", "model_value")
