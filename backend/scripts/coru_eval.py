"""Score the local models on a public receipt set (CORU / ReceiptSense).

    backend/.venv/Scripts/python.exe -m scripts.coru_sample sample      # once
    backend/.venv/Scripts/python.exe -m scripts.coru_eval --label a --mode text
    backend/.venv/Scripts/python.exe -m scripts.coru_eval --label b --mode vision
    backend/.venv/Scripts/python.exe -m scripts.coru_eval --label c --mode vision --few-shot

Each receipt photo is wrapped as a one-page PDF with no text layer — what a
scanned upload looks like — and goes through the pipeline's own steps: page
text (OCR), routing, the model, the deterministic sources, the rules and the
page findings. Nothing touches the database. Each run is appended to
``docs/results.md``; per-receipt predictions go to the git-ignored
``samples/eval/coru/runs/``.

Two things are measured per field that has ground truth:

* exact match AFTER normalization — amounts as Decimals, dates as dates, names
  with case/spacing/punctuation folded. ``seller_name`` also gets a fuzzy
  column, reported next to the strict one and never instead of it: CORU's
  store names are all annotated in Latin script, including on Arabic receipts.
* the validation catch rate — of the fields the model got wrong (a wrong value
  or none), how many a rule flagged with an error or a warning. "Not shown
  green" is the wider count: fields left amber for any reason.

CORU: Abdallah et al., "ReceiptSense: Beyond Traditional OCR", arXiv:2406.04493;
Hugging Face ``abdoelsayed/CORU``, MIT licence. The sample and its field mapping
come from ``scripts/coru_sample.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rapidfuzz import fuzz

from app.services.normalize import normalize_for_match, normalize_text

REPO = Path(__file__).resolve().parents[2]
CORU = REPO / "samples" / "eval" / "coru"
RESULTS = REPO / "docs" / "results.md"

AMOUNT_FIELDS = frozenset({"subtotal", "vat_amount", "total_amount"})
DATE_FIELDS = frozenset({"issue_date"})
CODE_FIELDS = frozenset({"invoice_number", "seller_trn"})
FUZZY_FIELD = "seller_name"
FUZZY_THRESHOLD = 85
"""rapidfuzz token_set_ratio, 0-100. A printed short name inside the annotated
long one ("Gourmet" / "Gourmet Food Stores") scores 100; another store does not
come close."""

FIELD_ORDER = (
    "seller_name",
    "issue_date",
    "invoice_number",
    "subtotal",
    "vat_amount",
    "total_amount",
    "seller_trn",
)

Status = Literal["correct", "wrong", "missing"]


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def parse_amount(raw: str | None) -> Decimal | None:
    """The number in 'LE 3,754.00', '153.51 EGP' or '*299.00'."""
    if not raw:
        return None
    text = normalize_text(raw).replace("٫", ".").replace("٬", "")
    text = re.sub(r",(?=\d{3}(\D|$))", "", text)
    found = re.search(r"-?\d+(?:\.\d+)?", text)
    if found is None:
        return None
    try:
        return Decimal(found.group())
    except InvalidOperation:  # pragma: no cover - the regex admits only numbers
        return None


_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_ISO = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})(?!\d)")
_DAY_MONTH_NAME = re.compile(r"(?<!\d)(\d{1,2})[\s\-/.]*([a-z]{3,9})[\s\-/.,]*(\d{4}|\d{2})(?!\d)")
_MONTH_NAME_DAY = re.compile(
    r"([a-z]{3,9})[\s.]*(\d{1,2})(?:st|nd|rd|th)?[\s,]+(\d{4}|\d{2})(?!\d)"
)


def _year(raw: str) -> int:
    return int(raw) + 2000 if len(raw) == 2 else int(raw)


def _real(year: int, month: int, day: int) -> set[date]:
    try:
        return {date(year, month, day)}
    except ValueError:
        return set()


def date_readings(raw: str | None) -> set[date]:
    """Every date the text could mean. '6/11/2022' is 6 November or 11 June and
    nothing on a receipt says which, so both are returned; '14/09/2022' has only
    one real reading. Empty when there is no date in the text."""
    if not raw:
        return set()
    text = normalize_text(raw).lower()
    if found := _ISO.search(text):
        year, month, day = (int(part) for part in found.groups())
        return _real(year, month, day)
    if found := _NUMERIC.search(text):
        first, second, year = int(found.group(1)), int(found.group(2)), _year(found.group(3))
        return _real(year, second, first) | _real(year, first, second)
    if (found := _DAY_MONTH_NAME.search(text)) and found.group(2) in _MONTHS:
        return _real(_year(found.group(3)), _MONTHS[found.group(2)], int(found.group(1)))
    if (found := _MONTH_NAME_DAY.search(text)) and found.group(1) in _MONTHS:
        return _real(_year(found.group(3)), _MONTHS[found.group(1)], int(found.group(2)))
    return set()


def _name(raw: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", normalize_for_match(raw))).strip()


def _code(raw: str) -> str:
    return re.sub(r"[^0-9a-z]", "", normalize_text(raw).lower())


def matches(field_key: str, predicted: str | None, acceptable: list[str]) -> bool:
    """Exact match after normalization, against any acceptable answer."""
    if predicted is None or not predicted.strip():
        return False
    if field_key in AMOUNT_FIELDS:
        value = parse_amount(predicted)
        return value is not None and any(value == parse_amount(a) for a in acceptable)
    if field_key in DATE_FIELDS:
        readings = date_readings(predicted)
        return any(readings & date_readings(a) for a in acceptable)
    if field_key in CODE_FIELDS:
        code = _code(predicted)
        return bool(code) and any(code == _code(a) for a in acceptable)
    name = _name(predicted)
    return bool(name) and any(name == _name(a) for a in acceptable)


def fuzzy_name_match(predicted: str | None, acceptable: list[str]) -> bool:
    if predicted is None or not predicted.strip():
        return False
    name = _name(predicted)
    return any(fuzz.token_set_ratio(name, _name(a)) >= FUZZY_THRESHOLD for a in acceptable)


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FieldOutcome:
    field: str
    status: str
    rule_flagged: bool = False
    """A rule raised an error or a warning naming this field."""
    shown_green: bool = True
    """The field ended `auto_validated`: nothing asks a reviewer to look."""
    fuzzy_correct: bool = False


def score_field(
    field_key: str,
    predicted: str | None,
    acceptable: list[str],
    *,
    rule_flagged: bool = False,
    shown_green: bool = True,
) -> FieldOutcome:
    status: Status
    if predicted is None or not predicted.strip():
        status = "missing"
    elif matches(field_key, predicted, acceptable):
        status = "correct"
    else:
        status = "wrong"
    return FieldOutcome(
        field=field_key,
        status=status,
        rule_flagged=rule_flagged,
        shown_green=shown_green,
        fuzzy_correct=status == "correct" or fuzzy_name_match(predicted, acceptable),
    )


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


@dataclass
class Scoreboard:
    label: str
    outcomes: list[FieldOutcome] = field(default_factory=list)
    documents: int = 0
    failed_documents: int = 0
    seconds: float = 0.0

    def add(self, outcome: FieldOutcome) -> None:
        self.outcomes.append(outcome)

    def of(self, field_key: str | None = None) -> list[FieldOutcome]:
        return [o for o in self.outcomes if field_key is None or o.field == field_key]

    def count(self, status: str, field_key: str | None = None) -> int:
        return sum(1 for o in self.of(field_key) if o.status == status)

    def accuracy(self, field_key: str | None = None) -> float | None:
        return _rate(self.count("correct", field_key), len(self.of(field_key)))

    def fuzzy_accuracy(self, field_key: str = FUZZY_FIELD) -> float | None:
        scored = self.of(field_key)
        return _rate(sum(1 for o in scored if o.fuzzy_correct), len(scored))

    def _not_correct(self, exclude: frozenset[str]) -> list[FieldOutcome]:
        return [o for o in self.outcomes if o.status != "correct" and o.field not in exclude]

    def caught(self, exclude: frozenset[str] = frozenset()) -> tuple[int, int]:
        wrong = self._not_correct(exclude)
        return sum(1 for o in wrong if o.rule_flagged), len(wrong)

    def catch_rate(self, exclude: frozenset[str] = frozenset()) -> float | None:
        return _rate(*self.caught(exclude))

    def not_green(self, exclude: frozenset[str] = frozenset()) -> tuple[int, int]:
        wrong = self._not_correct(exclude)
        return sum(1 for o in wrong if not o.shown_green), len(wrong)

    def not_green_rate(self, exclude: frozenset[str] = frozenset()) -> float | None:
        return _rate(*self.not_green(exclude))

    def false_alarms(self, exclude: frozenset[str] = frozenset()) -> tuple[int, int]:
        right = [o for o in self.outcomes if o.status == "correct" and o.field not in exclude]
        return sum(1 for o in right if o.rule_flagged), len(right)

    def false_alarm_rate(self, exclude: frozenset[str] = frozenset()) -> float | None:
        return _rate(*self.false_alarms(exclude))

    @property
    def seconds_per_document(self) -> float | None:
        return _rate_float(self.seconds, self.documents)


def _rate_float(total: float, count: int) -> float | None:
    return total / count if count else None


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.0%}"


def _of(pair: tuple[int, int]) -> str:
    part, whole = pair
    return f"{part} of {whole} ({_pct(_rate(part, whole))})"


NO_TRN = frozenset({"seller_trn"})


def render(scores: Scoreboard) -> str:
    """One run as markdown: per-field table, then the rates."""
    lines = [
        "| Field | With ground truth | Correct | Wrong | Missing | Exact match |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    present = [f for f in FIELD_ORDER if scores.of(f)]
    present += sorted({o.field for o in scores.outcomes} - set(present))
    for key in present:
        lines.append(
            f"| {key} | {len(scores.of(key))} | {scores.count('correct', key)} | "
            f"{scores.count('wrong', key)} | {scores.count('missing', key)} | "
            f"{_pct(scores.accuracy(key))} |"
        )
        if key == FUZZY_FIELD:
            fuzzy = sum(1 for o in scores.of(key) if o.fuzzy_correct)
            lines.append(
                f"| {key}, fuzzy (token-set ≥ {FUZZY_THRESHOLD}) | {len(scores.of(key))} | "
                f"{fuzzy} | | | {_pct(scores.fuzzy_accuracy(key))} |"
            )
    lines.append(
        f"| **All fields** | {len(scores.outcomes)} | {scores.count('correct')} | "
        f"{scores.count('wrong')} | {scores.count('missing')} | **{_pct(scores.accuracy())}** |"
    )
    per_doc = scores.seconds_per_document
    lines += [
        "",
        f"- Catch rate (a rule flagged the wrong field): {_of(scores.caught())}; "
        f"without seller_trn: {_of(scores.caught(NO_TRN))}",
        f"- Wrong fields not shown green (flagged or amber for any reason): "
        f"{_of(scores.not_green())}; without seller_trn: {_of(scores.not_green(NO_TRN))}",
        f"- False alarms (a rule flagged a correct field): {_of(scores.false_alarms())}; "
        f"without seller_trn: {_of(scores.false_alarms(NO_TRN))}",
        f"- Time: {'n/a' if per_doc is None else f'{per_doc:.1f} s'} per document "
        f"({scores.documents} documents, {scores.failed_documents} failed)",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Running the pipeline's steps on one receipt photo
# --------------------------------------------------------------------------- #
A4_LONG_SIDE_PT = 842.0


def upright(image: bytes) -> bytes:
    """The photo with its EXIF rotation applied to the pixels.

    A phone stores a portrait shot as landscape pixels plus a 'rotate' flag.
    Viewers honour the flag; embedding the raw JPEG in a PDF does not, and the
    model would be shown the receipt sideways. Untouched bytes when there is
    nothing to turn, so an upright photo is not re-compressed.
    """
    import io

    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(image)) as photo:
        if photo.getexif().get(274, 1) in (0, 1):
            return image
        turned = ImageOps.exif_transpose(photo).convert("RGB")
    out = io.BytesIO()
    turned.save(out, format="JPEG", quality=95)
    return out.getvalue()


def image_to_pdf(image: bytes) -> bytes:
    """A one-page PDF holding the photo and no text layer: a scanned upload.

    The page's long side is A4's, the photo scaled to fit — what 'print to PDF'
    or a scanner app does with a phone photo — so the pipeline's own DPI
    settings decide the pixels the OCR and the vision model see.
    """
    import pymupdf

    image = upright(image)
    with pymupdf.open(stream=image, filetype="jpg") as source:  # type: ignore[no-untyped-call]
        rect = source[0].rect
    scale = A4_LONG_SIDE_PT / max(rect.width, rect.height)
    with pymupdf.open() as doc:  # type: ignore[no-untyped-call]
        page = doc.new_page(width=rect.width * scale, height=rect.height * scale)
        page.insert_image(page.rect, stream=image)
        return bytes(doc.tobytes())


@dataclass
class Reading:
    values: dict[str, str | None]
    flagged: frozenset[str]
    green: frozenset[str]
    blockers: list[str]
    path: str
    text_sources: list[str]


def read_receipt(pdf_bytes: bytes, *, mode: str, few_shot: bool) -> Reading:
    """The pipeline's steps 2-4b, without the database."""
    import pymupdf

    from app.config import get_settings
    from app.services.extraction.client import OllamaClient
    from app.services.extraction.fewshot import RECEIPT_EXAMPLES
    from app.services.extraction.prompts import parse_schema
    from app.services.extraction.qr_values import apply_deterministic_sources
    from app.services.extraction.routing import resolve_mode
    from app.services.extraction.runner import run_extraction
    from app.services.pagetext import extract_page_text
    from app.services.qr import find_zatca_qr
    from app.services.raster import rasterize_pages
    from app.services.validation import run_rules
    from app.services.validation.context import build_context
    from app.services.validation.page_findings import PageState, missing_required, page_findings
    from scripts.seed_demo import INVOICE_SCHEMA

    settings = get_settings()
    fields = parse_schema(INVOICE_SCHEMA)
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        pages = [extract_page_text(p, i) for i, p in enumerate(doc, start=1)]

    resolved, wants_vision = resolve_mode(mode, pages)  # type: ignore[arg-type]
    vision_pages = frozenset(sorted(wants_vision)[: settings.MAX_VISION_PAGES])
    images = None
    if vision_pages:
        rasters = rasterize_pages(
            pdf_bytes, vision_pages, dpi=settings.VISION_RASTER_DPI, quality=settings.WEBP_QUALITY
        )
        images = [r.data for r in sorted(rasters, key=lambda r: r.page_number)]
    if resolved == "vision":
        client = OllamaClient(
            base_url=settings.VISION_INFERENCE_BASE_URL or settings.INFERENCE_BASE_URL,
            model=settings.VISION_MODEL,
            num_ctx=settings.VISION_NUM_CTX,
        )
    else:
        client = OllamaClient()

    result = run_extraction(
        client=client,
        fields=fields,
        pages=pages,
        page_images=images,
        vision_page_numbers=vision_pages,
        examples=RECEIPT_EXAMPLES if few_shot else (),
    )
    qr = find_zatca_qr(pdf_bytes) if settings.QR_READING else None
    apply_deterministic_sources(result.values, qr=qr, pages=pages)

    context = build_context(values=result.values, fields=fields, pages=pages, invoice=None)
    report = run_rules(context)
    report.results.extend(
        page_findings(
            [PageState(p.page_number, p.source, p.note) for p in pages],
            missing_required=missing_required(context),
        )
    )
    flagged = frozenset(report.blocking_field_keys) | frozenset(report.warned_field_keys)
    header = [v for v in result.values if v.row_index is None]
    return Reading(
        values={v.field_key: v.value for v in header},
        flagged=flagged,
        green=frozenset(
            v.field_key
            for v in header
            if v.validation_state == "auto_validated" and v.field_key not in flagged
        ),
        blockers=list(report.blockers),
        path="vision" if vision_pages else "text",
        text_sources=[p.source for p in pages],
    )


