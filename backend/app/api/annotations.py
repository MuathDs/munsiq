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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_session

router = APIRouter(prefix="/annotations", tags=["annotations"])

CONFIRMABLE_FROM = ("to_review", "reviewing")


class AnnotationSummary(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    document_id: uuid.UUID
    status: str
    created_at: datetime


class Blocker(BaseModel):
    rule_code: str
    field_key: str | None = None
    message_ar: str
    message_en: str


class ConfirmResponse(BaseModel):
    annotation_id: uuid.UUID
    status: str


class BlockedResponse(BaseModel):
    detail: str
    blockers: list[Blocker] = Field(default_factory=list)


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


@router.post(
    "/{annotation_id}/confirm",
    summary="Confirm an annotation once no blocking findings remain",
    responses={409: {"model": BlockedResponse, "description": "Unresolved blocking findings"}},
)
async def confirm_annotation(
    annotation_id: uuid.UUID,
    session: AsyncSession = Depends(get_tenant_session),
) -> ConfirmResponse:
    """Transition an annotation to 'confirmed'.

    REFUSES while any blocking finding is unresolved. This is the point where
    deterministic validation stops being advisory: a document that does not add
    up, whose VAT number is malformed, or that carries a value appearing nowhere
    on the page cannot be signed off and pushed downstream.

    Blocking state is recomputed from validation_results rather than trusted
    from annotations.blockers, so fixing a field and re-running validation is
    what clears it — not editing the cached list.
    """
    row = (
        await session.execute(
            text("SELECT id, status FROM annotations WHERE id = :id"),
            {"id": annotation_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found.")

    if row.status == "confirmed":
        return ConfirmResponse(annotation_id=annotation_id, status="confirmed")

    if row.status not in CONFIRMABLE_FROM:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Annotation is '{row.status}'; only {' or '.join(CONFIRMABLE_FROM)} can be confirmed.",
        )

    unresolved = (
        await session.execute(
            text(
                "SELECT rule_code, field_key, message_ar, message_en "
                "FROM validation_results "
                "WHERE annotation_id = :id AND severity = 'error' AND passed = false "
                "ORDER BY rule_code"
            ),
            {"id": annotation_id},
        )
    ).all()

    if unresolved:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "detail": (
                    f"{len(unresolved)} blocking finding(s) must be resolved before "
                    f"this annotation can be confirmed."
                ),
                "blockers": [
                    {
                        "rule_code": r.rule_code,
                        "field_key": r.field_key,
                        "message_ar": r.message_ar,
                        "message_en": r.message_en,
                    }
                    for r in unresolved
                ],
            },
        )

    await session.execute(
        text("UPDATE annotations SET status = 'confirmed', confirmed_at = now() WHERE id = :id"),
        {"id": annotation_id},
    )
    return ConfirmResponse(annotation_id=annotation_id, status="confirmed")
