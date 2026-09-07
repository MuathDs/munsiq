"""Document upload and status.

Processing runs in a FastAPI BackgroundTask rather than an arq worker: this
deployment has no Redis (no Docker on Windows). The pipeline entry point is a
plain coroutine, so moving to arq later is a call-site change, not a rewrite.
The trade-off — no retries, no durability across a restart — is recorded in
CLAUDE.md under the deferred section.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_tenant_session
from app.config import get_settings
from app.schemas.documents import DocumentStatus, PageStatus, UploadResponse
from app.services import storage as storage_mod
from app.services.pipeline import process_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, summary="Upload a PDF for processing")
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    org_id: uuid.UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> UploadResponse:
    """Store the PDF and queue processing.

    Returns 202: the document row exists immediately, extraction happens after
    the response. Poll GET /documents/{id} for progress.
    """
    settings = get_settings()
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file was empty.")
    if len(payload) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File exceeds MAX_UPLOAD_BYTES ({settings.MAX_UPLOAD_BYTES}).",
        )

    queue_id = await session.scalar(sql("SELECT id FROM queues ORDER BY created_at LIMIT 1"))
    if queue_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No queue configured for this organization. Run scripts/seed_demo.py.",
        )

    document_id = uuid.uuid4()
    key = storage_mod.document_key(org_id, document_id, "original.pdf")
    storage_mod.get_storage().put(key, payload)

    await session.execute(
        sql(
            "INSERT INTO documents (id, org_id, queue_id, storage_key, mime_type, source) "
            "VALUES (:id, :org, :q, :key, :mime, 'upload')"
        ),
        {
            "id": document_id,
            "org": org_id,
            "q": queue_id,
            "key": key,
            "mime": file.content_type or "application/pdf",
        },
    )

    background.add_task(process_document, org_id, document_id)

    return UploadResponse(
        document_id=document_id,
        filename=file.filename,
        size_bytes=len(payload),
        status="processing",
    )


@router.get("/{document_id}", summary="Document status, pages and extracted fields")
async def get_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_tenant_session),
) -> DocumentStatus:
    """Read processing state. RLS scopes this to the caller's tenant."""
    doc = (
        await session.execute(
            sql("SELECT id, page_count, has_embedded_ubl, mime_type FROM documents WHERE id = :id"),
            {"id": document_id},
        )
    ).first()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")

    annotation = (
        await session.execute(
            sql(
                "SELECT id, status, model_version, automated FROM annotations "
                "WHERE document_id = :id ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": document_id},
        )
    ).first()

    pages = (
        await session.execute(
            sql(
                "SELECT page_number, text_source, image_key, width_px, height_px "
                "FROM pages WHERE document_id = :id ORDER BY page_number"
            ),
            {"id": document_id},
        )
    ).all()

    fields: dict[str, str | None] = {}
    findings: list[str] = []
    if annotation is not None:
        rows = (
            await session.execute(
                sql(
                    "SELECT field_key, value_extracted FROM extracted_fields "
                    "WHERE annotation_id = :a ORDER BY field_key"
                ),
                {"a": annotation.id},
            )
        ).all()
        fields = {r.field_key: r.value_extracted for r in rows}
        findings = [
            r.rule_code
            for r in (
                await session.execute(
                    sql("SELECT rule_code FROM validation_results WHERE annotation_id = :a"),
                    {"a": annotation.id},
                )
            ).all()
        ]

    return DocumentStatus(
        document_id=doc.id,
        status=annotation.status if annotation else "processing",
        page_count=doc.page_count,
        has_embedded_ubl=doc.has_embedded_ubl,
        model_version=annotation.model_version if annotation else None,
        automated=bool(annotation.automated) if annotation else False,
        annotation_id=annotation.id if annotation else None,
        pages=[
            PageStatus(
                page_number=p.page_number,
                text_source=p.text_source,
                width_px=p.width_px,
                height_px=p.height_px,
            )
            for p in pages
        ],
        fields=fields,
        findings=findings,
    )
