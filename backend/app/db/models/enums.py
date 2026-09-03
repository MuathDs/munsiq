"""Postgres enum types, declared once and reused across models.

``create_type=False`` everywhere: the enums are created explicitly at the top of
the initial migration, in one place, so Alembic never races two tables trying to
CREATE TYPE the same name.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import ENUM

MEMBER_ROLE = ENUM(
    "owner",
    "admin",
    "approver",
    "reviewer",
    "viewer",
    name="member_role",
    create_type=False,
)

AUTOMATION_LEVEL = ENUM(
    "never",
    "confident",
    "always",
    name="automation_level",
    create_type=False,
)

DOCUMENT_SOURCE = ENUM(
    "email",
    "api",
    "upload",
    "sftp",
    name="document_source",
    create_type=False,
)

ANNOTATION_STATUS = ENUM(
    "importing",
    "processing",
    "to_review",
    "reviewing",
    "confirmed",
    "approved",
    "exporting",
    "exported",
    "rejected",
    "failed",
    name="annotation_status",
    create_type=False,
)

CORRECTION_ACTION = ENUM(
    "edit",
    "delete",
    "add",
    "rebox",
    name="correction_action",
    create_type=False,
)

SEVERITY = ENUM("info", "warning", "error", name="severity", create_type=False)

APPROVAL_DECISION = ENUM(
    "pending",
    "approved",
    "rejected",
    name="approval_decision",
    create_type=False,
)

ALL_ENUMS = [
    MEMBER_ROLE,
    AUTOMATION_LEVEL,
    DOCUMENT_SOURCE,
    ANNOTATION_STATUS,
    CORRECTION_ACTION,
    SEVERITY,
    APPROVAL_DECISION,
]
