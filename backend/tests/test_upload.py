"""The upload path: presigned tokens, PDF validation, dedup, retry.

The first half needs no database. Those tests attack the token — kind binding,
tampering, expiry — because a token that authorizes writes into a tenant is a
standing grant while it lives, and the signature is the whole boundary.

The second half goes through the real app and the real database, with only the
background pipeline swapped for a recorder: what matters here is what the HTTP
layer decides, not what the model does with the PDF afterwards.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sql

from app.api import uploads as uploads_mod
from app.api.uploads import insert_document_row, safe_filename
from app.config import Settings, get_settings
from app.db.base import get_sessionmaker
from app.db.session import session_scope
from app.main import create_app
from app.services import pipeline as pipeline_mod
from app.services import storage as storage_mod
from app.services.signed_urls import (
    SignatureError,
    sign_page_token,
    sign_upload_token,
    verify_page_token,
    verify_upload_token,
)
from app.services.storage import LocalStorage
from tests import fixtures

ORG = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-4222-8222-222222222222")
DOC = uuid.UUID("33333333-3333-4333-8333-333333333333")
SECRET = "test-bff-secret-value"

needs_db = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)


# --------------------------------------------------------------------------- #
# The token (no database)
# --------------------------------------------------------------------------- #
def test_upload_token_round_trips_to_its_tenant() -> None:
    assert verify_upload_token(sign_upload_token(ORG)).org_id == ORG


def test_upload_token_cannot_be_replayed_against_another_tenant() -> None:
    """Swapping the org in the payload must break the signature."""
    token = sign_upload_token(ORG)
    forged = sign_upload_token(OTHER_ORG).split(".")[0] + "." + token.split(".")[1]
    with pytest.raises(SignatureError):
        verify_upload_token(forged)


def test_a_page_token_does_not_authorize_an_upload() -> None:
    """Kind binding: a leaked image URL must not become write access."""
    with pytest.raises(SignatureError, match="not an upload token"):
        verify_upload_token(sign_page_token(ORG, DOC, 1))


def test_an_upload_token_does_not_authorize_reading_a_page() -> None:
    """And the other way: write access must not become read access."""
    with pytest.raises(SignatureError):
        verify_page_token(sign_upload_token(ORG))


def test_a_tampered_upload_token_is_rejected() -> None:
    token = sign_upload_token(ORG)
    payload, signature = token.split(".")
    flipped = ("A" if payload[0] != "A" else "B") + payload[1:]
    with pytest.raises(SignatureError):
        verify_upload_token(f"{flipped}.{signature}")


def test_an_expired_upload_token_is_rejected() -> None:
    with pytest.raises(SignatureError, match="expired"):
        verify_upload_token(sign_upload_token(ORG, ttl_s=-1))


def test_default_upload_expiry_is_short() -> None:
    """The token is a standing write grant while it lives, so it lives minutes."""
    assert get_settings().UPLOAD_URL_TTL_S <= 600
    assert verify_upload_token(sign_upload_token(ORG)).org_id == ORG


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("invoice.pdf", "invoice.pdf"),
        (r"C:\Users\me\Desktop\invoice.pdf", "invoice.pdf"),
        ("/etc/passwd", "passwd"),
        ("../../evil.pdf", "evil.pdf"),
        ("a\x00b\x1f.pdf", "ab.pdf"),
        ("  spaced.pdf  ", "spaced.pdf"),
        ("فاتورة-٢٠٢٦.pdf", "فاتورة-٢٠٢٦.pdf"),
        ("", None),
        (None, None),
        ("///", None),
        ("x" * 400, "x" * 255),
    ],
)
def test_safe_filename(raw: str | None, expected: str | None) -> None:
    assert safe_filename(raw) == expected


# --------------------------------------------------------------------------- #
# The routes' auth (no database: every case is refused before a session opens)
# --------------------------------------------------------------------------- #
def bff_app(**overrides: object) -> object:
    settings = {
        "DEBUG_ENDPOINTS": False,
        "DATABASE_URL": "",
        "TRUSTED_BFF_ENABLED": True,
        "TRUSTED_BFF_SECRET": SECRET,
    }
    return create_app(Settings(**{**settings, **overrides}))  # type: ignore[arg-type]


def client_for(app: object) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    )


PDF = {"file": ("invoice.pdf", b"%PDF-1.7\n%%EOF\n", "application/pdf")}


async def test_authorize_mints_a_token_for_the_bffs_tenant() -> None:
    async with client_for(bff_app()) as client:
        response = await client.post(
            "/api/v1/documents/authorize",
            headers={"X-Munsiq-Org": str(ORG), "X-Munsiq-BFF-Secret": SECRET},
        )
    assert response.status_code == 200
    body = response.json()
    token = body["upload_url"].split("upload_token=")[1]
    assert verify_upload_token(token).org_id == ORG
    assert body["upload_url"].startswith("/api/v1/documents?upload_token=")
    assert body["max_bytes"] == get_settings().MAX_UPLOAD_BYTES


async def test_authorize_needs_the_bff_secret() -> None:
    async with client_for(bff_app()) as client:
        wrong = await client.post(
            "/api/v1/documents/authorize",
            headers={"X-Munsiq-Org": str(ORG), "X-Munsiq-BFF-Secret": "nope"},
        )
        none = await client.post("/api/v1/documents/authorize")
    assert wrong.status_code == 401
    assert none.status_code == 401


async def test_a_browser_cannot_mint_its_own_authorization() -> None:
    """The hard rule: with the BFF off, nobody chooses a tenant by asking."""
    async with client_for(bff_app(TRUSTED_BFF_ENABLED=False)) as client:
        response = await client.post(
            "/api/v1/documents/authorize",
            headers={"X-Munsiq-Org": str(ORG), "X-Munsiq-BFF-Secret": SECRET},
        )
    assert response.status_code == 501


async def test_upload_with_a_forged_token_is_refused() -> None:
    async with client_for(bff_app()) as client:
        response = await client.post("/api/v1/documents?upload_token=not.a-real-token", files=PDF)
    assert response.status_code == 403


async def test_upload_with_an_expired_token_is_refused() -> None:
    token = sign_upload_token(ORG, ttl_s=-1)
    async with client_for(bff_app()) as client:
        response = await client.post(f"/api/v1/documents?upload_token={token}", files=PDF)
    assert response.status_code == 403


async def test_a_page_token_is_refused_as_an_upload_token() -> None:
    token = sign_page_token(ORG, DOC, 1)
    async with client_for(bff_app()) as client:
        response = await client.post(f"/api/v1/documents?upload_token={token}", files=PDF)
    assert response.status_code == 403


async def test_a_bad_token_is_not_rescued_by_valid_bff_headers() -> None:
    """A present-but-bad token must not silently fall back to the header path."""
    async with client_for(bff_app()) as client:
        response = await client.post(
            "/api/v1/documents?upload_token=garbage",
            files=PDF,
            headers={"X-Munsiq-Org": str(ORG), "X-Munsiq-BFF-Secret": SECRET},
        )
    assert response.status_code == 403


async def test_upload_with_no_identity_is_refused() -> None:
    async with client_for(bff_app(TRUSTED_BFF_ENABLED=False)) as client:
        response = await client.post("/api/v1/documents", files=PDF)
    assert response.status_code == 501


async def test_an_upload_token_cannot_read_a_document() -> None:
    """Write access is not read access: GET /documents/{id} ignores the token."""
    token = sign_upload_token(ORG)
    async with client_for(bff_app(TRUSTED_BFF_ENABLED=False)) as client:
        response = await client.get(f"/api/v1/documents/{DOC}?upload_token={token}")
    assert response.status_code == 501


# --------------------------------------------------------------------------- #
# Through the real app and database
# --------------------------------------------------------------------------- #
class Recorder:
    """Stands in for the pipeline: records what was queued, does nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def __call__(self, org_id: uuid.UUID, document_id: uuid.UUID) -> None:
        self.calls.append((org_id, document_id))