def run(label: str, *, mode: str, few_shot: bool, limit: int | None) -> Scoreboard:
    from app.services.extraction.client import InferenceError

    truth: dict[str, dict[str, list[str]]] = json.loads(
        (CORU / "ground_truth.json").read_text(encoding="utf-8")
    )["receipts"]
    scores = Scoreboard(label=label)
    details: dict[str, object] = {}
    for receipt_id in sorted(truth)[:limit]:
        expected = truth[receipt_id]
        started = time.monotonic()
        pdf = image_to_pdf((CORU / "images" / f"{receipt_id}.jpg").read_bytes())
        try:
            reading: Reading | None = read_receipt(pdf, mode=mode, few_shot=few_shot)
            error = None
        except InferenceError as exc:
            # In the pipeline this document is marked failed: nothing is shown
            # green, and no rule ran. Its fields count as missing.
            reading, error = None, str(exc)[:200]
            scores.failed_documents += 1
        elapsed = time.monotonic() - started
        scores.seconds += elapsed
        scores.documents += 1
        statuses = {}
        for key, acceptable in expected.items():
            outcome = score_field(
                key,
                reading.values.get(key) if reading else None,
                acceptable,
                rule_flagged=bool(reading) and key in reading.flagged,  # type: ignore[union-attr]
                shown_green=bool(reading) and key in reading.green,  # type: ignore[union-attr]
            )
            scores.add(outcome)
            statuses[key] = outcome.status
        details[receipt_id] = {
            "seconds": round(elapsed, 1),
            "error": error,
            "statuses": statuses,
            "reading": asdict(reading)
            | {"flagged": sorted(reading.flagged), "green": sorted(reading.green)}
            if reading
            else None,
        }
        correct = sum(1 for s in statuses.values() if s == "correct")
        print(
            f"  {scores.documents:3} {receipt_id[:8]} {elapsed:5.1f}s "
            f"{correct}/{len(statuses)}{'  FAILED' if error else ''}",
            flush=True,
        )
    runs = CORU / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{label}.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return scores


