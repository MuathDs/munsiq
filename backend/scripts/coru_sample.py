"""Fetch a fixed sample of CORU / ReceiptSense receipts with ground truth.

    backend/.venv/Scripts/python.exe -m scripts.coru_sample annotations
    backend/.venv/Scripts/python.exe -m scripts.coru_sample questions
    backend/.venv/Scripts/python.exe -m scripts.coru_sample sample --n 100 --seed 0
    backend/.venv/Scripts/python.exe -m scripts.coru_sample sample --split dev --n 50 --seed 1

CORU (Abdallah et al., "ReceiptSense", arXiv:2406.04493; Hugging Face dataset
``abdoelsayed/CORU``, MIT licence) is a public set of Arabic/English retail
receipt photos. Only its Receipt-QA split carries receipt-level TEXT ground
truth: one JSON of question/answer pairs per receipt. (Its key-information
split is boxes without values, and its IE split is item rows.) So ground truth
here is the answer to a question — "What is the store name?" — mapped to the
field of ours it corresponds to. The questions were generated per receipt
(19,890 distinct wordings over 1,100 receipts), so each field is a small family
of wordings; see ``FIELD_QUESTIONS``.

The split is one 3.9 GB zip. Nothing here downloads it whole: the zip's
directory is read with HTTP range requests and only the entries needed are
fetched — every annotation JSON (4.5 MB) and the sampled images.

Two splits. ``test`` is the 100-receipt sample every published number is
scored on. ``dev`` is drawn from the receipts that are NOT in it, for anything
that has to be tuned — a prompt, a threshold — so that tuning never sees the
receipts it is later scored on.

Everything lands in ``samples/eval/coru/``, which is git-ignored.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import struct
import sys
import urllib.request
import zipfile
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

URL = "https://huggingface.co/datasets/abdoelsayed/CORU/resolve/main/QA/test.zip"
OUT = Path(__file__).resolve().parents[2] / "samples" / "eval" / "coru"
ANNOTATIONS = OUT / "qa.json"
GROUND_TRUTH = OUT / "ground_truth.json"
IMAGES = OUT / "images"
SPLITS = ("test", "dev")


def split_dir(split: str) -> Path:
    """The test split keeps its original place; every other split gets a folder."""
    return OUT if split == "test" else OUT / split


# Our field -> the CORU questions (normalized, see `normalize_question`) that
# ask for it. Chosen from the question counts over every receipt (`questions`
# prints them). Deliberately narrow — lookalikes were measured and left out:
#   "name of the company"      same answer as the store name on 4 of 56 receipts
#   "total due" / "net amount" same answer as the total on 79 of 197
#   "order/slip/check number"  same answer as the receipt number on 2 of 121
# Not mapped at all: currency (free-form answers), customer name (the images are
# PII-redacted, the answers are not), and anything our schema has no field for.
_PLACE = "store|shop|restaurant|supermarket|pharmacy|merchant"
_DATED = "transaction|receipt|purchase|invoice|order"
FIELD_QUESTIONS: dict[str, re.Pattern[str]] = {
    "seller_name": re.compile(rf"what is the (name of the ({_PLACE})|({_PLACE}) name)"),
    "issue_date": re.compile(
        rf"what is the (date|date of the ({_DATED})|date on the receipt"
        r"|(transaction|receipt|invoice|purchase) date)"
        r"|what date was the (transaction|receipt|purchase)( made)?"
        r"|when was the (transaction|purchase)( made)?"
    ),
    "invoice_number": re.compile(r"what is the (transaction|receipt|invoice|bill) (number|no)"),
    "subtotal": re.compile(
        r"what (is|was) the (subtotal|sub total|subtotal amount)"
        r"|what is the (total amount without vat|total without vat|total before vat"
        r"|amount before vat|total excluding vat|total before tax)"
    ),
    "vat_amount": re.compile(
        r"what (is|was) the (vat amount|vat value|total vat|tax amount|vat|amount of vat"
        r"|total tax|tax)"
    ),
    "total_amount": re.compile(
        r"what (is|was) the (total|total amount|grand total|total amount paid|total price)"
    ),
    "seller_trn": re.compile(
        r"what is the (vat number|vat registration number|tax registration number"
        r"|tax number|vat no)"
    ),
}

# A receipt can print a transaction number AND a receipt number (205 of 649
# do), and either is a fair answer to "the invoice number": any of them counts.
# Every other field has one right answer, so two different answers mean the
# annotation is ambiguous and the field is dropped for that receipt.
ANY_ANSWER_COUNTS: frozenset[str] = frozenset({"invoice_number"})

# A receipt enters the sample only if it answers all of these.
REQUIRED_FIELDS: tuple[str, ...] = ("seller_name", "issue_date", "total_amount")

_UUID_IMAGE = re.compile(r"test/([0-9a-f-]{36})\.jpg")


def normalize_question(question: str) -> str:
    """Lower-case, no punctuation, single spaces: 'What is the Date?' and
    'what is the date' are one question."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", question.lower())).strip()


