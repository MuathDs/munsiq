"""Export a confirmed annotation as MunsiqInvoiceV1 (JSON, XLSX or CSV).

Only a confirmed annotation leaves the system. Confirmation is where the
deterministic rules stop being advisory, so exporting anything earlier would
push a document downstream that nobody signed off and that may not add up.

Every successful export writes an ``exports`` row: what went out, in which
format, and a hash of the bytes, so "what did we send the ERP" has an answer.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id, get_tenant_session
from app.schemas.export import SCHEMA_VERSION, ExportFormat
from app.services.export import (
    ExportNotConfirmedError,
    ExportNotFoundError,
    load_invoice,
    render,
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
    await session.execute(
        text(
            "INSERT INTO exports (org_id, annotation_id, target, status, attempts, response) "
            "VALUES (:org, :a, :target, 'completed', 1, CAST(:response AS jsonb))"
        ),
        {
            "org": org_id,
            "a": annotation_id,
            "target": export_format,
            "response": json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "format": export_format,
                    "bytes": len(rendered.body),
                    "sha256": hashlib.sha256(rendered.body).hexdigest(),
                    "fields": len(invoice.invoice),
                    "line_items": len(invoice.line_items),
                }
            ),
        },
    )
    return Response(
        content=rendered.body,
        media_type=rendered.media_type,
        headers={"Content-Disposition": f'attachment; filename="{rendered.filename}"'},
    )
