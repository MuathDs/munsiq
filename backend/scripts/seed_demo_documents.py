"""Seed the two demo documents the README screenshots show.

    A  COMPLIANT   text-layer PDF carrying its signed UBL attachment. Step Zero
                   answers from the XML, the model is never called, every value
                   is grounded on the page, line items come from the XML.

    B  BROKEN      text-layer PDF with no attachment and a printed total that
                   does not add up. The model extracts it (Ollama, whatever
                   INFERENCE_MODEL names), grounding gives each value a box and
                   a confidence, and the arithmetic rule blocks confirmation.

Both land in 'to_review'. Both invoices are synthetic: the numbers, names and
VAT registrations are invented, so nothing real is committed or stored.

Run after scripts.seed_demo (which creates the org, queue and schema):

    backend/.venv/Scripts/python.exe -m scripts.seed_demo_documents
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from pypdf import PdfReader, PdfWriter
from sqlalchemy import text as sql

from app.db.base import get_sessionmaker
from app.services import pipeline as pipeline_mod
from app.services import storage as storage_mod
from scripts.seed_demo import DEMO_ORG_NAME
from tests import fixtures

FONT = r"C:\Windows\Fonts\arial.ttf"

# A: the compliant invoice. The printed figures match the signed XML exactly,
# formatted the way a supplier's system prints them (thousands separators).
COMPLIANT_LINES: list[tuple[str, int]] = [
    ("TAX INVOICE", 20),
    ("Invoice No: SA-2026-0334", 13),
    ("Issue Date: 2026-02-10", 13),
    ("", 8),
    ("Seller: Al Jazeera Industrial Maintenance", 13),
    ("VAT No: 310122393510003", 13),
    ("", 8),
    ("Buyer: Jubail Maintenance Services Ltd.", 13),
    ("VAT No: 311111111110003", 13),
    ("", 12),
    ("Centrifugal pump          2 x 20,000.00      40,000.00", 12),
    ("Ball valve 6 inch         4 x  1,330.00       5,320.00", 12),
    ("", 10),
    ("Subtotal (excl. VAT):                       45,320.00", 13),
    ("VAT 15%:                                     6,798.00", 13),
    ("Total (incl. VAT):                          52,118.00 SAR", 14),
]

# B: the broken one. 18,400.00 + 2,760.00 is 21,160.00, and the invoice claims
# 21,610.00 — two digits transposed, exactly the kind of error a human eye slides
# over and GRAND_TOTAL_MISMATCH does not. Everything else is consistent, so the
# blocker is unambiguous.
BROKEN_LINES: list[tuple[str, int]] = [
    ("TAX INVOICE", 20),
    ("Invoice No: EPS-2026-1187", 13),
    ("Issue Date: 2026-03-04", 13),
    ("PO No: 4500012345", 13),
    ("", 8),
    ("Seller: Eastern Province Steel Trading Co.", 13),
    ("VAT No: 300475318510003", 13),
    ("", 8),
    ("Buyer: Jubail Maintenance Services Ltd.", 13),
    ("VAT No: 311111111110003", 13),
    ("", 12),
    ("Carbon steel pipe 6 inch  12 x  1,250.00     15,000.00", 12),
    ("Flange gasket kit          8 x    425.00      3,400.00", 12),
    ("", 10),
    ("Subtotal (excl. VAT):                       18,400.00", 13),
    ("VAT 15%:                                     2,760.00", 13),
    ("Total (incl. VAT):                          21,610.00 SAR", 14),
]


def build_pdf(lines: list[tuple[str, int]], *, ubl: bytes | None) -> bytes:
    """Render the page, then attach the UBL when there is one."""
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=595, height=842)
    y = 90
    for body, size in lines:
        if body:
            page.insert_text((60, y), body, fontsize=size, fontfile=FONT, fontname="F0")
        y += size + 10
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()

    writer = PdfWriter()
    for rendered in PdfReader(io.BytesIO(buffer.getvalue())).pages:
        writer.add_page(rendered)
    if ubl is not None:
        writer.add_attachment("invoice.xml", ubl)
    # Invisible, byte-level uniqueness. documents carries UNIQUE(org_id, sha256),
    # and a byte-identical re-upload currently crashes the pipeline (see "Known
    # issues" in CLAUDE.md), so re-seeding produces fresh bytes rather than a
    # collision. The rendered page is identical either way.
    writer.add_metadata({"/Subject": f"munsiq-demo-{uuid.uuid4()}"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def seed(org_id: uuid.UUID, queue_id: uuid.UUID, label: str, pdf: bytes) -> uuid.UUID:
    document_id = uuid.uuid4()
    key = storage_mod.document_key(org_id, document_id, "original.pdf")
    storage_mod.get_storage().put(key, pdf)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            sql(
                "INSERT INTO documents (id, org_id, queue_id, storage_key, source, mime_type) "
                "VALUES (:i, :o, :q, :k, 'upload', 'application/pdf')"
            ),
            {"i": document_id, "o": org_id, "q": queue_id, "k": key},
        )

    started = time.perf_counter()
    outcome = await pipeline_mod.process_document(org_id, document_id)
    elapsed = time.perf_counter() - started
    if outcome.error:
        raise SystemExit(f"{label}: pipeline failed — {outcome.error}")
    assert outcome.annotation_id is not None

    async with get_sessionmaker()() as session:
        stats = (
            await session.execute(
                sql(
                    "SELECT count(*) AS total, "
                    "count(*) FILTER (WHERE bbox IS NOT NULL) AS boxed, "
                    "count(*) FILTER (WHERE row_index IS NOT NULL) AS line_cells, "
                    "count(*) FILTER (WHERE validation_state = 'blocking') AS blocking "
                    "FROM extracted_fields WHERE annotation_id = :a"
                ),
                {"a": outcome.annotation_id},
            )
        ).first()
        latency = await session.scalar(
            sql("SELECT latency_ms FROM annotations WHERE id = :a"),
            {"a": outcome.annotation_id},
        )

    print(f"\n{label}")
    print(f"  annotation      {outcome.annotation_id}")
    print(f"  status          {outcome.status}")
    print(f"  embedded UBL    {outcome.has_embedded_ubl}")
    print(f"  model called    {outcome.model_called}" + (f" ({latency} ms)" if latency else ""))
    print(f"  fields          {stats.total} ({stats.line_cells} line-item cells)")
    print(f"  grounded        {stats.boxed}/{stats.total} have a bounding box")
    print(f"  blocking fields {stats.blocking}")
    print(f"  blockers        {outcome.blockers or 'none'}")
    print(f"  pipeline        {elapsed:.1f}s wall clock")
    return outcome.annotation_id


async def main() -> int:
    async with get_sessionmaker()() as session:
        org_id = await session.scalar(
            sql("SELECT id FROM organizations WHERE name = :n"), {"n": DEMO_ORG_NAME}
        )
        if org_id is None:
            raise SystemExit("no demo org — run `python -m scripts.seed_demo` first")
        queue_id = await session.scalar(
            sql("SELECT id FROM queues WHERE org_id = :o ORDER BY created_at LIMIT 1"),
            {"o": org_id},
        )

    compliant = await seed(
        org_id,
        queue_id,
        "A — compliant (signed UBL, no model)",
        build_pdf(COMPLIANT_LINES, ubl=fixtures.build_ubl_xml()),
    )
    broken = await seed(
        org_id,
        queue_id,
        "B — broken (no UBL, model extracted, total does not add up)",
        build_pdf(BROKEN_LINES, ubl=None),
    )

    print("\nReview them at:")
    for label, annotation_id in (("A", compliant), ("B", broken)):
        for locale in ("en", "ar"):
            print(f"  {label} {locale}  http://localhost:3000/{locale}/annotations/{annotation_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
