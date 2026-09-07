"""All ORM models, imported so Alembic autogenerate sees a complete metadata."""

from __future__ import annotations

from app.db.base import Base
from app.db.models.config import ExtractionSchema, Queue, Vendor
from app.db.models.documents import Document, DocumentPart, Page
from app.db.models.evaluation import EvalSet, GroundTruthField
from app.db.models.extraction import Annotation, ExtractedField, FieldCorrection
from app.db.models.ops import AuditLog, Export, ValidationResult
from app.db.models.tenancy import Membership, Organization, User
from app.db.models.workflow import Approval, WorkflowStep

__all__ = [
    "Annotation",
    "Approval",
    "AuditLog",
    "Base",
    "Document",
    "DocumentPart",
    "EvalSet",
    "Export",
    "ExtractedField",
    "ExtractionSchema",
    "FieldCorrection",
    "GroundTruthField",
    "Membership",
    "Organization",
    "Page",
    "Queue",
    "User",
    "ValidationResult",
    "Vendor",
    "WorkflowStep",
]


def org_scoped_tables() -> list[str]:
    """Every table carrying an ``org_id`` column.

    Single source of truth for the RLS migration and the RLS drift test, so the
    two cannot disagree. A new org-scoped model is picked up automatically.
    """
    return sorted(name for name, table in Base.metadata.tables.items() if "org_id" in table.c)
