"""Workspace-facing API additions from the design pass.

* UBL values are grounded on text-layer pages, so the review UI can outline
  where a signed value is printed. Provenance is untouched: still ubl_xml,
  still confidence 1.0, still auto_validated.
* GET /annotations/{id} returns the schema's labels and order, so the UI shows
  "Invoice number" / "رقم الفاتورة" instead of `invoice_number`, and hardcodes
  neither.
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
from app.services import pipeline as pipeline_mod
from app.services import storage as storage_mod
from app.services.storage import LocalStorage
from tests import fixtures

pytestmark = pytest.mark.skipif(
    not get_settings().DATABASE_URL,
    reason="DATABASE_URL not set — see backend/.env.example",
)

SCHEMA = {
    "name": "design pass",
    "fields": [
        {
            "key": "invoice_number",
            "type": "string",
            "label_en": "Invoice number",
            "label_ar": "رقم الفاتورة",
            "required": True,
        },
        {
            "key": "seller_trn",
            "type": "string",
            "label_en": "Seller VAT number",
            "label_ar": "الرقم الضريبي للبائع",
            "required": True,
        },
        {
            "key": "subtotal",
            "type": "decimal",
            "label_en": "Subtotal",
            "label_ar": "المجموع قبل الضريبة",
        },
        {
            "key": "total_amount",
            "type": "decimal",
            "label_en": "Total",
            "label_ar": "الإجمالي",
            "required": True,
        },
    ],
}


class NoModel:
    """Step Zero must answer on its own; any model call is a test failure."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def chat(self, **kwargs: object) -> None:
        raise AssertionError("the model must not be called when UBL is present")


@pytest_asyncio.fixture
async def tenant(tmp_path, monkeypatch) -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:  # type: ignore[no-untyped-def]
    org_id, queue_id = uuid.uuid4(), uuid.uuid4()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s, s.begin():
        await s.execute(
            sql("INSERT INTO organizations (id, name) VALUES (:i, :n)"),
            {"i": org_id, "n": f"Design Pass {org_id}"},
        )
        await s.execute(
            sql("INSERT INTO queues (id, org_id, name) VALUES (:i, :o, 'AP')"),
            {"i": queue_id, "o": org_id},
        )
        await s.execute(
            sql(
                "INSERT INTO extraction_schemas (org_id, queue_id, version, definition) "
                "VALUES (:o, :q, 1, CAST(:d AS jsonb))"
            ),
            {"o": org_id, "q": queue_id, "d": json.dumps(SCHEMA, ensure_ascii=False)},
        )

    previous = storage_mod._storage
    storage_mod._storage = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(pipeline_mod, "OllamaClient", NoModel)
    try:
        yield org_id, queue_id
    finally:
        storage_mod._storage = previous
        async with sessionmaker() as s, s.begin():
            await s.execute(sql("DELETE FROM organizations WHERE id = :i"), {"i": org_id})


async def _process(org_id: uuid.UUID, queue_id: uuid.UUID) -> uuid.UUID:
    document_id = uuid.uuid4()
    key = storage_mod.document_key(org_id, document_id, "original.pdf")
    storage_mod.get_storage().put(key, fixtures.build_pdf_with_text_layer_and_ubl())
    async with get_sessionmaker()() as s, s.begin():
        await s.execute(
            sql(
                "INSERT INTO documents (id, org_id, queue_id, storage_key, source) "
                "VALUES (:i, :o, :q, :k, 'upload')"
            ),
            {"i": document_id, "o": org_id, "q": queue_id, "k": key},
        )
    outcome = await pipeline_mod.process_document(org_id, document_id)
    assert outcome.error is None, outcome.error
    assert outcome.annotation_id is not None
    return outcome.annotation_id


def client_as(org_id: uuid.UUID) -> AsyncClient:
    app = create_app(Settings(DEBUG_ENDPOINTS=False))
    app.dependency_overrides[get_current_org_id] = lambda: org_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# UBL grounding
# --------------------------------------------------------------------------- #
async def test_ubl_values_are_grounded_on_a_text_layer_page(tenant) -> None:  # type: ignore[no-untyped-def]
    """The empty-overlay problem at its source: signed values now have boxes."""
    org_id, queue_id = tenant
    annotation_id = await _process(org_id, queue_id)

    async with client_as(org_id) as client:
        body = (await client.get(f"/api/v1/annotations/{annotation_id}")).json()

    by_key = {f["field_key"]: f for f in body["fields"]}
    for key in ("invoice_number", "seller_trn", "total_amount"):
        bbox = by_key[key]["bbox"]
        assert bbox is not None, f"{key} is printed on the page but was not grounded"
        for edge in ("x0", "y0", "x1", "y1"):
            assert 0.0 <= bbox[edge] <= 1.0


async def test_grounding_does_not_change_ubl_provenance(tenant) -> None:  # type: ignore[no-untyped-def]
    """A box says where a value is, never how much to trust it."""
    org_id, queue_id = tenant
    annotation_id = await _process(org_id, queue_id)

    async with client_as(org_id) as client:
        body = (await client.get(f"/api/v1/annotations/{annotation_id}")).json()

    for field in body["fields"]:
        if field["value_extracted"] is None:
            continue
        assert field["source"] == "ubl_xml"
        assert float(field["confidence"]) == 1.0
        assert field["validation_state"] == "auto_validated"


# --------------------------------------------------------------------------- #
# Schema labels
# --------------------------------------------------------------------------- #
async def test_detail_returns_schema_labels_in_schema_order(tenant) -> None:  # type: ignore[no-untyped-def]
    org_id, queue_id = tenant
    annotation_id = await _process(org_id, queue_id)

    async with client_as(org_id) as client:
        body = (await client.get(f"/api/v1/annotations/{annotation_id}")).json()

    schema = body["schema_fields"]
    assert [s["key"] for s in schema] == [f["key"] for f in SCHEMA["fields"]]
    first = schema[0]
    assert first["label_en"] == "Invoice number"
    assert first["label_ar"] == "رقم الفاتورة"
    assert first["required"] is True
    assert schema[3]["type"] == "decimal"