def _commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip()

    return git("rev-parse", "--short", "HEAD") + (
        " + uncommitted changes" if git("status", "--porcelain") else ""
    )


def append_result(scores: Scoreboard, *, title: str, mode: str, few_shot: bool) -> None:
    from app.config import get_settings

    settings = get_settings()
    if mode == "text":
        model = f"`{settings.INFERENCE_MODEL}` on OCR text (num_ctx {settings.INFERENCE_NUM_CTX})"
    else:
        model = (
            f"`{settings.VISION_MODEL}` on page images at {settings.VISION_RASTER_DPI} DPI "
            f"(num_ctx {settings.VISION_NUM_CTX})"
        )
    host = settings.VISION_INFERENCE_BASE_URL if mode != "text" else None
    host = host or settings.INFERENCE_BASE_URL
    local = "localhost" in host or "127.0.0.1" in host
    block = "\n".join(
        [
            f"## {title}",
            "",
            f"- Date: {date.today().isoformat()} · commit: `{_commit()}`",
            f"- Dataset: CORU `QA/test`, {scores.documents} receipts, seed 0 "
            "(`scripts/coru_sample.py`)",
            f"- Model: {model}, {'local Ollama' if local else 'REMOTE inference endpoint'}; "
            f"temperature 0, seed {settings.INFERENCE_SEED}, "
            "thinking off",
            f"- Mode: `{mode}` · few-shot examples: {'2 synthetic' if few_shot else 'none'} · "
            f"QR reading: {'on' if settings.QR_READING else 'off'}",
            "",
            render(scores),
            "",
        ]
    )
    header = "" if RESULTS.exists() else RESULTS_HEADER
    with RESULTS.open("a", encoding="utf-8", newline="\n") as out:
        out.write(header + block + "\n")


