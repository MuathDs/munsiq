"""Page image delivery.

This route is deliberately NOT behind the tenant session dependency, and that is
not an oversight.

An ``<img src>`` cannot carry a bearer token or a session cookie the way a fetch
can, so the URL has to authorize itself. Authorization travels in an HMAC
signature that covers the tenant, the document and the page, and expires in
minutes — the same model as an S3 presigned URL, which is what this stands in
for until storage moves off the local filesystem.

The signature is what makes this safe:

* the tenant is *verified* against a signature only this server can produce, not
  *read* from a caller-supplied parameter;
* tampering with any part of the payload invalidates it;
* a leaked URL is bound to one tenant, one document and one page, and dies in
  five minutes. It cannot be replayed across tenants.

CLAUDE.md forbids streaming document bytes through Next.js, which is exactly why
this lives here rather than in a frontend route handler.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.services import storage as storage_mod
from app.services.signed_urls import SignatureError, verify_page_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pages", tags=["pages"])

CACHE_CONTROL = "private, max-age=300, no-transform"


@router.get(
    "/image",
    summary="Serve a page image against a short-lived signed token",
    response_class=Response,
    responses={
        200: {"content": {"image/webp": {}}, "description": "The page image"},
        403: {"description": "Missing, tampered, or expired token"},
    },
)
async def get_page_image(token: str = Query(..., description="Signed page token")) -> Response:
    """Return one page's WebP.

    Verifies the signature BEFORE touching storage, so an invalid token costs a
    hash comparison and nothing else.
    """
    try:
        grant = verify_page_token(token)
    except SignatureError as exc:
        # One undifferentiated 403 for missing, tampered and expired. Telling a
        # caller which of those it was helps them probe, and helps nobody else.
        logger.info("page_image.rejected", extra={"reason": str(exc)})
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or expired image token.") from exc

    key = storage_mod.page_key(grant.org_id, grant.document_id, grant.page_number)
    try:
        data = storage_mod.get_storage().get(key)
    except storage_mod.StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page image not found.") from exc

    return Response(
        content=data,
        media_type="image/webp",
        headers={
            # `private` keeps it out of shared caches; the token expires anyway,
            # but a signed URL should never land in a CDN serving other tenants.
            "Cache-Control": CACHE_CONTROL,
            "X-Content-Type-Options": "nosniff",
        },
    )
