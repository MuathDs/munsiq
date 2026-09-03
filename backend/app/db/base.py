"""Declarative base, shared column types, and the async engine."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, MetaData, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

# Predictable constraint names, so Alembic autogenerate produces stable diffs
# instead of database-assigned names that churn between runs.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --------------------------------------------------------------------------- #
# Shared column factories
# --------------------------------------------------------------------------- #
def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary key generated server-side by pgcrypto."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def created_at_col() -> Mapped[datetime]:
    """TIMESTAMPTZ, stored UTC. Never a naive timestamp — see CLAUDE.md."""
    return mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


def org_fk(*, index: bool = True) -> Mapped[uuid.UUID]:
    """The tenant discriminator. Every org-scoped table carries exactly this."""
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=index,
    )


def jsonb(default: str = "'{}'") -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, nullable=False, server_default=text(default))


class OrgScopedMixin:
    """Marks a table as tenant-scoped.

    Presence of ``org_id`` is what the RLS migration keys off, and what
    tests/test_rls.py asserts against. Adding a table with an ``org_id`` that
    does not inherit this mixin is a bug the drift test is designed to catch.
    """

    @property
    def __org_scoped__(self) -> bool:
        return True


# --------------------------------------------------------------------------- #
# Engine / session factory
# --------------------------------------------------------------------------- #
def make_engine(url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        url or settings.async_database_url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        # Supabase sits behind a pooler; server-side statement caching across
        # pooled connections causes "prepared statement already exists" errors.
        connect_args={"statement_cache_size": 0},
    )


_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[SQLAlchemyAsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )
