"""Why each wrong field was wrong, counted. No model is run.

    backend/.venv/Scripts/python.exe -m scripts.coru_errors local-b-vision-v2 colab-b-vision-v2

Reads the per-receipt records ``scripts/coru_eval.py`` wrote for a run, and
sorts every field that was not correct into one of:

* misread       a near copy of the truth: a digit or letter read wrong, one
                dropped or doubled. The model looked at the right thing.
* label_style   right by the page, different from the label's convention: the
                shop named with its branch or legal name or in the page's
                script, another of the numbers the receipt prints, the same
                digits in a number or date format this scorer does not read
                (a decimal comma), or a label that is not a value at all.
* wrong_field   the value of a DIFFERENT annotated field on that receipt: the
                subtotal as the total, the delivery date as the date.
* empty         nothing returned.
* unclassified  near neither the truth nor any other annotated value. Possibly
                invented, possibly printed and simply not annotated; it is
                counted, not guessed into a category.

The split that matters is model versus data: misread, wrong_field and empty are
the model's; label_style is the benchmark's; unclassified is not known.

The rules use every question CORU asks about a receipt, not only the ones mapped
to our fields, so "another field's value" means any annotated value on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from app.services.normalize import has_arabic
from scripts.coru_eval import (
    AMOUNT_FIELDS,
    CODE_FIELDS,
    CORU,
    DATE_FIELDS,
    FIELD_ORDER,
    _code,
    _name,
    date_readings,
    fuzzy_name_match,
    matches,
    parse_amount,
)
from scripts.coru_sample import field_for, normalize_question, split_dir

CATEGORIES = ("misread", "label_style", "wrong_field", "empty", "unclassified")
MODEL_ERRORS = ("misread", "wrong_field", "empty")

NEAR = 0.75
"""Levenshtein similarity, 0-1, at or above which a value is a near copy of the
truth. One wrong digit in a nine-digit number is 0.89; one dropped character in
eighteen is 0.94; two unrelated numbers of the same length sit near 0.3."""

_NUMBER_WORDS = ("number", " no", " id", "code", "reference", "slip", "ticket")


def _digits(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def _similar(left: str, right: str) -> bool:
    return bool(left and right) and Levenshtein.normalized_similarity(left, right) >= NEAR


def _near_truth(field: str, predicted: str, acceptable: list[str]) -> bool:
    if field in AMOUNT_FIELDS:
        value = parse_amount(predicted)
        return value is not None and any(
            (truth := parse_amount(a)) is not None and _similar(f"{value:.2f}", f"{truth:.2f}")
            for a in acceptable
        )
    if field in DATE_FIELDS:
        return any(
            _similar(mine.isoformat(), theirs.isoformat())
            for mine in date_readings(predicted)
            for a in acceptable
            for theirs in date_readings(a)
        )
    if field in CODE_FIELDS:
        return any(_similar(_code(predicted), _code(a)) for a in acceptable)
    return any(fuzz.ratio(_name(predicted), _name(a)) >= NEAR * 100 for a in acceptable)


def _same_tokens_one_way(predicted: str, acceptable: list[str]) -> bool:
    """One name's words all appear in the other: a branch or a legal form added,
    or a short form used."""
    mine = set(_name(predicted).split())
    for a in acceptable:
        theirs = set(_name(a).split())
        if mine and theirs and (mine <= theirs or theirs <= mine):
            return True
    return False


def _equals_other(field: str, predicted: str, others: list[tuple[str, str]]) -> str | None:
    """The question whose answer this value is, if it is another field's."""
    for question, answer in others:
        if field_for(question) == field:
            continue
        if field in AMOUNT_FIELDS:
            same = parse_amount(predicted) is not None and parse_amount(predicted) == parse_amount(
                answer
            )
        elif field in DATE_FIELDS:
            same = bool(date_readings(predicted) & date_readings(answer))
        elif field in CODE_FIELDS:
            same = bool(_code(predicted)) and _code(predicted) == _code(answer)
        else:
            same = bool(_name(predicted)) and _name(predicted) == _name(answer)
        if same:
            return normalize_question(question)
    return None


