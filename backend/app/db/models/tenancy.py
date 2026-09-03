"""Organizations, users, memberships."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, created_at_col, uuid_pk
from app.db.models.enums import MEMBER_ROLE


class Organization(Base):
    """A tenant.

    Deliberately NOT OrgScopedMixin: its own primary key is the tenant
    discriminator. The RLS policy on this table matches on ``id``, not
    ``org_id`` — see docs/db.md.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vat_number: Mapped[str | None] = mapped_column(Text)
    data_region: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ksa-dammam'"))
    retention_days: Mapped[int] = mapped_column(nullable=False, server_default=text("365"))
    created_at: Mapped[datetime] = created_at_col()


class User(Base):
    """A person. Global, not org-scoped — one user may belong to several orgs.

    Deliberately has no ``org_id`` and no RLS policy; membership is what binds a
    user to a tenant. Documented in docs/db.md.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ar-SA'"))
    created_at: Mapped[datetime] = created_at_col()


class Membership(Base, OrgScopedMixin):
    """Which user has which role in which org. Composite primary key."""

    __tablename__ = "memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(MEMBER_ROLE, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
