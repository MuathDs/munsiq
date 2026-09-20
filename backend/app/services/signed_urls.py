"""Short-lived signed URLs for page images and document uploads.

Local filesystem storage has no presigning, so this is the equivalent: a token
the server mints and later verifies, standing in for what S3 would issue. The
seam matches, so swapping to real presigned URLs later changes this module and
nothing else.

WHY THE SIGNATURE COVERS org_id, AND WHY THAT IS NOT A HARD-RULE VIOLATION.

CLAUDE.md forbids reading tenant identity from a request body or query
parameter, because a caller could otherwise choose which tenant's data to read.
The token below carries an org_id, which superficially looks like exactly that.
It is not, and the distinction is the whole point:

* The org_id is not *read* from the request as an assertion of identity. It is
  *verified* against an HMAC that only this server can produce.
* Changing a single character of the payload invalidates the signature, so a
  caller cannot substitute another tenant's id.
* A leaked URL is therefore bound to the tenant it was minted for and expires in
  minutes. It cannot be replayed across tenants.

This is the same model as an S3 presigned URL, where authorization travels in
the signature rather than in a session. An `<img src>` cannot carry a bearer
token, so the URL has to be self-authorizing.

UPLOADS use the same mechanism for the same reason CLAUDE.md gives for images:
document bytes must not stream through Next.js. The BFF, which holds the tenant
identity, asks this API to authorize an upload; the browser then posts the PDF
straight to the API against the returned token. Tokens are bound to a *kind*, so
a page-image token can never authorize an upload, nor an upload token a read.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Final

from app.config import get_settings

logger = logging.getLogger(__name__)

_ALGORITHM: Final[str] = "sha256"
_SEPARATOR: Final[str] = "."

_dev_secret: str | None = None


class SignatureError(Exception):
    """The token was missing, malformed, tampered with, or expired."""


def _secret() -> str:
    """The HMAC key.

    In non-local environments an unset secret is fatal: signing with a known or
    empty key would make every page image world-readable across tenants.

    Locally an unset secret generates a random per-process key. URLs then stop
    working after a restart, which is harmless given the five-minute expiry and
    is far better than shipping a hardcoded default that could reach production.
    """
    global _dev_secret
    settings = get_settings()
    configured = settings.IMAGE_URL_SECRET.strip()
    if configured:
        return configured

    if settings.ENVIRONMENT != "local":
        raise SignatureError(
            "IMAGE_URL_SECRET is not set. Refusing to sign page URLs with an empty key."
        )

    if _dev_secret is None:
        _dev_secret = secrets.token_urlsafe(32)
        logger.warning(
            "signed_urls.ephemeral_secret",
            extra={"detail": "IMAGE_URL_SECRET unset; using a per-process key (local only)."},
        )
    return _dev_secret


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _seal(payload: dict[str, object]) -> str:
    """Serialize and sign a payload. Sorted keys keep signing deterministic."""
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(_secret().encode(), encoded.encode(), _ALGORITHM).digest()
    return f"{encoded}{_SEPARATOR}{_b64encode(signature)}"


def _open(token: str) -> dict[str, object]:
    """Verify the signature, then the payload's shape, then its expiry — in that
    order, so a tampered token is reported as tampered whatever its clock says.

    Raises:
        SignatureError: malformed, tampered with, or expired.
    """
    if not token or _SEPARATOR not in token:
        raise SignatureError("malformed token")

    encoded, _, provided = token.partition(_SEPARATOR)
    expected = hmac.new(_secret().encode(), encoded.encode(), _ALGORITHM).digest()

    try:
        given = _b64decode(provided)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise SignatureError("malformed signature") from exc

    # Constant time: a length-or-content comparison that short-circuits would
    # leak the signature one byte at a time.
    if not hmac.compare_digest(expected, given):
        raise SignatureError("signature does not match")

    try:
        payload = json.loads(_b64decode(encoded))
        expires_at = int(payload["e"])
    except (ValueError, KeyError, TypeError) as exc:
        raise SignatureError("malformed payload") from exc
    if not isinstance(payload, dict):
        raise SignatureError("malformed payload")

    if time.time() > expires_at:
        raise SignatureError("token has expired")
    return payload


@dataclass(frozen=True)
class PageGrant:
    """What a verified token authorizes."""

    org_id: uuid.UUID
    document_id: uuid.UUID
    page_number: int


def sign_page_token(
    org_id: uuid.UUID, document_id: uuid.UUID, page_number: int, ttl_s: int | None = None
) -> str:
    """Mint a token authorizing one page image of one document for one tenant."""
    settings = get_settings()
    ttl = settings.PAGE_URL_TTL_S if ttl_s is None else ttl_s
    return _seal(
        {
            "o": str(org_id),
            "d": str(document_id),
            "p": int(page_number),
            "e": int(time.time()) + ttl,
        }
    )


def verify_page_token(token: str) -> PageGrant:
    """Verify a token and return what it authorizes.

    Raises:
        SignatureError: malformed, tampered with, or expired.
    """
    payload = _open(token)
    try:
        return PageGrant(
            org_id=uuid.UUID(str(payload["o"])),
            document_id=uuid.UUID(str(payload["d"])),
            page_number=int(payload["p"]),  # type: ignore[call-overload]
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise SignatureError("malformed payload") from exc


UPLOAD_KIND: Final[str] = "upload"


@dataclass(frozen=True)
class UploadGrant:
    """What a verified upload token authorizes: uploading, for one tenant."""

    org_id: uuid.UUID


def sign_upload_token(org_id: uuid.UUID, ttl_s: int | None = None) -> str:
    """Mint a token authorizing document uploads for one tenant.

    The ``k`` claim binds it to uploads. A page-image token has no ``k``, so it
    is refused here; an upload token has no document or page, so it is refused
    by the image route.
    """
    settings = get_settings()
    ttl = settings.UPLOAD_URL_TTL_S if ttl_s is None else ttl_s
    return _seal({"k": UPLOAD_KIND, "o": str(org_id), "e": int(time.time()) + ttl})


def verify_upload_token(token: str) -> UploadGrant:
    """Verify an upload token.

    Raises:
        SignatureError: malformed, tampered with, expired, or not an upload token.
    """
    payload = _open(token)
    if payload.get("k") != UPLOAD_KIND:
        raise SignatureError("token is not an upload token")
    try:
        return UploadGrant(org_id=uuid.UUID(str(payload["o"])))
    except (ValueError, KeyError, TypeError) as exc:
        raise SignatureError("malformed payload") from exc


def page_image_path(token: str, prefix: str = "/api/v1") -> str:
    """The URL an <img src> should point at."""
    return f"{prefix}/pages/image?token={token}"