RESULTS_HEADER = """# Measured results

Every run of `scripts/coru_eval.py` appends itself here: date, commit,
configuration, per-field exact match, catch rate and seconds per document.
Nothing in this file is estimated or edited after the fact.

**Dataset.** CORU / ReceiptSense — Abdallah et al., "ReceiptSense: Beyond
Traditional OCR - A Dataset for Receipt Understanding", arXiv:2406.04493;
Hugging Face `abdoelsayed/CORU`, MIT licence. Arabic/English retail receipt
photos. Ground truth is the Receipt-QA split's answers, mapped to the fields of
ours they correspond to (`scripts/coru_sample.py` has the mapping and why each
lookalike question was left out). 100 receipts, fixed sample, seed 0.

**How to read it.**

- *Exact match* is after normalization: amounts as Decimals, dates as dates
  (an ambiguous `6/11/2022` is accepted under either reading), names with case,
  spacing and punctuation folded.
- *seller_name, fuzzy* sits next to the strict row because every annotated
  store name is in Latin script, including on Arabic receipts: an exactly-read
  Arabic name cannot match its English annotation.
- *subtotal* is loose ground truth: ours means "excluding VAT", a receipt's
  printed "subtotal" may not.
- *seller_trn* is not a Saudi VAT number on these receipts, so the format rule
  flags it even when it was read correctly. Catch rate and false alarms are
  therefore given with and without it.
- These receipts are not what the product is built for (Saudi tax invoices with
  signed XML or a ZATCA QR). They are a public, checkable stand-in for the hard
  case: a photographed page with no text layer.

"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--label", required=True, help="file name for the per-receipt output")
    parser.add_argument("--title", help="heading in docs/results.md (default: the label)")
    parser.add_argument("--mode", choices=("text", "vision", "auto"), required=True)
    parser.add_argument("--few-shot", action="store_true")
    parser.add_argument("--limit", type=int, help="first N receipts only; not appended")
    args = parser.parse_args()
    # A Windows console in a legacy code page cannot print every character in a
    # report; a display error must never cost a finished run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    print(f"coru '{args.label}' [mode={args.mode}, few_shot={args.few_shot}]")
    scores = run(args.label, mode=args.mode, few_shot=args.few_shot, limit=args.limit)
    if args.limit is None:
        # Saved before anything is printed.
        append_result(
            scores, title=args.title or args.label, mode=args.mode, few_shot=args.few_shot
        )
    print()
    print(render(scores))
    if args.limit is None:
        print(f"\nappended to {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
