"""Read endpoints behind the dashboard: documents, stats, templates, org, system.

Like every read in this API, none of these filters by org_id. RLS scopes them,
which is why tests/test_dashboard_api.py checks them from a second tenant too.

Nothing here is estimated. Where a number cannot be computed it is null, and the
frontend hides the card rather than showing a placeholder.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_current_org_id, get_tenant_session
from app.config import Settings
from app.schemas.dashboard import (
    AccuracyStats,
    DocumentListItem,
    OrgOut,
    Stats,
    SystemInfo,
    TemplateOut,
)
from app.schemas.workspace import schema_fields_from_definition

router = APIRouter(tags=["dashboard"])

# What a document's state resolves to: the latest annotation's status, or
# 'processing' / 'stalled' when there is no annotation yet. One definition, used
# by the list and by the stats, so a document is never counted differently in
# the two places.
_STATE_CTE = """
WITH latest AS (
    SELECT d.id, d.filename, d.created_at, d.has_embedded_ubl, d.page_count,
           a.id AS annotation_id, a.status::text AS astatus, a.model_version
    FROM documents d
    LEFT JOIN LATERAL (
        SELECT id, status, model_version FROM annotations
        WHERE document_id = d.id ORDER BY created_at DESC LIMIT 1
    ) a ON true
),
state AS (
    SELECT l.*,
           CASE WHEN l.annotation_id IS NOT NULL THEN l.astatus
                WHEN l.created_at < now() - make_interval(secs => CAST(:stall AS double precision))
                    THEN 'stalled'
                ELSE 'processing' END AS st
    FROM latest l
)
"""

_HEADER_KEYS = ("invoice_number", "seller_name", "total_amount", "currency")
# One aggregate per header field, generated so the four lines cannot drift apart.
_HEADER_VALUES = ", ".join(
    f"max(COALESCE(value_final, value_extracted)) FILTER (WHERE field_key = '{key}') AS {key}"
    for key in _HEADER_KEYS
)

_PROCESSED = "('to_review','reviewing','confirmed','approved','exporting','exported','rejected')"


@router.get("/documents", summary="Every uploaded document, newest first, with its state")
async def list_documents(
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_tenant_session),
    settings: Settings = Depends(get_app_settings),
) -> list[DocumentListItem]:
    """The dashboard's History. One row per document — including those still
    processing or failed, which have no annotation to list."""
    rows = (
        await session.execute(
            text(
                _STATE_CTE
                + f"""
                SELECT s.id AS document_id, s.annotation_id, s.filename, s.created_at,
                       s.st AS state, s.has_embedded_ubl, s.model_version, s.page_count,
                       f.invoice_number, f.seller_name, f.total_amount, f.currency,
                       COALESCE(v.blocking, 0) AS blocking_count,
                       v.error_en, v.error_ar
                FROM state s
                LEFT JOIN LATERAL (
                    SELECT {_HEADER_VALUES}
                    FROM extracted_fields
                    WHERE annotation_id = s.annotation_id AND row_index IS NULL
                ) f ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) FILTER (
                               WHERE severity = 'error' AND passed = false) AS blocking,
                           max(message_en) FILTER (
                               WHERE rule_code = 'PIPELINE_FAILED') AS error_en,
                           max(message_ar) FILTER (
                               WHERE rule_code = 'PIPELINE_FAILED') AS error_ar
                    FROM validation_results WHERE annotation_id = s.annotation_id
                ) v ON true
                ORDER BY s.created_at DESC
                LIMIT :limit
                """
            ),
            {"stall": float(settings.STALLED_AFTER_S), "limit": limit},
        )
    ).all()
    return [
        DocumentListItem(
            document_id=r.document_id,
            annotation_id=r.annotation_id,
            filename=r.filename,
            created_at=r.created_at,
            state=r.state,
            has_embedded_ubl=bool(r.has_embedded_ubl),
            model_version=r.model_version,
            page_count=r.page_count,
            invoice_number=r.invoice_number,
            seller_name=r.seller_name,
            total_amount=r.total_amount,
            currency=r.currency,
            blocking_count=int(r.blocking_count or 0),
            error_en=r.error_en,
            error_ar=r.error_ar,
        )
        for r in rows
    ]


@router.get("/stats", summary="Dashboard counts, computed from the data")
async def get_stats(
    session: AsyncSession = Depends(get_tenant_session),
    settings: Settings = Depends(get_app_settings),
) -> Stats:
    """Counts and the accuracy figure. Every value is derived; none is estimated."""
    counts = (
        await session.execute(
            text(
                _STATE_CTE
                + f"""
                , with_blockers AS (
                    SELECT s.*,
                           (SELECT count(*) FROM validation_results v
                            WHERE v.annotation_id = s.annotation_id
                              AND v.severity = 'error' AND v.passed = false) AS blocking
                    FROM state s
                )
                SELECT count(*) AS documents_total,
                       count(*) FILTER (WHERE st IN {_PROCESSED}) AS processed,
                       count(*) FILTER (WHERE st = 'processing') AS in_progress,
                       count(*) FILTER (WHERE st IN ('to_review','reviewing')) AS awaiting_review,
                       count(*) FILTER (WHERE st IN ('to_review','reviewing')
                                          AND blocking > 0) AS blocked,
                       count(*) FILTER (WHERE st IN ('confirmed','approved','exporting','exported'))
                           AS confirmed,
                       count(*) FILTER (WHERE st IN ('failed','stalled')) AS failed,
                       count(*) FILTER (WHERE st IN {_PROCESSED}
                                          AND has_embedded_ubl AND model_version IS NULL)
                           AS from_signed_xml
                FROM with_blockers
                """
            ),
            {"stall": float(settings.STALLED_AFTER_S)},
        )
    ).one()

    # A field is CORRECTED when its effective value differs from what was
    # extracted, or when a reviewer deleted it. value_final NULL means "never
    # edited", so a deletion has to be read from the append-only correction log —
    # without that clause, deleting a wrong value would look identical to
    # accepting it. A field correctly absent on both sides (no extracted value, no
    # correction) makes no claim and is left out of both numerator and denominator.
    accuracy_row = (
        await session.execute(
            text(
                """
                WITH reviewed AS (
                    SELECT id FROM annotations
                    WHERE status IN ('confirmed','approved','exporting','exported')
                ),
                per_field AS (
                    SELECT f.annotation_id,
                           f.value_extracted IS NOT NULL AS had_value,
                           (COALESCE(f.value_final, f.value_extracted)
                                IS DISTINCT FROM f.value_extracted
                            OR EXISTS (
                                SELECT 1 FROM field_corrections c
                                WHERE c.annotation_id = f.annotation_id
                                  AND c.field_key = f.field_key
                                  AND c.row_index IS NOT DISTINCT FROM f.row_index
                                  AND c.action = 'delete')) AS corrected
                    FROM extracted_fields f JOIN reviewed r ON r.id = f.annotation_id
                )
                SELECT count(DISTINCT annotation_id) AS annotations,
                       count(*) FILTER (WHERE had_value OR corrected) AS fields_total,
                       count(*) FILTER (WHERE corrected) AS fields_corrected
                FROM per_field
                """
            )
        )
    ).one()

    accuracy = (
        AccuracyStats(
            annotations=int(accuracy_row.annotations),
            fields_total=int(accuracy_row.fields_total),
            fields_corrected=int(accuracy_row.fields_corrected),
        )
        if int(accuracy_row.fields_total) > 0
        else None
    )

    return Stats(
        documents_total=int(counts.documents_total),
        processed=int(counts.processed),
        in_progress=int(counts.in_progress),
        awaiting_review=int(counts.awaiting_review),
        blocked=int(counts.blocked),
        confirmed=int(counts.confirmed),
        failed=int(counts.failed),
        from_signed_xml=int(counts.from_signed_xml),
        accuracy=accuracy,
    )


@router.get("/templates", summary="Extraction schemas (read-only)")
async def list_templates(
    session: AsyncSession = Depends(get_tenant_session),
) -> list[TemplateOut]:
    """Every extraction schema this tenant has, newest version first per queue.

    ``in_use`` is the highest version per queue, because that is what the
    pipeline reads (``ORDER BY version DESC LIMIT 1``) — not what a column says.
    """
    rows = (
        await session.execute(
            text(
                "SELECT e.id, e.version, e.definition, e.created_at, q.id AS queue_id, "
                "q.name AS queue_name, "
                "e.version = max(e.version) OVER (PARTITION BY e.queue_id) AS in_use "
                "FROM extraction_schemas e LEFT JOIN queues q ON q.id = e.queue_id "
                "ORDER BY q.name NULLS LAST, e.version DESC"
            )
        )
    ).all()
    return [
        TemplateOut(
            id=r.id,
            version=r.version,
            name=r.definition.get("name") if isinstance(r.definition, dict) else None,
            queue_id=r.queue_id,
            queue_name=r.queue_name,
            in_use=bool(r.in_use),
            created_at=r.created_at,
            fields=schema_fields_from_definition(r.definition),
        )
        for r in rows
    ]


@router.get("/org", summary="The caller's organization")
async def get_org(
    org_id: uuid.UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> OrgOut:
    """Who the dashboard is showing. Read by id — this is the tenant's own row,
    and RLS on `organizations` matches `id`, so no other org is visible."""
    row = (
        await session.execute(
            text("SELECT id, name, vat_number, data_region FROM organizations WHERE id = :id"),
            {"id": org_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    return OrgOut(id=row.id, name=row.name, vat_number=row.vat_number, data_region=row.data_region)


@router.get("/system", summary="Non-secret runtime configuration")
async def get_system(
    _org: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_app_settings),
) -> SystemInfo:
    """What the settings page shows. Nothing secret: no URLs, keys or credentials."""
    return SystemInfo(
        environment=settings.ENVIRONMENT,
        inference_model=settings.INFERENCE_MODEL,
        extraction_use_vision=settings.EXTRACTION_USE_VISION,
        ocr_engine=settings.OCR_ENGINE,
        max_upload_bytes=settings.MAX_UPLOAD_BYTES,
        grounding_threshold=settings.GROUNDING_THRESHOLD,
        stalled_after_s=settings.STALLED_AFTER_S,
    )
