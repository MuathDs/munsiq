"""Signed page-image tokens.

A page image URL authorizes itself, because an <img src> cannot carry a bearer
token. That makes the signature the entire security boundary, so these tests
attack it rather than merely exercising it.

The property that matters most: **a leaked URL must not be replayable across
tenants.** The signature covers the org_id, so swapping it invalidates the token.
"""

from __future__ import annotations

import time
import uuid

import pytest

from app.services.signed_urls import (
    PageGrant,
    SignatureError,
    page_image_path,
    sign_page_token,
    verify_page_token,
)

ORG = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-4222-8222-222222222222")
DOC = uuid.UUID("33333333-3333-4333-8333-333333333333")
OTHER_DOC = uuid.UUID("44444444-4444-4444-8444-444444444444")


def test_round_trip_recovers_exactly_what_was_signed() -> None:
    grant = verify_page_token(sign_page_token(ORG, DOC, 3))
    assert grant == PageGrant(org_id=ORG, document_id=DOC, page_number=3)


# --------------------------------------------------------------------------- #
# The cross-tenant replay attack
# --------------------------------------------------------------------------- #
def test_a_token_cannot_be_replayed_against_another_tenant() -> None:
    """THE point of signing the org_id.

    Take a valid token, swap the tenant in its payload, and it must not verify.
    Otherwise a leaked URL would read any tenant's pages.
    """
    import base64
    import json

    token = sign_page_token(ORG, DOC, 1)
    encoded, _, signature = token.partition(".")

    payload = json.loads(base64.urlsafe_b64decode(encoded + "=="))
    assert payload["o"] == str(ORG)
    payload["o"] = str(OTHER_ORG)

    forged = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        .decode()
        .rstrip("=")
    )

    with pytest.raises(SignatureError):
        verify_page_token(f"{forged}.{signature}")


def test_tokens_for_different_tenants_differ() -> None:
    assert sign_page_token(ORG, DOC, 1) != sign_page_token(OTHER_ORG, DOC, 1)


def test_a_token_is_bound_to_its_document_and_page() -> None:
    """Scope is per page, so one leaked URL is not a key to the whole document."""
    assert sign_page_token(ORG, DOC, 1) != sign_page_token(ORG, OTHER_DOC, 1)
    assert sign_page_token(ORG, DOC, 1) != sign_page_token(ORG, DOC, 2)


# --------------------------------------------------------------------------- #
# Tampering and malformed input
# --------------------------------------------------------------------------- #
def test_tampering_with_the_signature_is_rejected() -> None:
    encoded, _, signature = sign_page_token(ORG, DOC, 1).partition(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(SignatureError):
        verify_page_token(f"{encoded}.{flipped}")


def test_tampering_with_the_payload_is_rejected() -> None:
    encoded, _, signature = sign_page_token(ORG, DOC, 1).partition(".")
    with pytest.raises(SignatureError):
        verify_page_token(f"{encoded}x.{signature}")


@pytest.mark.parametrize(
    "token",
    ["", "no-separator", ".", "a.b", "....", "!!!.???"],
)
def test_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(SignatureError):
        verify_page_token(token)


def test_a_signature_from_a_different_payload_does_not_transfer() -> None:
    """Splicing one token's payload onto another's signature must fail."""
    payload_a, _, _ = sign_page_token(ORG, DOC, 1).partition(".")
    _, _, signature_b = sign_page_token(OTHER_ORG, OTHER_DOC, 9).partition(".")
    with pytest.raises(SignatureError):
        verify_page_token(f"{payload_a}.{signature_b}")


# --------------------------------------------------------------------------- #
# Expiry
# --------------------------------------------------------------------------- #
def test_an_expired_token_is_rejected() -> None:
    expired = sign_page_token(ORG, DOC, 1, ttl_s=-1)
    with pytest.raises(SignatureError, match="expired"):
        verify_page_token(expired)


def test_a_token_is_valid_up_to_its_expiry() -> None:
    token = sign_page_token(ORG, DOC, 1, ttl_s=60)
    assert verify_page_token(token).page_number == 1


def test_default_expiry_is_short() -> None:
    """A signed URL is a standing grant for as long as it lives. Keep it short."""
    from app.config import get_settings

    assert get_settings().PAGE_URL_TTL_S <= 300


def test_expiry_is_checked_after_the_signature() -> None:
    """An expired token with a broken signature must fail on the signature.

    Verifying expiry first would let an attacker distinguish "wrong key" from
    "right key, too old", which leaks whether they ever had a valid token.
    """
    encoded, _, _ = sign_page_token(ORG, DOC, 1, ttl_s=-1).partition(".")
    with pytest.raises(SignatureError, match="signature"):
        verify_page_token(f"{encoded}.AAAA")


def test_url_shape_is_a_query_token() -> None:
    url = page_image_path(sign_page_token(ORG, DOC, 1))
    assert url.startswith("/api/v1/pages/image?token=")
    # The tenant must not be legible as a plain parameter; it lives inside the
    # signed payload.
    assert str(ORG) not in url


def test_signing_is_stable_within_the_same_second() -> None:
    """Not a security property — a guard on accidental nondeterminism."""
    now = int(time.time())
    first = sign_page_token(ORG, DOC, 1, ttl_s=100)
    if int(time.time()) != now:  # pragma: no cover - clock rolled over mid-test
        pytest.skip("second boundary crossed")
    assert first == sign_page_token(ORG, DOC, 1, ttl_s=100)
