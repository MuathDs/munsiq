"""Export a confirmed annotation as MunsiqInvoiceV1 (JSON, XLSX or CSV).

Only a confirmed annotation leaves the system. Confirmation is where the
deterministic rules stop being advisory, so exporting anything earlier would
push a document downstream that nobody signed off and that may not add up.

Every successful export writes an ``exports`` row: what went out, in which
format, and a hash of the bytes, so "what did we send the ERP" has an answer.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_tenant_session
from app.schemas.export import ExportFormat
from app.services.export import (
    ExportBatchError,
    ExportNotConfirmedError,
    ExportNotFoundError,
    load_batch,
    load_invoice,
    record_exports,
    render,
    render_batch_xlsx,
)

router = APIRouter(prefix="/annotations", tags=["exports"])

_STATUS_AR = {
    "importing": "قيد الاستيراد",
    "processing": "قيد المعالجة",
    "to_review": "بانتظار المراجعة",
    "reviewing": "قيد المراجعة",
    "approved": "مُصادق عليها",
    "rejected": "مرفوضة",
    "exported": "مُصدَّرة",
    "failed": "فشلت",
}


@router.get(
    "/{annotation_id}/export",
    summary="Export a confirmed annotation as MunsiqInvoiceV1",
    responses={
        404: {"description": "No such annotation for this tenant"},
        409: {"description": "Not confirmed yet; message in Arabic and English"},
    },
)
async def export_annotation(
    annotation_id: uuid.UUID,
    export_format: ExportFormat = Query(
        default="json",
        alias="format",
        description="json is the contract itself; xlsx and csv are renderings of it.",
    ),
    org_id: uuid.UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> Response:
    try:
        invoice = await load_invoice(session, annotation_id)
    except ExportNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found.") from None
    except ExportNotConfirmedError as exc:
        message_en = (
            f"Only a confirmed annotation can be exported. This one is '{exc.status}'; "
            "resolve any blocking findings and confirm it first."
        )
        message_ar = (
            "لا يمكن تصدير الفاتورة قبل اعتمادها. حالتها الحالية: "
            f"{_STATUS_AR.get(exc.status, exc.status)}. "
            "عالج الملاحظات الحاجبة ثم اعتمدها أولاً."
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "detail": message_en,
                "message_en": message_en,
                "message_ar": message_ar,
                "status": exc.status,
            },
        ) from None

    rendered = render(invoice, export_format)
    await record_exports(
        session, org_id, [invoice], export_format=export_format, body=rendered.body
    )
    return Response(
        content=rendered.body,
        media_type=rendered.media_type,
        headers={"Content-Disposition": f'attachment; filename="{rendered.filename}"'},
    )


MAX_BATCH = 200


class BatchExportRequest(BaseModel):
    ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=MAX_BATCH,
        description="Annotations to export together. Repeats are collapsed.",
    )


@router.post(
    "/export",
    summary="Export several confirmed annotations as one Excel workbook",
    responses={
        404: {"description": "An id is unknown to this tenant"},
        409: {"description": "One or more are not confirmed; nothing was exported"},
    },
)
async def export_batch(
    body: BatchExportRequest,
    org_id: uuid.UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> Response:
    """One workbook, a row per invoice and a row per line item.

    All or nothing: a single unconfirmed invoice refuses the whole batch and names
    every offender, so nothing is half exported and marked as sent.
    """
    try:
        invoices = await load_batch(session, body.ids)
    except ExportBatchError as exc:
        if exc.missing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found.") from None
        listed = [{"id": str(i), "status": s} for i, s in exc.not_confirmed]
        message_en = (
            f"{len(listed)} of the selected invoices are not confirmed. Only confirmed "
            "invoices can be exported; nothing was exported."
        )
        message_ar = (
            f"{len(listed)} من الفواتير المحددة غير معتمدة. لا يمكن تصدير إلا الفواتير "
            "المعتمدة؛ لم يُصدَّر شيء."
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "detail": message_en,
                "message_en": message_en,
                "message_ar": message_ar,
                "not_confirmed": listed,
            },
        ) from None

    rendered = render_batch_xlsx(invoices)
    await record_exports(
        session,
        org_id,
        invoices,
        export_format="xlsx",
        body=rendered.body,
        batch_size=len(invoices),
    )
    return Response(
        content=rendered.body,
        media_type=rendered.media_type,
        headers={"Content-Disposition": f'attachment; filename="{rendered.filename}"'},
    )
