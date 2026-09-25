"""The three endpoints the validation workspace runs on, over real HTTP.

Covered here:

* ``GET /annotations/{id}`` — one round trip carrying fields, provenance, boxes,
  findings with BOTH languages, blockers and signed page URLs.
* ``PATCH /annotations/{id}/fields`` — a batch of correction events, logged and
  revalidated. The property that matters: correcting the value that caused a
  blocker CLEARS it, so confirm becomes possible.
* ``GET /pages/image`` — signature-authorized, cross-tenant replay rejected.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sql

from app.api.deps import get_current_org_id
from app.config import Settings, get_settings
from app.db.base import get_sessionmaker
from app.main import create_app
from app.services import storage as storage_mod
from app.services.signed_urls import sign_page_token
from app.services.storage import LocalStorage

pytestmark = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)

SCHEMA = {
    "name": "workspace test",
    "fields": [
        {"key": "invoice_number", "type": "string", "required": True},
        {"key": "seller_trn", "type": "string", "required": True},
        {"key": "subtotal", "type": "decimal", "required": True},
        {"key": "vat_amount", "type": "decimal", "required": True},
        {"key": "total_amount", "type": "decimal", "required": True},
    ],
}

# Deliberately broken: 45000 + 6750 = 51750, not 99999. The page text below
# contains 51750.00 too, so a reviewer correcting to it is grounded either way.
FIELDS = [
    (
        "invoice_number",
        "INV-001",
        "vlm",
        "auto_validated",
        {"page": 1, "x0": 0.1, "y0": 0.1, "x1": 0.3, "y1": 0.12},
    ),
    ("seller_trn", "310122393510003", "ubl_xml", "auto_validated", None),
    ("subtotal", "45000.00", "vlm", "auto_validated", None),
    ("vat_amount", "6750.00", "vlm", "auto_validated", None),
    ("total_amount", "99999.00", "vlm", "blocking", None),
]

PAGE_TEXT = "INV-001 45000.00 6750.00 51750.00 99999.00 310122393510003"


class Fx:
    def __init__(self) -> None:
        self.org_id = uuid.uuid4()
        self.queue_id = uuid.uuid4()
        self.schema_id = uuid.uuid4()
        self.document_id = uuid.uuid4()
        self.part_id = uuid.uuid4()
        self.annotation_id = uuid.uuid4()


@pytest_asyncio.fixture
async def fx(tmp_path) -> AsyncIterator[Fx]:  # type: ignore[no-untyped-def]
    f = Fx()
    previous = storage_mod._storage
    storage_mod._storage = LocalStorage(tmp_path / "storage")
    # A real byte payload so the image route has something to serve.
    storage_mod.get_storage().put(
        storage_mod.page_key(f.org_id, f.document_id, 1), b"RIFF----WEBPVP8 fake"
    )

    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await s.execute(
            sql("INSERT INTO organizations (id, name) VALUES (:i, :n)"),
            {"i": f.org_id, "n": f"Workspace {f.org_id}"},
        )
        await s.execute(
            sql("INSERT INTO queues (id, org_id, name) VALUES (:i, :o, 'AP')"),
            {"i": f.queue_id, "o": f.org_id},
        )
        await s.execute(
            sql(
                "INSERT INTO extraction_schemas (id, org_id, queue_id, version, definition) "
                "VALUES (:i, :o, :q, 1, CAST(:d AS jsonb))"
            ),
            {
                "i": f.schema_id,
                "o": f.org_id,
                "q": f.queue_id,
                "d": json.dumps(SCHEMA),
            },
        )
        await s.execute(
            sql(
                "INSERT INTO documents (id, org_id, queue_id, source, page_count, "
                "has_embedded_ubl) VALUES (:i, :o, :q, 'upload', 1, false)"
            ),
            {"i": f.document_id, "o": f.org_id, "q": f.queue_id},
        )
        await s.execute(
            sql(
                "INSERT INTO pages (org_id, document_id, page_number, image_key, "
                "width_px, height_px, ocr_text, text_source) "
                "VALUES (:o, :d, 1, :k, 595, 842, :t, 'text_layer')"
            ),
            {
                "o": f.org_id,
                "d": f.document_id,
                "k": storage_mod.page_key(f.org_id, f.document_id, 1),
                "t": PAGE_TEXT,
            },
        )
        await s.execute(
            sql(
                "INSERT INTO document_parts (id, org_id, document_id, part_index) "
                "VALUES (:i, :o, :d, 0)"
            ),
            {"i": f.part_id, "o": f.org_id, "d": f.document_id},
        )
        await s.execute(
            sql(
                "INSERT INTO annotations (id, org_id, document_id, part_id, schema_id, "
                "status, blockers) VALUES (:i, :o, :d, :p, :s, 'to_review', "
                "CAST(:b AS jsonb))"
            ),
            {
                "i": f.annotation_id,
                "o": f.org_id,
                "d": f.document_id,
                "p": f.part_id,
                "s": f.schema_id,
                "b": json.dumps(["GRAND_TOTAL_MISMATCH"]),
            },
        )
        for key, value, source, state, bbox in FIELDS:
            await s.execute(
                sql(
                    "INSERT INTO extracted_fields (org_id, annotation_id, field_key, "
                    "value_extracted, source, validation_state, confidence, bbox) "
                    "VALUES (:o, :a, :k, :v, :src, :st, 0.95, CAST(:b AS jsonb))"
                ),
                {
                    "o": f.org_id,
                    "a": f.annotation_id,
                    "k": key,
                    "v": value,
                    "src": source,
                    "st": state,
                    "b": json.dumps(bbox) if bbox else None,
                },
            )
        await s.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, "
                "severity, message_ar, message_en, field_key, passed) VALUES "
                "(:o, :a, 'GRAND_TOTAL_MISMATCH', 'error', :ar, :en, 'total_amount', false)"
            ),
            {
                "o": f.org_id,
                "a": f.annotation_id,
                "ar": "المجموع قبل الضريبة مضافاً إليه الضريبة لا يساوي الإجمالي.",
                "en": "Subtotal plus VAT does not equal the total.",
            },
        )
    try:
        yield f
    finally:
        storage_mod._storage = previous
        async with sm() as s, s.begin():
            await s.execute(sql("DELETE FROM organizations WHERE id = :i"), {"i": f.org_id})


def client_as(org_id: uuid.UUID) -> AsyncClient:
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    app.dependency_overrides[get_current_org_id] = lambda: org_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# GET — one round trip
# --------------------------------------------------------------------------- #
async def test_detail_returns_everything_the_workspace_needs(fx: Fx) -> None:
    async with client_as(fx.org_id) as c:
        r = await c.get(f"/api/v1/annotations/{fx.annotation_id}")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "to_review"
    assert len(body["fields"]) == len(FIELDS)
    assert len(body["pages"]) == 1
    assert body["findings"], "findings must arrive with the annotation"
    assert body["blockers"] == ["GRAND_TOTAL_MISMATCH"]


async def test_blockers_arrive_without_a_second_call(fx: Fx) -> None:
    """A reviewer must never wait on another request to learn why it is blocked."""
    async with client_as(fx.org_id) as c:
        body = (await c.get(f"/api/v1/annotations/{fx.annotation_id}")).json()

    assert body["blockers"] == ["GRAND_TOTAL_MISMATCH"]
    finding = next(f for f in body["findings"] if f["rule_code"] == "GRAND_TOTAL_MISMATCH")
    assert finding["passed"] is False
    assert finding["severity"] == "error"
    assert finding["field_key"] == "total_amount"


async def test_findings_carry_both_languages(fx: Fx) -> None:
    """The UI is bilingual; a finding with only English is unusable in Arabic."""
    async with client_as(fx.org_id) as c:
        body = (await c.get(f"/api/v1/annotations/{fx.annotation_id}")).json()

    finding = next(f for f in body["findings"] if f["rule_code"] == "GRAND_TOTAL_MISMATCH")
    assert finding["message_en"].strip()
    assert finding["message_ar"].strip()
    assert any("؀" <= ch <= "ۿ" for ch in finding["message_ar"])


async def test_two_findings_of_the_same_rule_have_distinct_ids(fx: Fx) -> None:
    """One rule firing on two fields — the real shape that collided as a React
    key when only rule_code was used to identify a finding on the wire."""
    async with get_sessionmaker()() as s, s.begin():
        await s.execute(
            sql(
                "INSERT INTO validation_results (org_id, annotation_id, rule_code, "
                "severity, message_ar, message_en, field_key, passed) VALUES "
                "(:o, :a, 'GRAND_TOTAL_MISMATCH', 'error', :ar, :en, 'subtotal', false)"
            ),
            {"o": fx.org_id, "a": fx.annotation_id, "ar": "رسالة ثانية.", "en": "Second message."},
        )

    async with client_as(fx.org_id) as c:
        body = (await c.get(f"/api/v1/annotations/{fx.annotation_id}")).json()

    matching = [f for f in body["findings"] if f["rule_code"] == "GRAND_TOTAL_MISMATCH"]
    assert len(matching) == 2
    assert {f["field_key"] for f in matching} == {"total_amount", "subtotal"}
    ids = [f["id"] for f in matching]
    assert all(ids)
    assert len(set(ids)) == 2


async def test_provenance_and_confidence_survive_the_wire(fx: Fx) -> None:
    """The provenance badge is the core differentiator — its inputs must arrive."""
    async with client_as(fx.org_id) as c:
        body = (await c.get(f"/api/v1/annotations/{fx.annotation_id}")).json()

    by_key = {f["field_key"]: f for f in body["fields"]}
    assert by_key["seller_trn"]["source"] == "ubl_xml"
    assert by_key["invoice_number"]["source"] == "vlm"
    assert by_key["invoice_number"]["confidence"] is not None
    assert by_key["total_amount"]["validation_state"] == "blocking"


async def test_bboxes_are_normalized_and_ready_for_the_svg_overlay(fx: Fx) -> None:
    async with client_as(fx.org_id) as c:
        body = (await c.get(f"/api/v1/annotations/{fx.annotation_id}")).json()

    bbox = next(f for f in body["fields"] if f["field_key"] == "invoice_number")["bbox"]
    assert bbox is not None
    assert bbox["page"] == 1
    for key in ("x0", "y0", "x1", "y1"):
        assert 0.0 <= bbox[key] <= 1.0


async def test_pages_carry_signed_image_urls(fx: Fx) -> None:
    async with client_as(fx.org_id) as c:
        body = (await c.get(f"/api/v1/annotations/{fx.annotation_id}")).json()

    page = body["pages"][0]
    assert page["image_url"].startswith("/api/v1/pages/image?token=")
    assert str(fx.org_id) not in page["image_url"], "tenant must not be legible in the URL"
    assert page["text_source"] == "text_layer"


async def test_another_tenant_cannot_read_the_annotation(fx: Fx) -> None:
    async with client_as(uuid.uuid4()) as c:
        r = await c.get(f"/api/v1/annotations/{fx.annotation_id}")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# PATCH — corrections and revalidation
# --------------------------------------------------------------------------- #
async def test_correcting_the_blocking_value_clears_the_blocker(fx: Fx) -> None:
    """THE property this endpoint exists for.

    Without revalidation the stale failing row would survive and the reviewer
    could never confirm, no matter what they fixed.
    """
    async with client_as(fx.org_id) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "total_amount", "new_value": "51750.00"}]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["applied"] == 1
        assert "GRAND_TOTAL_MISMATCH" not in r.json()["blockers"]

        confirm = await c.post(f"/api/v1/annotations/{fx.annotation_id}/confirm")

    assert confirm.status_code == 200, confirm.text


async def test_a_wrong_correction_keeps_the_blocker(fx: Fx) -> None:
    """Revalidation is real, not a reset: a still-wrong value stays blocked."""
    async with client_as(fx.org_id) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "total_amount", "new_value": "88888.00"}]},
        )
        assert "GRAND_TOTAL_MISMATCH" in r.json()["blockers"]
        # Revalidation deletes and re-inserts every row, so a finding's id from
        # before a correction is never reused for the one after it.
        finding = next(f for f in r.json()["findings"] if f["rule_code"] == "GRAND_TOTAL_MISMATCH")
        assert finding["id"]
        confirm = await c.post(f"/api/v1/annotations/{fx.annotation_id}/confirm")

    assert confirm.status_code == 409


async def test_revalidation_turns_a_green_null_required_field_amber(fx: Fx) -> None:
    """The real invoice's shape: a required field extracted as null and stored
    auto_validated. Revalidation reads `required` from the annotation's own
    schema, flags it, and moves it to review_suggested — without blocking."""
    async with get_sessionmaker()() as s, s.begin():
        await s.execute(
            sql(
                "UPDATE extracted_fields SET value_extracted = NULL, "
                "validation_state = 'auto_validated' "
                "WHERE annotation_id = :a AND field_key = 'subtotal'"
            ),
            {"a": fx.annotation_id},
        )

    async with client_as(fx.org_id) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "total_amount", "new_value": "51750.00"}]},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    subtotal = next(f for f in body["fields"] if f["field_key"] == "subtotal")
    assert subtotal["validation_state"] == "review_suggested"
    missing = [
        f
        for f in body["findings"]
        if f["rule_code"] == "REQUIRED_FIELD_MISSING" and not f["passed"]
    ]
    assert [(f["field_key"], f["severity"]) for f in missing] == [("subtotal", "warning")]
    assert missing[0]["message_ar"] and missing[0]["message_en"]
    assert "REQUIRED_FIELD_MISSING" not in body["blockers"]


async def test_correction_is_logged_for_the_flywheel(fx: Fx) -> None:
    """field_corrections is append-only and feeds the correction-rate metrics."""
    async with client_as(fx.org_id) as c:
        await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "total_amount", "new_value": "51750.00"}]},
        )

    async with get_sessionmaker()() as s, s.begin():
        row = (
            await s.execute(
                sql(
                    "SELECT field_key, old_value, new_value, action FROM field_corrections "
                    "WHERE annotation_id = :a"
                ),
                {"a": fx.annotation_id},
            )
        ).one()

    assert row.field_key == "total_amount"
    assert row.old_value == "99999.00"
    assert row.new_value == "51750.00"
    assert row.action == "edit"


async def test_a_batch_applies_every_event(fx: Fx) -> None:
    """The payload is a batch of events, not one field at a time."""
    async with client_as(fx.org_id) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={
                "events": [
                    {"field_key": "subtotal", "new_value": "45000.00"},
                    {"field_key": "vat_amount", "new_value": "6750.00"},
                    {"field_key": "total_amount", "new_value": "51750.00"},
                ]
            },
        )

    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 3


async def test_a_correction_marks_the_field_human_sourced(fx: Fx) -> None:
    """Provenance must reflect that a person, not a model, chose this value."""
    async with client_as(fx.org_id) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "total_amount", "new_value": "51750.00"}]},
        )

    field = next(f for f in r.json()["fields"] if f["field_key"] == "total_amount")
    assert field["source"] == "human"
    assert field["value_final"] == "51750.00"
    assert field["value_extracted"] == "99999.00", "the original must be preserved"


async def test_unknown_field_is_rejected_rather_than_invented(fx: Fx) -> None:
    async with client_as(fx.org_id) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "not_a_field", "new_value": "x"}]},
        )
    assert r.status_code == 422


async def test_empty_batch_is_rejected(fx: Fx) -> None:
    async with client_as(fx.org_id) as c:
        r = await c.patch(f"/api/v1/annotations/{fx.annotation_id}/fields", json={"events": []})
    assert r.status_code == 422


async def test_confirmed_annotation_can_no_longer_be_edited(fx: Fx) -> None:
    async with get_sessionmaker()() as s, s.begin():
        await s.execute(
            sql("UPDATE annotations SET status = 'confirmed' WHERE id = :i"),
            {"i": fx.annotation_id},
        )

    async with client_as(fx.org_id) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "total_amount", "new_value": "1.00"}]},
        )
    assert r.status_code == 409


async def test_another_tenant_cannot_patch_our_fields(fx: Fx) -> None:
    async with client_as(uuid.uuid4()) as c:
        r = await c.patch(
            f"/api/v1/annotations/{fx.annotation_id}/fields",
            json={"events": [{"field_key": "total_amount", "new_value": "1.00"}]},
        )
    assert r.status_code == 404

    async with get_sessionmaker()() as s, s.begin():
        value = await s.scalar(
            sql(
                "SELECT value_final FROM extracted_fields WHERE annotation_id = :a "
                "AND field_key = 'total_amount'"
            ),
            {"a": fx.annotation_id},
        )
    assert value is None, "another tenant modified our field"


# --------------------------------------------------------------------------- #
# GET /pages/image
# --------------------------------------------------------------------------- #
async def test_a_valid_token_serves_the_image(fx: Fx) -> None:
    token = sign_page_token(fx.org_id, fx.document_id, 1)
    async with client_as(fx.org_id) as c:
        r = await c.get(f"/api/v1/pages/image?token={token}")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/webp"
    assert "private" in r.headers["cache-control"]
    assert r.content == b"RIFF----WEBPVP8 fake"


async def test_a_token_for_another_tenant_cannot_read_our_page(fx: Fx) -> None:
    """The signature covers the tenant, so a foreign token resolves elsewhere.

    It must not return this tenant's bytes under any circumstances.
    """
    foreign = sign_page_token(uuid.uuid4(), fx.document_id, 1)
    async with client_as(fx.org_id) as c:
        r = await c.get(f"/api/v1/pages/image?token={foreign}")

    assert r.status_code == 404
    assert r.content != b"RIFF----WEBPVP8 fake"


async def test_a_tampered_token_is_forbidden(fx: Fx) -> None:
    token = sign_page_token(fx.org_id, fx.document_id, 1)
    encoded, _, signature = token.partition(".")
    async with client_as(fx.org_id) as c:
        r = await c.get(f"/api/v1/pages/image?token={encoded}.{'A' * len(signature)}")

    assert r.status_code == 403


async def test_an_expired_token_is_forbidden(fx: Fx) -> None:
    token = sign_page_token(fx.org_id, fx.document_id, 1, ttl_s=-1)
    async with client_as(fx.org_id) as c:
        r = await c.get(f"/api/v1/pages/image?token={token}")

    assert r.status_code == 403


async def test_the_image_route_needs_no_session(fx: Fx) -> None:
    """An <img src> carries no auth, so the token alone must suffice."""
    token = sign_page_token(fx.org_id, fx.document_id, 1)
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    # No dependency override: get_current_org_id would raise 501 if consulted.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/v1/pages/image?token={token}")

    assert r.status_code == 200, r.text
