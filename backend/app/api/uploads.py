"""Document upload and status.

Processing runs in a FastAPI BackgroundTask rather than an arq worker: this
deployment has no Redis (no Docker on Windows). The pipeline entry point is a
plain coroutine, so moving to arq later is a call-site change, not a rewrite.
The trade-off — no retries, no durability across a restart — is recorded in
CLAUDE.md under the deferred section.

TWO WAYS IN, ONE HANDLER. ``POST /documents`` accepts either:

* the trusted-BFF headers (service-to-service, what an API client or a test uses), or
* a signed ``upload_token`` minted by ``POST /documents/authorize``.

The token path exists because CLAUDE.md forbids streaming document bytes through
Next.js. The BFF holds the tenant identity, so it asks THIS API for an
authorization; the browser then posts the PDF straight here, which is also the
only way to get real upload progress. The tenant in the token is verified against
an HMAC only this server can produce — never read from the request. See
app/services/signed_urls.py for why that is not a hard-rule violation.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import text as sql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ORG_HEADER,
    SECRET_HEADER,
    get_app_settings,
    get_current_org_id,
    get_tenant_session,
)
from app.config import Settings
from app.db.session import session_scope
from app.schemas.documents import (
    DocumentStatus,
    PageStatus,
    UploadAuthorization,
    UploadResponse,
)
from app.services import storage as storage_mod
from app.services.pipeline import process_document
from app.services.signed_urls import SignatureError, sign_upload_token, verify_upload_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MAX_FILENAME = 255


def safe_filename(raw: str | None) -> str | None:
    """A display name from an attacker-controlled string.

    Keeps the last path component (some clients send the full path), drops
    control characters, and caps the length. It is display-only: storage keys
    are built from UUIDs and never from this.
    """
    if not raw:
        return None
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_CHARS.sub("", name).strip()
    return name[:_MAX_FILENAME] or None


# --------------------------------------------------------------------------- #
# Who is uploading
# --------------------------------------------------------------------------- #
async def get_upload_org_id(
    upload_token: str | None = Query(
        default=None, description="Signed token from POST /documents/authorize."
    ),
    x_munsiq_org: str | None = Header(default=None, alias=ORG_HEADER),
    x_munsiq_bff_secret: str | None = Header(default=None, alias=SECRET_HEADER),
    settings: Settings = Depends(get_app_settings),
) -> uuid.UUID:
    """The tenant for an upload: from a verified token, else from the trusted BFF.

    A token that is PRESENT but bad is refused outright. Silently falling back to
    the header path would let a malformed token quietly become a different kind
    of request, and a caller who sent one clearly meant to use it.
    """
    if upload_token:
        try:
            return verify_upload_token(upload_token).org_id
        except SignatureError as exc:
            # One undifferentiated 403, as for page images: telling a caller
            # whether it was tampered, expired or the wrong kind only helps them probe.
            logger.info("upload.token_rejected", extra={"reason": str(exc)})
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Invalid or expired upload token."
            ) from exc
    return await get_current_org_id(x_munsiq_org, x_munsiq_bff_secret, settings)


@router.post(
    "/authorize",
    summary="Authorize a browser to upload one PDF directly to this API",
)
async def authorize_upload(
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_app_settings),
) -> UploadAuthorization:
    """Mint a short-lived upload URL for the caller's tenant.

    Called by the BFF, which knows the tenant. The browser never sees a tenant id
    — only an opaque signed URL that expires in minutes.
    """
    token = sign_upload_token(org_id)
    return UploadAuthorization(
        upload_url=f"{settings.API_V1_PREFIX}/documents?upload_token={token}",
        expires_in=settings.UPLOAD_URL_TTL_S,
        max_bytes=settings.MAX_UPLOAD_BYTES,
    )


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
async def _existing_document(session: AsyncSession, sha: bytes, stall_s: int) -> Any:
    """The document already stored for these exact bytes, with its current state.

    `state` mirrors the dashboard's: the latest annotation's status, or
    'processing' / 'stalled' when there is none yet.
    """
    return (
        await session.execute(
            sql(
                "SELECT d.id AS document_id, a.id AS annotation_id, "
                "CASE WHEN a.id IS NOT NULL THEN a.status::text "
                "     WHEN d.created_at < now() - "
                "       make_interval(secs => CAST(:stall AS double precision)) "
                "       THEN 'stalled' ELSE 'processing' END AS state "
                "FROM documents d "
                "LEFT JOIN LATERAL (SELECT id, status FROM annotations "
                "  WHERE document_id = d.id ORDER BY created_at DESC LIMIT 1) a ON true "
                "WHERE d.sha256 = :sha LIMIT 1"
            ),
            {"sha": sha, "stall": float(stall_s)},
        )
    ).first()


async def insert_document_row(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    queue_id: uuid.UUID,
    document_id: uuid.UUID,
    storage_key: str,
    mime_type: str,
    filename: str | None,
    sha: bytes,
) -> bool:
    """Insert the document. False if UNIQUE(org_id, sha256) says it already exists.

    The savepoint is what makes a lost race survivable: an IntegrityError inside
    the outer transaction would otherwise poison it, and the caller could not
    even look up the row that beat it.
    """
    try:
        async with session.begin_nested():
            await session.execute(
                sql(
                    "INSERT INTO documents (id, org_id, queue_id, storage_key, mime_type, "
                    "source, filename, sha256) "
                    "VALUES (:id, :org, :q, :key, :mime, 'upload', :name, :sha)"
                ),
                {
                    "id": document_id,
                    "org": org_id,
                    "q": queue_id,
                    "key": storage_key,
                    "mime": mime_type,
                    "name": filename,
                    "sha": sha,
                },
            )
    except IntegrityError:
        return False
    return True


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF for processing",
    responses={
        200: {"description": "This exact file was already uploaded; the existing document"},
        403: {"description": "Bad or expired upload token"},
        413: {"description": "Larger than MAX_UPLOAD_BYTES"},
        415: {"description": "Not a PDF"},
    },
)
async def upload_document(
    background: BackgroundTasks,
    response: Response,
    file: UploadFile = File(...),
    org_id: uuid.UUID = Depends(get_upload_org_id),
    settings: Settings = Depends(get_app_settings),
) -> UploadResponse:
    """Store the PDF and queue processing.

    Returns 202: the document row exists immediately, extraction happens after
    the response. Poll GET /documents (or /documents/{id}) for progress.

    IDEMPOTENT ON CONTENT. Suppliers resend invoices all the time. The bytes are
    hashed BEFORE anything is stored: a file this tenant already has returns the
    existing document with 200 — never a 500, and never a second pipeline run. The
    one exception is a document whose earlier attempt FAILED or STALLED: uploading
    it again is how the reviewer retries, so it is processed again in place.

    THIS HANDLER OWNS ITS TRANSACTION, and that is load-bearing. It does not take a
    session as a dependency, because a yield-dependency's teardown — where its
    transaction commits — runs after the response and its background tasks in
    FastAPI >= 0.118. The pipeline would then open its own session looking for a
    document that was not committed yet, and fail with "not found for this tenant".
    So the writes happen inside an explicit scope that commits on exit, and the
    pipeline is scheduled only after it has.
    """
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file was empty.")
    if len(payload) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File exceeds MAX_UPLOAD_BYTES ({settings.MAX_UPLOAD_BYTES}).",
        )
    # The header may sit within the first KiB (PDF 1.7 §7.5.2). Cheap, and it
    # turns "someone uploaded a .txt" into an immediate 415 instead of a failed
    # document a minute later. content_type is client-supplied, so not trusted.
    if b"%PDF-" not in payload[:1024]:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files can be uploaded."
        )

    filename = safe_filename(file.filename)
    sha = hashlib.sha256(payload).digest()

    async with session_scope(org_id) as session:
        existing = await _existing_document(session, sha, settings.STALLED_AFTER_S)

        if existing is None:
            queue_id = await session.scalar(
                sql("SELECT id FROM queues ORDER BY created_at LIMIT 1")
            )
            if queue_id is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "No queue configured for this organization. Run scripts/seed_demo.py.",
                )

            document_id = uuid.uuid4()
            key = storage_mod.document_key(org_id, document_id, "original.pdf")
            storage_mod.get_storage().put(key, payload)

            inserted = await insert_document_row(
                session,
                org_id=org_id,
                queue_id=queue_id,
                document_id=document_id,
                storage_key=key,
                mime_type="application/pdf",
                filename=filename,
                sha=sha,
            )
            if inserted:
                result = UploadResponse(
                    document_id=document_id,
                    filename=filename,
                    size_bytes=len(payload),
                    status="processing",
                )
                run_pipeline = True
            else:
                # Two identical uploads raced and the other one won. The
                # constraint is the backstop; the outcome is the same as the
                # pre-check: the existing document.
                storage_mod.get_storage().delete_prefix(f"{org_id}/documents/{document_id}")
                existing = await _existing_document(session, sha, settings.STALLED_AFTER_S)
                if existing is None:  # pragma: no cover - the constraint fired, so it exists
                    raise HTTPException(
                        status.HTTP_409_CONFLICT, "Duplicate upload could not be resolved."
                    )

        if existing is not None:
            result, run_pipeline = await _resolve_duplicate(
                existing, session, filename, len(payload)
            )

    # Committed. Only now may the pipeline look for the row.
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    if run_pipeline:
        background.add_task(process_document, org_id, result.document_id)
    return result


async def _resolve_duplicate(
    existing: Any,
    session: AsyncSession,
    filename: str | None,
    size_bytes: int,
) -> tuple[UploadResponse, bool]:
    """Answer an upload of bytes we already hold. Returns (response, run_pipeline)."""
    if existing.state in ("failed", "stalled"):
        # The earlier attempt produced nothing usable. Clear the failed annotation
        # (its findings and fields cascade) so the dashboard shows 'processing'
        # rather than the old failure; the caller then runs the pipeline again on
        # the same stored bytes.
        if existing.annotation_id is not None:
            await session.execute(
                sql("DELETE FROM annotations WHERE id = :a"), {"a": existing.annotation_id}
            )
        return (
            UploadResponse(
                document_id=existing.document_id,
                filename=filename,
                size_bytes=size_bytes,
                status="processing",
                retried=True,
            ),
            True,
        )

    return (
        UploadResponse(
            document_id=existing.document_id,
            filename=filename,
            size_bytes=size_bytes,
            status=existing.state,
            annotation_id=existing.annotation_id,
            duplicate=True,
        ),
        False,
    )


@router.get("/{document_id}", summary="Document status, pages and extracted fields")
async def get_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_tenant_session),
) -> DocumentStatus:
    """Read processing state. RLS scopes this to the caller's tenant.

    Deliberately NOT ``get_upload_session``: an upload token authorizes writing a
    document, never reading one.
    """
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
