"""Ground truth for real invoices, and text-vs-vision scoring against it.

    backend/.venv/Scripts/python.exe -m scripts.eval_set template <document_id> \
        > samples/eval/<document_id>.json
    # ...fill in the 9 fields by hand, reading the real PDF in the review UI...
    backend/.venv/Scripts/python.exe -m scripts.eval_set load <org_id> <name> samples/eval/
    backend/.venv/Scripts/python.exe -m scripts.eval_set score <org_id> <name> --mode text
    backend/.venv/Scripts/python.exe -m scripts.eval_set score <org_id> <name> --mode vision
    backend/.venv/Scripts/python.exe -m scripts.eval_set score <org_id> <name> --qr on

Reuses the eval_sets / ground_truth_fields tables that already exist in the
Phase 2 schema (app/db/models/evaluation.py) — this is the tooling that was
missing to populate them, not new storage.

Nine fields, matching the ones the user's own manual vision test on the contractor
invoice was scored against: invoice_number, issue_date, seller_name,
seller_trn, buyer_name, buyer_trn, subtotal, vat_amount, total_amount.

`score` applies the pipeline's deterministic step after the model (a copied
receipt subtotal is derived; with ``--qr on`` the ZATCA QR's five fields replace
the model's), so it scores what a reviewer would be shown. The generated test
invoices on disk are scored the same way by scripts/benchmark.py, which takes
the same ``--qr`` switch.

`template` only prints a shape — it takes a document_id but reads nothing.
`load` and `score` are the only commands that touch a real PDF or its fields,
and `score` prints COUNTS ONLY: never an expected or extracted value. See
CLAUDE.md, "don't store or print the invoice's contents beyond what's needed".

samples/eval/ is git-ignored (see .gitignore): the ground-truth JSON files ARE
the invoice's fields, same reasoning as the PDFs themselves.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from sqlalchemy import text as sql

from app.config import get_settings
from app.db.session import session_scope
from app.services import storage as storage_mod
from app.services.extraction.client import OllamaClient
from app.services.extraction.prompts import parse_schema
from app.services.extraction.qr_values import apply_deterministic_sources
from app.services.extraction.routing import ExtractionMode, resolve_mode
from app.services.extraction.runner import run_extraction
from app.services.pagetext import extract_page_text
from app.services.qr import find_zatca_qr
from app.services.raster import rasterize_pages
from scripts.benchmark import Report, render
from scripts.seed_demo import INVOICE_SCHEMA

NINE_FIELDS: tuple[str, ...] = (
    "invoice_number",
    "issue_date",
    "seller_name",
    "seller_trn",
    "buyer_name",
    "buyer_trn",
    "subtotal",
    "vat_amount",
    "total_amount",
)


def _template(document_id: str) -> dict[str, object]:
    return {"document_id": document_id, "fields": dict.fromkeys(NINE_FIELDS)}


async def _load(org_id: uuid.UUID, eval_set_name: str, directory: Path) -> None:
    async with session_scope(org_id) as session:
        eval_set_id = await session.scalar(
            sql("SELECT id FROM eval_sets WHERE org_id = :o AND name = :n"),
            {"o": org_id, "n": eval_set_name},
        )
        if eval_set_id is None:
            eval_set_id = await session.scalar(
                sql(
                    "INSERT INTO eval_sets (org_id, name) VALUES (:o, :n) RETURNING id"
                ),
                {"o": org_id, "n": eval_set_name},
            )

        files = sorted(directory.glob("*.json"))
        if not files:
            raise SystemExit(f"no *.json ground-truth files in {directory}")

        field_count = 0
        for path in files:
            raw = json.loads(path.read_text(encoding="utf-8"))
            document_id = uuid.UUID(str(raw["document_id"]))
            # Re-loading the same document is a correction, not an accumulation:
            # drop its old rows first rather than relying on ON CONFLICT, which
            # a NULL row_index (every field here is a header field) would not
            # reliably match.
            await session.execute(
                sql(
                    "DELETE FROM ground_truth_fields "
                    "WHERE eval_set_id = :e AND document_id = :d"
                ),
                {"e": eval_set_id, "d": document_id},
            )
            for key, value in raw["fields"].items():
                await session.execute(
                    sql(
                        "INSERT INTO ground_truth_fields "
                        "(org_id, eval_set_id, document_id, field_key, expected_value) "
                        "VALUES (:o, :e, :d, :k, :v)"
                    ),
                    {"o": org_id, "e": eval_set_id, "d": document_id, "k": key, "v": value},
                )
                field_count += 1
        print(f"loaded {field_count} ground-truth fields from {len(files)} file(s) "
              f"into eval set {eval_set_name!r}")


async def _score(
    org_id: uuid.UUID, eval_set_name: str, mode: ExtractionMode, *, qr: bool = False
) -> None:
    settings = get_settings()
    fields = parse_schema(INVOICE_SCHEMA)
    text_client = OllamaClient()
    vision_client = None
    if mode != "text":
        vision_client = OllamaClient(
            base_url=settings.VISION_INFERENCE_BASE_URL or settings.INFERENCE_BASE_URL,
            model=settings.VISION_MODEL,
            num_ctx=settings.VISION_NUM_CTX,
        )
    storage = storage_mod.get_storage()

    async with session_scope(org_id) as session:
        eval_set_id = await session.scalar(
            sql("SELECT id FROM eval_sets WHERE org_id = :o AND name = :n"),
            {"o": org_id, "n": eval_set_name},
        )
        if eval_set_id is None:
            raise SystemExit(f"no eval set named {eval_set_name!r} for this org")

        rows = (
            await session.execute(
                sql(
                    "SELECT g.document_id, g.field_key, g.expected_value, d.storage_key "
                    "FROM ground_truth_fields g JOIN documents d ON d.id = g.document_id "
                    "WHERE g.eval_set_id = :e"
                ),
                {"e": eval_set_id},
            )
        ).all()
    if not rows:
        raise SystemExit(f"eval set {eval_set_name!r} has no ground truth loaded")

    expected_by_doc: dict[uuid.UUID, dict[str, str | None]] = {}
    storage_key_by_doc: dict[uuid.UUID, str] = {}
    for r in rows:
        expected_by_doc.setdefault(r.document_id, {})[r.field_key] = r.expected_value
        storage_key_by_doc[r.document_id] = r.storage_key

    report = Report(label=f"{eval_set_name}-{mode}-qr-{'on' if qr else 'off'}")
    qr_read = 0
    for document_id, storage_key in storage_key_by_doc.items():
        pdf_bytes = storage.get(storage_key)
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            pages = [extract_page_text(p, i) for i, p in enumerate(doc, start=1)]

        resolved, vision_pages = resolve_mode(mode, pages)
        page_images = None
        if vision_pages:
            rasters = rasterize_pages(
                pdf_bytes,
                vision_pages,
                dpi=settings.VISION_RASTER_DPI,
                quality=settings.WEBP_QUALITY,
            )
            page_images = [r.data for r in sorted(rasters, key=lambda r: r.page_number)]

        if resolved == "vision":
            assert vision_client is not None, "'vision' only comes back when mode != 'text'"
            client = vision_client
        else:
            client = text_client

        result = run_extraction(
            client=client,
            fields=fields,
            pages=pages,
            page_images=page_images,
            vision_page_numbers=vision_pages,
        )
        zatca_qr = find_zatca_qr(pdf_bytes) if qr else None
        apply_deterministic_sources(result.values, qr=zatca_qr, pages=pages)
        qr_read += zatca_qr is not None
        by_key = {v.field_key: v for v in result.values if v.row_index is None}
        expected = expected_by_doc[document_id]
        doc_path = "vision" if vision_pages else "text"
        for key in NINE_FIELDS:
            report.add(key, expected.get(key), by_key.get(key), path=doc_path)
        report.documents += 1
        # Deliberately no per-document print here (unlike benchmark.run): a
        # filename or a per-field line would risk naming what the field said.
        # Only the aggregate, scores-only report below is printed.

    print(render(report))
    if qr:
        # A count, never the QR's content.
        print(f"ZATCA QR read on {qr_read} of {report.documents} document(s)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_template = sub.add_parser(
        "template", help="print a ground-truth JSON template for one document"
    )
    p_template.add_argument("document_id")

    p_load = sub.add_parser("load", help="load samples/eval/*.json into the eval-set tables")
    p_load.add_argument("org_id")
    p_load.add_argument("eval_set_name")
    p_load.add_argument("directory", type=Path)

    p_score = sub.add_parser("score", help="run extraction and score it against ground truth")
    p_score.add_argument("org_id")
    p_score.add_argument("eval_set_name")
    p_score.add_argument("--mode", choices=("text", "vision", "auto"), default="auto")
    p_score.add_argument("--qr", choices=("on", "off"), default="off")

    args = parser.parse_args()

    if args.command == "template":
        print(json.dumps(_template(args.document_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "load":
        asyncio.run(_load(uuid.UUID(args.org_id), args.eval_set_name, args.directory))
        return 0
    if args.command == "score":
        asyncio.run(
            _score(uuid.UUID(args.org_id), args.eval_set_name, args.mode, qr=args.qr == "on")
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
