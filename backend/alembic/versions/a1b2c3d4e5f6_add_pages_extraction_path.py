"""add pages.extraction_path

Revision ID: a1b2c3d4e5f6
Revises: c41d0a7be92f
Create Date: 2026-09-23 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "c41d0a7be92f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 'text' | 'vision' | NULL. NULL means Step Zero answered and the model
    # (therefore no per-page routing decision) was never called for this page.
    op.add_column("pages", sa.Column("extraction_path", sa.Text(), nullable=True))
    op.create_check_constraint(
        "pages_extraction_path_valid",
        "pages",
        "extraction_path IS NULL OR extraction_path IN ('text', 'vision')",
    )


def downgrade() -> None:
    op.drop_constraint("pages_extraction_path_valid", "pages", type_="check")
    op.drop_column("pages", "extraction_path")