class RangeFile(io.RawIOBase):
    """A read-only, seekable view of a remote file over HTTP range requests."""

    def __init__(self, url: str) -> None:
        self.url, self.pos = url, 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as response:
            self.size = int(response.headers["Content-Length"])

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        base = 0 if whence == 0 else self.pos if whence == 1 else self.size
        self.pos = base + offset
        return self.pos

    def readinto(self, buffer: bytearray) -> int:  # type: ignore[override]
        if self.pos >= self.size or not buffer:
            return 0
        data = fetch_range(self.url, self.pos, min(self.pos + len(buffer), self.size) - 1)
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)


def fetch_range(url: str, first: int, last: int) -> bytes:
    request = urllib.request.Request(url, headers={"Range": f"bytes={first}-{last}"})
    with urllib.request.urlopen(request) as response:
        return bytes(response.read())


def directory() -> list[zipfile.ZipInfo]:
    reader = io.BufferedReader(RangeFile(URL), buffer_size=1 << 16)  # type: ignore[type-var]
    return zipfile.ZipFile(reader).infolist()


def fetch_entry(info: zipfile.ZipInfo) -> bytes:
    """One zip entry by range: its local header, then its (deflated) bytes."""
    # The local header's name/extra lengths can differ from the directory's, so
    # over-read a little and parse them rather than trust the directory.
    slack = 30 + len(info.filename.encode()) + 256
    blob = fetch_range(URL, info.header_offset, info.header_offset + slack + info.compress_size)
    name_len, extra_len = struct.unpack("<HH", blob[26:30])
    start = 30 + name_len + extra_len
    data = blob[start : start + info.compress_size]
    if info.compress_type == zipfile.ZIP_STORED:
        return data
    return zlib.decompress(data, -zlib.MAX_WBITS)


def fetch_many(infos: list[zipfile.ZipInfo]) -> list[bytes]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(fetch_entry, infos))


