"""
build_report.py — Batch pipeline: raw procurement text -> local model -> Excel/CSV report.

Reads raw document text, runs each document through the locally-served fine-tuned
Qwen model (via Ollama, using the exact same endpoint and prompt as the web UI),
flattens the extracted JSON into one row per document, and writes:

  * a human-readable Excel workbook (for a CEO / non-technical stakeholder), and
  * a flat CSV (a clean source for Power BI to ingest and auto-refresh).

Both outputs are built from a single in-memory table, so the Excel view and the
Power BI feed can never drift apart -- one extraction, one canonical structure.

Usage
-----
  # Process the raw `text` fields from the existing dataset through the model:
  python -m src.data_pipeline.build_report --input data/procurement_finetune.jsonl --limit 20

  # Build the report from the ground-truth labels instead of calling the model
  # (fast; useful for testing the reporting half without waiting on inference):
  python -m src.data_pipeline.build_report --input data/procurement_finetune.jsonl --from-ground-truth
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

# --------------------------------------------------------------------------- #
# Model / prompt config -- kept identical to frontend/src/app/api/extract/route.ts
# so batch extraction and UI extraction produce the same output.
# --------------------------------------------------------------------------- #
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "munsiq-extractor"

JSON_SCHEMA_DESCRIPTION = """{
  "document_type": string, // one of: Purchase Order, Invoice, LPO, Work Order,
                            // Maintenance Log, Delivery Note, RFQ, Warranty Claim,
                            // Service Report, Inspection Report
  "company_name": string,
  "equipment_mentioned": string[],
  "total_value_sar": number,
  "critical_dates": string[]  // copy each date exactly as it appears in the text,
                              // do not reformat it
}"""

PROMPT_TEMPLATE = """أنت مهندس بيانات خبير متخصص في المستندات الصناعية والعقود. استخرج الحقول التالية من النص أدناه وأعدها بصيغة JSON صالحة فقط، مطابقة تماماً للمخطط المحدد، دون أي شرح إضافي.

### المخطط المطلوب (JSON Schema):
{schema}

### النص الأصلي:
{text}

### المخرجات (JSON):
"""

# Field order for the report. LIST_FIELDS get joined into a single cell so each
# document is exactly one readable row.
FIELDS = ["document_type", "company_name", "equipment_mentioned",
          "total_value_sar", "critical_dates"]
LIST_FIELDS = {"equipment_mentioned", "critical_dates"}

# Human-friendly column headers for the Excel/CSV output.
COLUMN_LABELS = {
    "source_id": "Source",
    "document_type": "Document Type",
    "company_name": "Company",
    "equipment_mentioned": "Equipment",
    "total_value_sar": "Total Value (SAR)",
    "critical_dates": "Critical Dates",
    "parse_ok": "Extracted OK",
}


def build_prompt(text: str) -> str:
    return PROMPT_TEMPLATE.format(schema=JSON_SCHEMA_DESCRIPTION, text=text)


def call_model(text: str, timeout: int = 300) -> str:
    """Send one document to the local model and return the raw completion text."""
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": build_prompt(text),
            "raw": True,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 256},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def extract_json_block(text: str) -> dict | None:
    """Pull the first {...} block out of a model completion and parse it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def flatten_record(source_id: str, extracted: dict | None) -> dict:
    """Turn one extraction into a single flat row for the report table."""
    row: dict = {"source_id": source_id}
    if extracted is None:
        for f in FIELDS:
            row[f] = None
        row["parse_ok"] = False
        return row

    for f in FIELDS:
        value = extracted.get(f)
        if f in LIST_FIELDS and isinstance(value, list):
            row[f] = "; ".join(str(v) for v in value)
        else:
            row[f] = value
    row["parse_ok"] = True
    return row


def load_documents(input_path: Path) -> list[dict]:
    """Load records from a .jsonl file. Each record must have a `text` field;
    `extracted_json` (ground-truth) is used only in --from-ground-truth mode."""
    records = []
    with input_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            records.append({
                "source_id": obj.get("id", f"doc_{i + 1:04d}"),
                "text": obj["text"],
                "ground_truth": obj.get("extracted_json"),
            })
    return records


def write_report(rows: list[dict], out_dir: Path, basename: str) -> tuple[Path, Path]:
    """Write the flat rows to both an Excel workbook and a CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)

    column_order = ["source_id", *FIELDS, "parse_ok"]
    df = pd.DataFrame(rows, columns=column_order).rename(columns=COLUMN_LABELS)

    csv_path = out_dir / f"{basename}.csv"
    xlsx_path = out_dir / f"{basename}.xlsx"

    # CSV for Power BI: utf-8-sig so Arabic renders correctly on import.
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Excel for humans: autosized columns, frozen header, SAR number format.
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Extractions")
        ws = writer.sheets["Extractions"]
        ws.freeze_panes = "A2"

        sar_col_label = COLUMN_LABELS["total_value_sar"]
        for idx, col in enumerate(df.columns, start=1):
            letter = ws.cell(row=1, column=idx).column_letter
            max_len = max(
                [len(str(col))] + [len(str(v)) for v in df[col].fillna("")]
            )
            ws.column_dimensions[letter].width = min(max_len + 2, 60)
            if col == sar_col_label:
                for cell in ws[letter][1:]:
                    cell.number_format = "#,##0.00"

    return xlsx_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch extraction -> Excel/CSV report.")
    parser.add_argument("--input", required=True, type=Path,
                        help="Input .jsonl with a `text` field per line.")
    parser.add_argument("--out-dir", type=Path, default=Path("data/reports"),
                        help="Output directory for the report files.")
    parser.add_argument("--basename", default="procurement_report",
                        help="Base filename (without extension) for the outputs.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N documents (useful on slow hardware).")
    parser.add_argument("--from-ground-truth", action="store_true",
                        help="Skip the model; build the report from existing `extracted_json` labels.")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    documents = load_documents(args.input)
    if args.limit is not None:
        documents = documents[: args.limit]

    print(f"Loaded {len(documents)} document(s). "
          f"{'Using ground-truth labels' if args.from_ground_truth else 'Calling local model'}...")

    rows = []
    failures = 0
    t0 = time.time()

    for n, doc in enumerate(documents, start=1):
        if args.from_ground_truth:
            extracted = doc["ground_truth"]
        else:
            try:
                completion = call_model(doc["text"])
                extracted = extract_json_block(completion)
            except requests.RequestException as e:
                print(f"  [{n}/{len(documents)}] {doc['source_id']}: request failed ({e})",
                      file=sys.stderr)
                extracted = None

        if extracted is None:
            failures += 1
        rows.append(flatten_record(doc["source_id"], extracted))

        if not args.from_ground_truth:
            print(f"  [{n}/{len(documents)}] {doc['source_id']}: "
                  f"{'ok' if extracted else 'FAILED'}")

    xlsx_path, csv_path = write_report(rows, args.out_dir, args.basename)
    elapsed = time.time() - t0

    print(f"\nDone in {elapsed:.1f}s. {len(rows)} rows, {failures} extraction failure(s).")
    print(f"  Excel (for people):   {xlsx_path}")
    print(f"  CSV   (for Power BI): {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
