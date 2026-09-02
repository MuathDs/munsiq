"""
stress_test.py — Batch-feed multiple invoices to the local model and verify none
are dropped or overwritten (the failure mode the single-shot web UI can't catch).

Reads a delimiter-separated text file of raw invoices, extracts each one
individually via the local Ollama endpoint, and writes every successful
extraction to a single Excel report -- so a dropped or failed record is
immediately visible as a missing/blank row rather than silently overwritten.

Usage
-----
  python -m src.data_pipeline.stress_test
  python -m src.data_pipeline.stress_test --input data/test_invoices.txt --delimiter "=========="
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from src.data_pipeline.build_report import (
    COLUMN_LABELS,
    FIELDS,
    call_model,
    extract_json_block,
    flatten_record,
)

import requests

DEFAULT_INPUT = Path("data/test_invoices.txt")
DEFAULT_DELIMITER = "=========="
DEFAULT_OUTPUT = Path("data/reports/stress_test_report.xlsx")


def load_invoices(path: Path, delimiter: str) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    chunks = [chunk.strip() for chunk in raw.split(delimiter)]
    return [c for c in chunks if c]


def write_excel(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    column_order = ["source_id", *FIELDS, "parse_ok"]
    df = pd.DataFrame(rows, columns=column_order).rename(columns=COLUMN_LABELS)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Stress Test")
        ws = writer.sheets["Stress Test"]
        ws.freeze_panes = "A2"
        for idx, col in enumerate(df.columns, start=1):
            letter = ws.cell(row=1, column=idx).column_letter
            max_len = max([len(str(col))] + [len(str(v)) for v in df[col].fillna("")])
            ws.column_dimensions[letter].width = min(max_len + 2, 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress-test the local model on multiple invoices.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="Text file containing delimiter-separated invoices.")
    parser.add_argument("--delimiter", default=DEFAULT_DELIMITER,
                        help="Delimiter separating individual invoices in the input file.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Path to write the Excel report.")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    invoices = load_invoices(args.input, args.delimiter)
    total = len(invoices)
    print(f"Loaded {total} invoice(s) from {args.input} (delimiter: {args.delimiter!r})\n")

    rows = []
    failures = 0

    for i, invoice_text in enumerate(invoices, start=1):
        source_id = f"invoice_{i:03d}"
        try:
            completion = call_model(invoice_text)
            extracted = extract_json_block(completion)
        except requests.RequestException as e:
            print(f"  [{i}/{total}] {source_id}: request failed ({e})", file=sys.stderr)
            extracted = None

        if extracted is None:
            failures += 1
            print(f"  [{i}/{total}] {source_id}: FAILED")
        else:
            print(f"  [{i}/{total}] {source_id}: ok")

        rows.append(flatten_record(source_id, extracted))

    write_excel(rows, args.output)

    successes = total - failures
    print(f"\nSuccessfully extracted {successes}/{total} invoices. "
          f"{failures} extraction failure{'s' if failures != 1 else ''}.")
    print(f"Report written to: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