@pytest_asyncio.fixture(scope="module")
async def tenant(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[uuid.UUID]:
    if not get_settings().DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    org_id, queue_id = uuid.uuid4(), uuid.uuid4()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s, s.begin():
        await s.execute(
            sql("INSERT INTO organizations (id, name) VALUES (:i, :n)"),
            {"i": org_id, "n": f"Upload {org_id}"},
        )
        await s.execute(
            sql("INSERT INTO queues (id, org_id, name) VALUES (:i, :o, 'AP')"),
            {"i": queue_id, "o": org_id},
        )
    previous = storage_mod._storage
    storage_mod._storage = LocalStorage(tmp_path_factory.mktemp("upload-storage"))
    try:
        yield org_id
    finally:
        storage_mod._storage = previous
        async with sessionmaker() as s, s.begin():
            await s.execute(sql("DELETE FROM organizations WHERE id = :i"), {"i": org_id})


def upload_url(org_id: uuid.UUID) -> str:
    return f"/api/v1/documents?upload_token={sign_upload_token(org_id)}"


def real_app() -> object:
    return create_app(Settings(DEBUG_ENDPOINTS=False, TRUSTED_BFF_ENABLED=False))


async def _row(document_id: uuid.UUID) -> object:
    async with get_sessionmaker()() as s:
        return (
            await s.execute(
                sql("SELECT org_id, filename, sha256, mime_type FROM documents WHERE id = :i"),
                {"i": document_id},
            )
        ).first()


@needs_db
async def test_upload_by_token_stores_the_document_under_the_tokens_tenant(
    tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(uploads_mod, "process_document", recorder)
    pdf = fixtures.build_pdf_without_attachment() + b"\n%unique-a"

    async with client_for(real_app()) as client:
        response = await client.post(
            upload_url(tenant),
            files={"file": (r"C:\fakepath\Invoice 1.pdf", pdf, "application/pdf")},
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "processing"
    assert body["duplicate"] is False
    assert body["filename"] == "Invoice 1.pdf", "the path prefix must not survive"

    row = await _row(uuid.UUID(body["document_id"]))
    assert row.org_id == tenant  # type: ignore[attr-defined]
    assert row.filename == "Invoice 1.pdf"  # type: ignore[attr-defined]
    assert bytes(row.sha256) == hashlib.sha256(pdf).digest()  # type: ignore[attr-defined]
    assert recorder.calls == [(tenant, uuid.UUID(body["document_id"]))]
    key = storage_mod.document_key(tenant, uuid.UUID(body["document_id"]), "original.pdf")
    assert storage_mod.get_storage().get(key) == pdf


@needs_db
async def test_the_document_is_committed_before_the_pipeline_is_started(
    tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug live testing found: uploads returned 202 and the pipeline then failed
    with "document not found for this tenant".

    FastAPI (>= 0.118) runs a yield-dependency's teardown — where a request
    session commits — AFTER the response and its background tasks. A handler that
    inserted through such a session and then queued the pipeline was racing its own
    commit, and losing: the task opened a fresh session, and the row was not there.

    So the check is made from where the pipeline stands: at the moment the task
    runs, in a session of its own, is the document visible? A recorder that only
    remembers its arguments cannot catch this, which is why the earlier tests did
    not.
    """
    seen: list[bool] = []

    async def pipeline_probe(org_id: uuid.UUID, document_id: uuid.UUID) -> None:
        async with session_scope(org_id) as fresh:
            found = await fresh.scalar(
                sql("SELECT count(*) FROM documents WHERE id = :d"), {"d": document_id}
            )
        seen.append(found == 1)

    monkeypatch.setattr(uploads_mod, "process_document", pipeline_probe)
    pdf = fixtures.build_pdf_without_attachment() + b"\n%unique-commit-order"

    async with client_for(real_app()) as client:
        response = await client.post(upload_url(tenant), files={"file": ("c.pdf", pdf)})

    assert response.status_code == 202, response.text
    assert seen == [True], "the pipeline started before the document was committed"


@needs_db
async def test_identical_reupload_returns_the_existing_document(
    tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug CLAUDE.md recorded: a resent invoice used to 500 and orphan a row."""
    recorder = Recorder()
    monkeypatch.setattr(uploads_mod, "process_document", recorder)
    pdf = fixtures.build_pdf_without_attachment() + b"\n%unique-b"

    async with client_for(real_app()) as client:
        first = await client.post(upload_url(tenant), files={"file": ("a.pdf", pdf)})
        again = await client.post(upload_url(tenant), files={"file": ("resent.pdf", pdf)})

    assert first.status_code == 202
    assert again.status_code == 200, again.text  # not 202, and never 500
    assert again.json()["document_id"] == first.json()["document_id"]
    assert again.json()["duplicate"] is True
    assert len(recorder.calls) == 1, "a second pipeline run was started"

    async with get_sessionmaker()() as s:
        count = await s.scalar(
            sql("SELECT count(*) FROM documents WHERE sha256 = :h AND org_id = :o"),
            {"h": hashlib.sha256(pdf).digest(), "o": tenant},
        )
    assert count == 1


@needs_db
async def test_a_failed_document_is_retried_when_uploaded_again(
    tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dedup must not make a failure permanent.

    Without this, re-uploading a file after fixing an outage (the model was down)
    would just hand back the failed row forever, and the only retry there is — the
    user trying again — would be a no-op.
    """
    recorder = Recorder()
    monkeypatch.setattr(uploads_mod, "process_document", recorder)
    pdf = fixtures.build_pdf_without_attachment() + b"\n%unique-c"

    async with client_for(real_app()) as client:
        first = await client.post(upload_url(tenant), files={"file": ("c.pdf", pdf)})
        document_id = uuid.UUID(first.json()["document_id"])

        # The pipeline fails, as it would with the model unreachable.
        await pipeline_mod._mark_failed(tenant, document_id, "InferenceError: connection refused")
        async with session_scope(tenant) as s:
            failed = (
                await s.execute(
                    sql(
                        "SELECT a.status::text AS status, v.message_en, v.message_ar "
                        "FROM annotations a JOIN validation_results v ON v.annotation_id = a.id "
                        "WHERE a.document_id = :d AND v.rule_code = 'PIPELINE_FAILED'"
                    ),
                    {"d": document_id},
                )
            ).first()
        assert failed is not None, "a failure with no annotation left no trace"
        assert failed.status == "failed"
        assert "connection refused" in failed.message_en
        assert "connection refused" in failed.message_ar
        assert "تعذّرت" in failed.message_ar

        retry = await client.post(upload_url(tenant), files={"file": ("c.pdf", pdf)})

    assert retry.status_code == 202, retry.text
    assert retry.json()["retried"] is True
    assert retry.json()["document_id"] == str(document_id)
    assert recorder.calls == [(tenant, document_id), (tenant, document_id)]
    async with session_scope(tenant) as s:
        leftover = await s.scalar(
            sql("SELECT count(*) FROM annotations WHERE document_id = :d"), {"d": document_id}
        )
    assert leftover == 0, "the old failed annotation should be cleared, not shown as current"


@needs_db
async def test_only_pdfs_are_accepted(tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder()
    monkeypatch.setattr(uploads_mod, "process_document", recorder)
    async with client_for(real_app()) as client:
        text_file = await client.post(
            upload_url(tenant), files={"file": ("notes.txt", b"just some text")}
        )
        # A lie in the Content-Type must not get a text file through.
        lying = await client.post(
            upload_url(tenant), files={"file": ("x.pdf", b"not a pdf", "application/pdf")}
        )
        empty = await client.post(upload_url(tenant), files={"file": ("e.pdf", b"")})
    assert text_file.status_code == 415
    assert lying.status_code == 415
    assert empty.status_code == 400
    assert recorder.calls == []


@needs_db
async def test_a_lost_insert_race_is_survivable(tenant: uuid.UUID) -> None:
    """UNIQUE(org_id, sha256) is the backstop for two identical concurrent uploads.

    The savepoint means the loser's IntegrityError does not poison its
    transaction: it can still look up the row that beat it.
    """
    sha = hashlib.sha256(b"race").digest()
    async with session_scope(tenant) as session:
        queue_id = await session.scalar(sql("SELECT id FROM queues LIMIT 1"))
        kwargs = {
            "org_id": tenant,
            "queue_id": queue_id,
            "storage_key": "x",
            "mime_type": "application/pdf",
            "filename": "race.pdf",
            "sha": sha,
        }
        assert await insert_document_row(session, document_id=uuid.uuid4(), **kwargs) is True  # type: ignore[arg-type]
        assert await insert_document_row(session, document_id=uuid.uuid4(), **kwargs) is False  # type: ignore[arg-type]
        # The transaction is still usable after the failure.
        assert (
            await session.scalar(
                sql("SELECT count(*) FROM documents WHERE sha256 = :h"), {"h": sha}
            )
            == 1
        )