def classify(
    field: str, predicted: str | None, acceptable: list[str], others: list[tuple[str, str]]
) -> str:
    """The cause of one wrong field. ``others`` is every (question, answer)
    CORU has for the receipt; the ones asking for this field are ignored."""
    if predicted is None or not predicted.strip():
        return "empty"

    # The label itself is the problem: it is not a value of its own type (a date
    # of '6/24/202-'), or it is the same digits in a format the scorer does not
    # read (a decimal comma: '24,44' against a correct '24.44').
    if field in AMOUNT_FIELDS:
        if all(parse_amount(a) is None for a in acceptable):
            return "label_style"
        if _digits(predicted) and any(_digits(predicted) == _digits(a) for a in acceptable):
            return "label_style"
    if field in DATE_FIELDS and not any(date_readings(a) for a in acceptable):
        return "label_style"

    other = _equals_other(field, predicted, others)
    if other is not None:
        # Two cases where another annotated value is a difference of convention,
        # not a wrong pick: a receipt prints several numbers and any of them
        # identifies it, and "the company" is the seller our field asks for.
        if field == "invoice_number" and any(word in f" {other}" for word in _NUMBER_WORDS):
            return "label_style"
        if field == "seller_name" and "company" in other:
            return "label_style"
        return "wrong_field"

    if field == "seller_name":
        if any(has_arabic(predicted) != has_arabic(a) for a in acceptable):
            return "label_style"
        if _same_tokens_one_way(predicted, acceptable):
            return "label_style"
        if _near_truth(field, predicted, acceptable):
            return "misread"
        return "label_style" if fuzzy_name_match(predicted, acceptable) else "unclassified"

    if field in DATE_FIELDS and not date_readings(predicted):
        same_digits = any(_digits(predicted) == _digits(a) for a in acceptable)
        return "label_style" if same_digits and _digits(predicted) else "unclassified"

    if _near_truth(field, predicted, acceptable):
        return "misread"
    return "unclassified"


def tally(run: str, split: str = "test") -> dict[str, Counter[str]]:
    """Category counts per field for one run of ``scripts/coru_eval.py``."""
    truth = json.loads((split_dir(split) / "ground_truth.json").read_text(encoding="utf-8"))[
        "receipts"
    ]
    qa = json.loads((CORU / "qa.json").read_text(encoding="utf-8"))
    records = json.loads((CORU / "runs" / f"{run}.json").read_text(encoding="utf-8"))
    counts: dict[str, Counter[str]] = {key: Counter() for key in FIELD_ORDER}
    for receipt_id, record in records.items():
        reading = record["reading"]
        others = [
            (str(pair.get("question", "")), str(pair.get("answer", "")))
            for pair in qa.get(receipt_id, [])
        ]
        for key, acceptable in truth[receipt_id].items():
            predicted = reading["values"].get(key) if reading else None
            if predicted is not None and matches(key, predicted, acceptable):
                continue
            counts[key][classify(key, predicted, acceptable, others)] += 1
    return counts


def render(run: str, counts: dict[str, Counter[str]]) -> str:
    total: Counter[str] = Counter()
    for per_field in counts.values():
        total.update(per_field)
    lines = [
        f"**`{run}`** — {sum(total.values())} wrong fields",
        "",
        "| Field | Misread | Label style | Wrong field | Empty | Unclassified | All |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in FIELD_ORDER:
        row = counts[key]
        if sum(row.values()):
            lines.append(
                f"| {key} | "
                + " | ".join(str(row[c]) for c in CATEGORIES)
                + f" | {sum(row.values())} |"
            )
    lines.append(
        "| **All** | "
        + " | ".join(f"**{total[c]}**" for c in CATEGORIES)
        + f" | **{sum(total.values())}** |"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("runs", nargs="+", help="run labels under samples/eval/coru/runs/")
    parser.add_argument("--split", choices=("test", "dev"), default="test")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    for run in args.runs:
        print(render(run, tally(run, args.split)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
