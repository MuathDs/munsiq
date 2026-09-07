"""Annotation endpoints.

Minimal for now: enough of a real request path to prove tenant isolation holds
end to end through HTTP, not just at the session layer. The full annotation API
arrives with the review workspace.

Note what these handlers do NOT do: they never filter by org_id. There is no
``WHERE org_id = :org`` anywhere below. Scoping comes entirely from RLS, driven
by the GUC and the role that app/db/session.py sets on the transaction. If RLS
were switched off, these queries would return every tenant's rows — which is
exactly why tests/test_api_tenancy.py exercises them over HTTP.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_session

router = APIRouter(prefix="/annotations", tags=["annotations"])


class AnnotationSummary(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    document_id: uuid.UUID
    status: str
    created_at: datetime


@router.get("", summary="List annotations visible to the caller's tenant")
async def list_annotations(
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AnnotationSummary]:
    """Return this tenant's annotations, newest first.

    Deliberately unfiltered by org_id — see the module docstring.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, org_id, document_id, status, created_at "
                "FROM annotations ORDER BY created_at DESC LIMIT 100"
            )
        )
    ).all()
    return [
        AnnotationSummary(
            id=r.id,
            org_id=r.org_id,
            document_id=r.document_id,
            status=r.status,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/{annotation_id}", summary="Fetch one annotation by id")
async def get_annotation(
    annotation_id: uuid.UUID,
    session: AsyncSession = Depends(get_tenant_session),
) -> AnnotationSummary | None:
    """Fetch by primary key.

    Also deliberately unfiltered: knowing another tenant's UUID must not be
    enough to read it. RLS is what makes this safe.
    """
    row = (
        await session.execute(
            text(
                "SELECT id, org_id, document_id, status, created_at FROM annotations WHERE id = :id"
            ),
            {"id": annotation_id},
        )
    ).first()
    if row is None:
        return None
    return AnnotationSummary(
        id=row.id,
        org_id=row.org_id,
        document_id=row.document_id,
        status=row.status,
        created_at=row.created_at,
    )
