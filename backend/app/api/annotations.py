"""Annotation endpoints — the API behind the validation workspace.

Note what these handlers do NOT do: they never filter by org_id. There is no
``WHERE org_id = :org`` anywhere below. Scoping comes entirely from RLS, driven
by the GUC and the role that app/db/session.py sets on the transaction. If RLS
were switched off, these queries would return every tenant's rows — which is
exactly why tests/test_api_tenancy.py exercises them over HTTP.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_tenant_session
from app.schemas.workspace import (
    AnnotationDetail,
    CorrectionBatch,
    CorrectionResult,
    ExtractedFieldOut,
    PageOut,
    ValidationFinding,
    bbox_from_json,
    schema_fields_from_definition,
)
from app.services.revalidate import revalidate_annotation
from app.services.signed_urls import page_image_path, sign_page_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/annotations", tags=["annotations"])

CONFIRMABLE_FROM = ("to_review", "reviewing")
EDITABLE_STATUSES = ("to_review", "reviewing")

FIELD_COLUMNS = (
    "SELECT field_key, row_index, value_extracted, value_final, confidence, "
    "source, validation_state, bbox FROM extracted_fields "
    "WHERE annotation_id = :id ORDER BY field_key, row_index NULLS FIRST"
)


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


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
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


@router.get(
    "/{annotation_id}",
    summary="Everything the validation workspace needs, in one round trip",
)
async def get_annotation(
    annotation_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> AnnotationDetail:
    """Fields, provenance, boxes, findings, blockers and signed page URLs.

    Deliberately one call. The workspace cannot render its first frame without
    all of it, and a reviewer must never wait on a second request to learn WHY a
    document is blocked.

    Also deliberately unfiltered by org_id: knowing another tenant's UUID must
    not be enough to read it. RLS is what makes this safe.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.id, a.document_id, a.status, a.model_version, a.automated, "
                "a.created_at, a.confirmed_at, a.blockers, "
                "d.has_embedded_ubl, d.page_count "
                "FROM annotations a JOIN documents d ON d.id = a.document_id "
                "WHERE a.id = :id"
            ),
            {"id": annotation_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found.")

    field_rows = (await session.execute(text(FIELD_COLUMNS), {"id": annotation_id})).all()

    finding_rows = (
        await session.execute(
            text(
                "SELECT rule_code, severity, passed, message_ar, message_en, field_key "
                "FROM validation_results WHERE annotation_id = :id "
                "ORDER BY passed, rule_code"
            ),
            {"id": annotation_id},
        )
    ).all()

    page_rows = (
        await session.execute(
            text(
                "SELECT page_number, text_source, width_px, height_px, image_key "
                "FROM pages WHERE document_id = :d ORDER BY page_number"
            ),
            {"d": row.document_id},
        )
    ).all()

    # Labels and order come from the queue's extraction schema at request time,
    # so the workspace shows "Invoice number" / "رقم الفاتورة" instead of a raw
    # key — and the frontend hardcodes neither the labels nor the field list.
    definition = await session.scalar(
        text(
            "SELECT e.definition FROM annotations a "
            "JOIN extraction_schemas e ON e.id = a.schema_id WHERE a.id = :id"
        ),
        {"id": annotation_id},
    )
    schema_fields = schema_fields_from_definition(definition)
    # A missing label is a schema-authoring gap. The UI falls back to a
    # humanised key rather than the identifier, but say so here so the gap gets
    # fixed in the schema instead of living on as "Seller vat number".
    for spec in schema_fields:
        missing = [lang for lang in ("label_ar", "label_en") if not getattr(spec, lang)]
        if missing:
            logger.warning("extraction schema field %r has no %s", spec.key, " or ".join(missing))

    return AnnotationDetail(
        annotation_id=row.id,
        schema_fields=schema_fields,
        document_id=row.document_id,
        status=row.status,
        model_version=row.model_version,
        automated=bool(row.automated),
        created_at=row.created_at,
        confirmed_at=row.confirmed_at,
        has_embedded_ubl=bool(row.has_embedded_ubl),
        page_count=row.page_count,
        blockers=list(row.blockers or []),
        fields=[_field_out(r) for r in field_rows],
        findings=[_finding_out(r) for r in finding_rows],
        pages=[_page_out(r, org_id, row.document_id) for r in page_rows],
    )


def _field_out(row: Any) -> ExtractedFieldOut:
    return ExtractedFieldOut(
        field_key=row.field_key,
        row_index=row.row_index,
        value_extracted=row.value_extracted,
        value_final=row.value_final,
        confidence=row.confidence,
        source=row.source,
        validation_state=row.validation_state,
        bbox=bbox_from_json(row.bbox),
    )


def _finding_out(row: Any) -> ValidationFinding:
    return ValidationFinding(
        rule_code=row.rule_code,
        severity=row.severity,
        passed=bool(row.passed),
        message_ar=row.message_ar,
        message_en=row.message_en,
        field_key=row.field_key,
    )


def _page_out(row: Any, org_id: uuid.UUID, document_id: uuid.UUID) -> PageOut:
    image_url = None
    if row.image_key:
        image_url = page_image_path(sign_page_token(org_id, document_id, row.page_number))
    return PageOut(
        page_number=row.page_number,
        text_source=row.text_source,
        width_px=row.width_px,
        height_px=row.height_px,
        image_url=image_url,
    )


# --------------------------------------------------------------------------- #
# Corrections
# --------------------------------------------------------------------------- #
@router.patch(
    "/{annotation_id}/fields",
    summary="Apply a batch of reviewer corrections and revalidate",
)
async def patch_fields(
    annotation_id: uuid.UUID,
    batch: CorrectionBatch,
    org_id: uuid.UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> CorrectionResult:
    """Apply reviewer edits, log them, then re-run every validation rule.

    The payload is a batch of EVENTS, not the whole annotation. Sending a full
    snapshot would let one reviewer's stale copy silently revert another's work.

    Revalidation is not optional here. The confirm endpoint recomputes blockers
    from validation_results, so without re-running the rules a reviewer could
    correct the very value that caused a blocker and still be refused forever.
    """
    row = (
        await session.execute(
            text("SELECT id, status FROM annotations WHERE id = :id"), {"id": annotation_id}
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found.")
    if row.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Annotation is '{row.status}' and can no longer be edited.",
        )

    applied = 0
    for event in batch.events:
        existing = (
            await session.execute(
                text(
                    "SELECT value_extracted, value_final FROM extracted_fields "
                    "WHERE annotation_id = :a AND field_key = :k "
                    "AND row_index IS NOT DISTINCT FROM :r"
                ),
                {"a": annotation_id, "k": event.field_key, "r": event.row_index},
            )
        ).first()
        if existing is None:
            # Unknown field: reject rather than invent a row. A typo in a field
            # key should surface, not silently create data.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Unknown field '{event.field_key}' on this annotation.",
            )

        old_value = (
            existing.value_final if existing.value_final is not None else existing.value_extracted
        )
        new_value = None if event.action == "delete" else event.new_value

        await session.execute(
            text(
                "UPDATE extracted_fields SET value_final = :v, source = 'human' "
                "WHERE annotation_id = :a AND field_key = :k "
                "AND row_index IS NOT DISTINCT FROM :r"
            ),
            {"v": new_value, "a": annotation_id, "k": event.field_key, "r": event.row_index},
        )
        # Append-only log: raw material for correction-rate metrics and for any
        # future fine-tune.
        await session.execute(
            text(
                "INSERT INTO field_corrections (org_id, annotation_id, field_key, "
                "row_index, old_value, new_value, action) "
                "VALUES (:org, :a, :k, :r, :old, :new, :act)"
            ),
            {
                "org": org_id,
                "a": annotation_id,
                "k": event.field_key,
                "r": event.row_index,
                "old": old_value,
                "new": new_value,
                "act": event.action,
            },
        )
        applied += 1

    report = await revalidate_annotation(session, org_id, annotation_id)
    field_rows = (await session.execute(text(FIELD_COLUMNS), {"id": annotation_id})).all()

    return CorrectionResult(
        annotation_id=annotation_id,
        applied=applied,
        blockers=report.blockers,
        fields=[_field_out(r) for r in field_rows],
        findings=[
            ValidationFinding(
                rule_code=r.code,
                severity=r.severity.value,
                passed=r.passed,
                message_ar=r.message_ar,
                message_en=r.message_en,
                field_key=r.field_key,
            )
            for r in report.results
        ],
    )


# --------------------------------------------------------------------------- #
# Confirm
# --------------------------------------------------------------------------- #
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
