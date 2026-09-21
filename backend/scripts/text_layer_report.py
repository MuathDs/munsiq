"""Measure whether a PDF's text layer cuts Arabic words apart. Prints NUMBERS ONLY.

    backend/.venv/Scripts/python.exe -m scripts.text_layer_report path/to/file.pdf

Written so it can be run on a document that is personal data and must not be read:
no word, no letter and no value is ever printed, only counts and ratios, so its
output is safe to paste anywhere.

What it reports, per page:

* how many words are Arabic, and what share are single letters and what share begin
  with the definite article (real text: few and many; a cut-apart layer: many and
  none — see ``TEXT_LAYER_FRAGMENTED``);
* the gap between every pair of neighbouring Arabic words on a line, as a fraction
  of the line height, split by whether the word that comes first in reading order
  ends in a letter that never joins the next one. If words really are being cut
  after non-joining letters, the small gaps pile up in the first row and the second
  row is nearly empty. That is what tells the two populations of gap apart, and it
  is the number needed to pick a threshold for joining the fragments back.
"""

from __future__ import annotations

import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from app.services.normalize import has_arabic, normalize_text

NON_JOINING = frozenset("ادذرزو")
BUCKETS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.00)


def bucket(ratio: float) -> str:
    for edge in BUCKETS:
        if ratio < edge:
            return f"<{edge:.2f}"
    return f">={BUCKETS[-1]:.2f}"


def report(path: Path) -> None:
    with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
        for number, page in enumerate(doc, start=1):
            words = [
                (x0, y0, x1, y1, normalize_text(raw))
                for x0, y0, x1, y1, raw, *_ in page.get_text("words")
            ]
            arabic = [w for w in words if has_arabic(w[4])]
            print(f"page {number}: {len(words)} words, {len(arabic)} Arabic")
            if len(arabic) < 5:
                continue
            single = sum(1 for w in arabic if len(w[4]) == 1)
            article = sum(1 for w in arabic if w[4].startswith("ال"))
            print(f"  single-letter words : {single / len(arabic):.0%}")
            print(f"  begin with the article: {article / len(arabic):.0%}")

            rows: dict[int, list[tuple[float, float, float, float, str]]] = {}
            for w in arabic:
                rows.setdefault(round((w[1] + w[3]) / 2 / 3), []).append(w)
            gaps: dict[bool, Counter[str]] = {True: Counter(), False: Counter()}
            for row in rows.values():
                row.sort(key=lambda w: w[0])
                for left, right in pairwise(row):
                    height = max(right[3] - right[1], 1e-6)
                    # In an RTL line the RIGHT word is read first, so its last
                    # letter is the one that meets the gap.
                    ends_non_joining = right[4][-1] in NON_JOINING
                    gaps[ends_non_joining][bucket((right[0] - left[2]) / height)] += 1
            labels = [f"<{b:.2f}" for b in BUCKETS] + [f">={BUCKETS[-1]:.2f}"]
            print("  gap / line height     " + " ".join(f"{label:>7}" for label in labels))
            for flag, name in (
                (True, "after a NON-joining letter"),
                (False, "after a joining letter"),
            ):
                counts = gaps[flag]
                print(f"  {name:26}" + " ".join(f"{counts[label]:>7}" for label in labels))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    report(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
