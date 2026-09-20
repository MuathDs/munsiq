"""add documents.filename

The upload endpoint has always returned the file's name and never stored it. The
dashboard's History needs it: a document that is still processing, or that
failed, has no invoice number yet, and "no name at all" is not a usable row.

Nullable, because every document uploaded before this migration has none and
seeded documents are inserted without one. A column-level ADD keeps the table's
RLS policy and grants exactly as they were.

Revision ID: c41d0a7be92f
Revises: 75484fbb7214
Create Date: 2026-09-20 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c41d0a7be92f"
down_revision: str | None = "75484fbb7214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("filename", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "filename")
