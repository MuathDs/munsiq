"""Is a field's label printed on the page?

Used to catch a SILENT MISS: the model returned null for a field whose label is
sitting in the text. A field that is absent from the document has no label there,
and that null is correct and stays quiet; a field whose label is present and whose
value came back null is a miss, and a reviewer has to be told.

Matching is done with ALL whitespace removed from both sides. That is deliberate
and it is the whole reason this is not a plain ``in`` test: the first real invoice's
text layer had cut Arabic words apart after non-joining letters (a space after the
alef of the definite article, for one), so a match on the words as written would
miss the label that was plainly there.

The price of ignoring spaces is a false hit on a longer word, and the one that
matters in practice is a plural: "المشتريات" (purchases, the title of a purchase
summary) begins with the letters of "المشتري" (the buyer). A match followed by an
Arabic plural or dual ending is therefore not accepted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from app.services.normalize import normalize_for_match

MIN_LABEL_CHARS: Final = 4
"""Below this, a label with its spaces removed matches half the alphabet."""

_LONGER_WORD_ENDINGS: Final = frozenset({"ات", "ون", "ين", "ان"})

_WHITESPACE: Final = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _WHITESPACE.sub("", normalize_for_match(text))


def label_present(labels: Iterable[str], text: str) -> str | None:
    """The first label that appears in ``text``, or None."""
    haystack = _squash(text)
    for label in labels:
        needle = _squash(label)
        if len(needle) < MIN_LABEL_CHARS:
            continue
        start = haystack.find(needle)
        while start != -1:
            end = start + len(needle)
            # The plural of a word ending in ي is that ي plus "ن" (المشتري -> المشترين),
            # so the ending can overlap the label's last letter.
            extended = haystack[end : end + 2] in _LONGER_WORD_ENDINGS or (
                needle.endswith("ي") and haystack[end : end + 1] == "ن"
            )
            if not extended:
                return label
            start = haystack.find(needle, start + 1)
    return None
