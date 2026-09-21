"""Benchmark the extraction model against the six generated test invoices.

    backend/.venv/Scripts/python.exe -m scripts.make_test_invoices      # once
    backend/.venv/Scripts/python.exe -m scripts.benchmark --label before
    backend/.venv/Scripts/python.exe -m scripts.benchmark --label after
    backend/.venv/Scripts/python.exe -m scripts.benchmark --compare before after

Every PDF is read by the MODEL, including the two that carry a signed UBL (the
pipeline would skip the model for those; here the point is to measure it). Expected
values come from ``samples/test/expected.json``, written by make_test_invoices from
the same numbers that draw each page, so the truth is exact. Both files are
git-ignored and invented.

What is counted, per field:

* correct         the value matches (money to the halala, dates as dates)
* wrong           a value came back and it is not the expected one
* null_miss       a value is printed and the model returned null
* silent_miss     a null_miss that the reviewer would NOT be warned about, because
                  the field is still marked auto_validated. This is the number that
                  matters: a silent miss is worse than a visible error.
* false_value     nothing is printed and the model invented something

Slow by design (about half a minute per invoice on this GPU) and needs Ollama.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from app.services.extraction.client import OllamaClient
from app.services.extraction.prompts import parse_schema
from app.services.extraction.runner import ExtractedValue, run_extraction
from app.services.normalize import normalize_for_match, normalize_text
from app.services.pagetext import extract_page_text
from scripts.seed_demo import INVOICE_SCHEMA

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "test"
MONEY = frozenset({"subtotal", "vat_amount", "total_amount"})
HALALA = Decimal("0.005")


def _money(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", normalize_text(raw).replace(",", ""))
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _date(raw: str | None) -> str | None:
    """Any of 2026-04-06, 06/04/2026, 06 - 04 - 2026 as 2026-04-06."""
    if raw is None:
        return None
    parts = re.findall(r"\d+", normalize_text(raw))
    if len(parts) != 3:
        return None
    if len(parts[0]) == 4:
        year, month, day = parts
    elif len(parts[2]) == 4:
        day, month, year = parts
    else:
        return None
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _currency(raw: str | None) -> str | None:
    if raw is None:
        return None
    folded = normalize_for_match(raw)
    return "SAR" if any(t in folded for t in ("sar", "riyal", "ريال", "ر.س", "sr")) else folded


def _text(raw: str | None) -> str | None:
    return None if raw is None else re.sub(r"[\W_]+", "", normalize_for_match(raw))


def same(key: str, expected: str | None, got: str | None) -> bool:
    if key in MONEY:
        a, b = _money(expected), _money(got)
        return a is not None and b is not None and abs(a - b) <= HALALA
    if key == "issue_date":
        return _date(expected) is not None and _date(expected) == _date(got)
    if key == "currency":
        return _currency(expected) == _currency(got)
    return _text(expected) == _text(got)


@dataclass
class Tally:
    correct: int = 0
    wrong: int = 0
    null_miss: int = 0
    silent_miss: int = 0
    false_value: int = 0
    wrong_but_flagged: int = 0

    @property
    def total(self) -> int:
        return self.correct + self.wrong + self.null_miss + self.false_value


@dataclass
class Report:
    label: str
    fields: dict[str, Tally] = field(default_factory=dict)
    seconds: float = 0.0
    documents: int = 0

    def add(self, key: str, expected: str | None, value: ExtractedValue | None) -> None:
        tally = self.fields.setdefault(key, Tally())
        got = value.value if value else None
        flagged = value is not None and value.validation_state != "auto_validated"
        if expected is None:
            if got is None:
                tally.correct += 1
            else:
                tally.false_value += 1
        elif got is None:
            tally.null_miss += 1
            tally.silent_miss += 0 if flagged else 1
        elif same(key, expected, got):
            tally.correct += 1
        else:
            tally.wrong += 1
            tally.wrong_but_flagged += 1 if flagged else 0

    def totals(self) -> Tally:
        out = Tally()
        for t in self.fields.values():
            for name in asdict(out):
                setattr(out, name, getattr(out, name) + getattr(t, name))
        return out


def run(label: str, directory: Path, only: list[str] | None) -> Report:
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    fields = parse_schema(INVOICE_SCHEMA)
    client = OllamaClient()
    report = Report(label=label)
    for name in sorted(expected):
        if only and not any(o in name for o in only):
            continue
        started = time.monotonic()
        with pymupdf.open(directory / name) as doc:  # type: ignore[no-untyped-call]
            pages = [extract_page_text(p, i) for i, p in enumerate(doc, start=1)]
        result = run_extraction(client=client, fields=fields, pages=pages)
        by_key = {v.field_key: v for v in result.values if v.row_index is None}
        for spec in fields:
            report.add(spec.key, expected[name].get(spec.key), by_key.get(spec.key))
        report.documents += 1
        elapsed = time.monotonic() - started
        report.seconds += elapsed
        print(f"  {name:34} {elapsed:5.1f}s", flush=True)
    return report


def render(report: Report) -> str:
    lines = [
        f"[{report.label}]  {report.documents} invoices, {report.seconds:.0f}s",
        f"{'field':24} {'ok':>3} {'wrong':>5} {'null':>4} {'SILENT':>6} {'false':>5}   accuracy",
    ]
    for key, t in report.fields.items():
        lines.append(
            f"{key:24} {t.correct:>3} {t.wrong:>5} {t.null_miss:>4} {t.silent_miss:>6} "
            f"{t.false_value:>5}   {t.correct / t.total:>6.0%}"
        )
    t = report.totals()
    lines.append(
        f"{'ALL':24} {t.correct:>3} {t.wrong:>5} {t.null_miss:>4} {t.silent_miss:>6} "
        f"{t.false_value:>5}   {t.correct / t.total:>6.0%}"
    )
    return "\n".join(lines)


def load(label: str, directory: Path) -> Report:
    raw = json.loads((directory / f"benchmark-{label}.json").read_text(encoding="utf-8"))
    return Report(
        label=raw["label"],
        fields={k: Tally(**v) for k, v in raw["fields"].items()},
        seconds=raw["seconds"],
        documents=raw["documents"],
    )


def compare(before: Report, after: Report) -> str:
    lines = [
        f"{before.label}  ->  {after.label}",
        f"{'field':24} {'accuracy':>16} {'null':>9} {'SILENT':>9}",
    ]
    for key in before.fields:
        b, a = before.fields[key], after.fields.get(key, Tally())
        lines.append(
            f"{key:24} {b.correct / b.total:>7.0%} -> {a.correct / max(a.total, 1):<5.0%} "
            f"{b.null_miss:>4} -> {a.null_miss:<2} {b.silent_miss:>4} -> {a.silent_miss:<2}"
        )
    tb, ta = before.totals(), after.totals()
    lines.append(
        f"{'ALL':24} {tb.correct / tb.total:>7.0%} -> {ta.correct / max(ta.total, 1):<5.0%} "
        f"{tb.null_miss:>4} -> {ta.null_miss:<2} {tb.silent_miss:>4} -> {ta.silent_miss:<2}"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--label", default="run")
    parser.add_argument("--dir", type=Path, default=SAMPLES)
    parser.add_argument("--only", nargs="*", help="substrings of filenames to include")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()

    if args.compare:
        print(compare(load(args.compare[0], args.dir), load(args.compare[1], args.dir)))
        return 0

    print(f"benchmark '{args.label}' — model reads every invoice, UBL ignored")
    report = run(args.label, args.dir, args.only)
    (args.dir / f"benchmark-{args.label}.json").write_text(
        json.dumps(
            {
                "label": report.label,
                "seconds": report.seconds,
                "documents": report.documents,
                "fields": {k: asdict(v) for k, v in report.fields.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print()
    print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
