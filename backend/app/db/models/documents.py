"""Documents, pages, and document parts."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, created_at_col, org_fk, uuid_pk
from app.db.models.enums import DOCUMENT_SOURCE


class Document(Base, OrgScopedMixin):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("org_id", "sha256"),
        Index("ix_documents_org_created", "org_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    queue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL")
    )
    storage_key: Mapped[str | None] = mapped_column(Text)
    # The name the uploader gave the file. Display only — storage keys are built
    # from UUIDs, never from this, because it is attacker-controlled text.
    filename: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    mime_type: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(DOCUMENT_SOURCE)

    # Set by ZATCA Step Zero, before any model runs.
    has_embedded_ubl: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    embedded_ubl_key: Mapped[str | None] = mapped_column(Text)

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()
    purge_after: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Page(Base, OrgScopedMixin):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_key: Mapped[str | None] = mapped_column(Text)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    # How this page's text was obtained: 'text_layer' | 'ocr' |
    # 'ocr_unsupported_script' | 'ocr_unavailable' | 'empty'.
    # The degraded values exist so a page that yielded NO usable text is
    # recorded as such instead of being indistinguishable from a blank page.
    text_source: Mapped[str | None] = mapped_column(Text)


class DocumentPart(Base, OrgScopedMixin):
    """A logical document inside a physical file.

    RATIONALE: a single emailed PDF frequently contains an invoice plus a
    delivery note plus a purchase order, so one document can yield several
    annotations. This table exists NOW even though nothing populates it yet —
    Phase 3 will insert exactly one part per document spanning all pages, and
    Phase 3.5 (out of scope for this build) would populate it properly.
    Retrofitting it once annotations exist means a data migration, not a
    feature. Two lines now, no migration later.
    """

    __tablename__ = "document_parts"
    __table_args__ = (UniqueConstraint("document_id", "part_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    part_index: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_type: Mapped[str | None] = mapped_column(Text)
    doc_type_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    classifier_source: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_col()
