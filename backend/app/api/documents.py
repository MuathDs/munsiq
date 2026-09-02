"""Document endpoints.

Phase 1 ships exactly one route here, and it is temporary.

SECURITY: /probe accepts UNAUTHENTICATED file uploads. There is no auth layer,
no tenant scoping and no rate limit in Phase 1, so anyone who can reach this
route can push bytes into the process. It is registered only when
``settings.DEBUG_ENDPOINTS`` is true (default False) and must stay off anywhere
reachable from a network you do not control. It exists to eyeball Step Zero
against real invoices by hand and will be deleted once Phase 3 lands the real
upload flow.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.schemas.invoice import ProbeResponse
from app.services.ubl import (
    MalformedPDFError,
    MalformedXMLError,
    extract_embedded_xml,
    parse_ubl_invoice,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents (debug)"])


@router.post(
    "/probe",
    summary="TEMPORARY: check a PDF for embedded UBL and parse it",
    response_model=ProbeResponse,
)
async def probe_document(file: UploadFile = File(...)) -> ProbeResponse:
    """Run ZATCA Step Zero against an uploaded PDF and return what was found.

    No database write, no model call, no persistence of any kind — the bytes are
    read, inspected and dropped.
    """
    settings = get_settings()
    payload = await file.read()

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file was empty.",
        )
    if len(payload) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds MAX_UPLOAD_BYTES ({settings.MAX_UPLOAD_BYTES} bytes).",
        )

    try:
        xml_bytes = extract_embedded_xml(payload)
    except MalformedPDFError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    if xml_bytes is None:
        # Not an error. Most Saudi AP intake is still plain scans; those take the
        # model path in Phase 4. Step Zero simply had nothing to do.
        return ProbeResponse(
            filename=file.filename,
            size_bytes=len(payload),
            has_embedded_ubl=False,
        )

    try:
        invoice = parse_ubl_invoice(xml_bytes)
    except MalformedXMLError as exc:
        # The attachment was there but unparseable — worth reporting distinctly
        # from "no attachment", because it is a supplier-side compliance defect.
        return ProbeResponse(
            filename=file.filename,
            size_bytes=len(payload),
            has_embedded_ubl=True,
            embedded_xml_bytes=len(xml_bytes),
            parse_error=str(exc),
        )

    return ProbeResponse(
        filename=file.filename,
        size_bytes=len(payload),
        has_embedded_ubl=True,
        embedded_xml_bytes=len(xml_bytes),
        invoice=invoice,
    )