def cmd_annotations() -> None:
    infos = directory()
    images = {m.group(1) for i in infos if (m := _UUID_IMAGE.fullmatch(i.filename))}
    wanted = [i for i in infos if i.filename.endswith(".json") and i.filename[5:-5] in images]
    print(f"{len(wanted)} receipts have both a QA file and an image; fetching their QA files")
    qa: dict[str, object] = {}
    broken = 0
    for info, raw in zip(wanted, fetch_many(wanted), strict=True):
        try:
            pairs = json.loads(raw)
        except json.JSONDecodeError:
            broken += 1  # the dataset's own file is malformed; nothing to score against
            continue
        if isinstance(pairs, list):
            qa[info.filename[5:-5]] = [p for p in pairs if isinstance(p, dict)]
    print(f"{len(qa)} parsed, {broken} skipped as malformed JSON")
    OUT.mkdir(parents=True, exist_ok=True)
    ANNOTATIONS.write_text(json.dumps(qa, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {ANNOTATIONS} ({ANNOTATIONS.stat().st_size / 1e6:.1f} MB)")


def load_annotations() -> dict[str, list[dict[str, str]]]:
    if not ANNOTATIONS.exists():
        raise SystemExit("run `python -m scripts.coru_sample annotations` first")
    loaded: dict[str, list[dict[str, str]]] = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    return loaded


def cmd_questions(top: int) -> None:
    qa = load_annotations()
    counts: Counter[str] = Counter()
    for pairs in qa.values():
        counts.update({normalize_question(p["question"]) for p in pairs if "question" in p})
    print(f"{len(qa)} receipts, {len(counts)} distinct questions")
    for question, n in counts.most_common(top):
        print(f"{n:5}  {question}")


def field_for(question: str) -> str | None:
    normalized = normalize_question(question)
    for field, pattern in FIELD_QUESTIONS.items():
        if pattern.fullmatch(normalized):
            return field
    return None


def ground_truth_for(pairs: list[dict[str, str]]) -> dict[str, list[str]]:
    """Our fields for one receipt, each with its acceptable answers: one,
    except where ``ANY_ANSWER_COUNTS`` says several are fair. A single-answer
    field asked twice with different answers is dropped rather than guessed."""
    seen: dict[str, list[str]] = {}
    for pair in pairs:
        field = field_for(str(pair.get("question", "")))
        answer = str(pair.get("answer", "")).strip()
        if field and answer and answer not in seen.setdefault(field, []):
            seen[field].append(answer)
    return {
        field: answers
        for field, answers in seen.items()
        if answers and (len(answers) == 1 or field in ANY_ANSWER_COUNTS)
    }


def choose_sample(
    eligible: list[str], n: int, *, seed: int, exclude: list[str] | tuple[str, ...] = ()
) -> list[str]:
    """A fixed draw of ``n`` receipts, never one of ``exclude``.

    With nothing excluded this is the formula the test sample was drawn with,
    so that sample cannot move. The pool is sorted first, so the draw depends
    on the seed and the ids alone, not on the order they were listed in.
    """
    held_out = set(exclude)
    pool = sorted(rid for rid in eligible if rid not in held_out)
    if n > len(pool):
        raise SystemExit(f"asked for {n} receipts, only {len(pool)} are eligible and not excluded")
    return sorted(random.Random(seed).sample(pool, n))


def cmd_sample(n: int, seed: int, split: str) -> None:
    qa = load_annotations()
    truth = {rid: ground_truth_for(pairs) for rid, pairs in qa.items()}
    eligible = sorted(rid for rid, gt in truth.items() if all(f in gt for f in REQUIRED_FIELDS))
    exclude: list[str] = []
    if split != "test":
        if not GROUND_TRUTH.exists():
            raise SystemExit("draw the test split first: a dev split is defined against it")
        exclude = sorted(json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))["receipts"])
    chosen = choose_sample(eligible, n, seed=seed, exclude=exclude)
    assert not set(chosen) & set(exclude)
    print(f"{len(qa)} receipts; per-field ground truth available:")
    for field in FIELD_QUESTIONS:
        print(f"  {field:16} {sum(field in gt for gt in truth.values())}")
    print(
        f"{len(eligible)} answer all of {REQUIRED_FIELDS}; {len(exclude)} held out as the "
        f"test split; sampled {n} with seed {seed} for split '{split}'"
    )
    target = split_dir(split)
    images, ground_truth = target / "images", target / "ground_truth.json"

    by_name = {i.filename: i for i in directory()}
    infos = [by_name[f"test/{rid}.jpg"] for rid in chosen]
    images.mkdir(parents=True, exist_ok=True)
    total = 0
    for rid, data in zip(chosen, fetch_many(infos), strict=True):
        (images / f"{rid}.jpg").write_bytes(data)
        total += len(data)
    ground_truth.write_text(
        json.dumps(
            {
                "dataset": "abdoelsayed/CORU (QA/test)",
                "split": split,
                "seed": seed,
                "n": n,
                "receipts": {rid: truth[rid] for rid in chosen},
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {n} images ({total / 1e6:.0f} MB) and {ground_truth}")
    counts = Counter(f for rid in chosen for f in truth[rid])
    print("ground truth in the sample:")
    for field in FIELD_QUESTIONS:
        print(f"  {field:16} {counts[field]}")
    print(f"  {'ALL':16} {sum(counts.values())}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("annotations", help="fetch every QA file (4.5 MB)")
    p_questions = sub.add_parser("questions", help="count the distinct questions")
    p_questions.add_argument("--top", type=int, default=60)
    p_sample = sub.add_parser("sample", help="pick receipts and fetch their images")
    p_sample.add_argument("--n", type=int, default=100)
    p_sample.add_argument("--seed", type=int, default=0)
    p_sample.add_argument("--split", choices=SPLITS, default="test")
    args = parser.parse_args()
    if args.command == "annotations":
        cmd_annotations()
    elif args.command == "questions":
        cmd_questions(args.top)
    else:
        cmd_sample(args.n, args.seed, args.split)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
