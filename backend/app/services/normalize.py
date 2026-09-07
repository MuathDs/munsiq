"""Text normalization for Arabic and Latin invoice text.

Two problems this solves, both measured against real PDF behaviour rather than
assumed:

1. **Arabic presentation forms.** PDF text layers routinely store *shaped*
   glyphs (U+FE70-U+FEFF) instead of base letters, because that is what the
   renderer drew. Extracting a Saudi invoice gives you U+FE93 U+FEAD ... where
   you expected U+0629 U+0631 .... Comparing that against a model's output, or
   against a UBL value, fails for every Arabic field. NFKC maps the
   presentation forms back to base letters, verified round-trip.

2. **Arabic-Indic digits.** Amounts and dates appear as ١٢٣ (U+0660-U+0669) or
   ۱۲۳ (U+06F0-U+06F9). Any arithmetic or substring check against an ASCII
   value fails unless these are folded first.

Every function returns the normalized string; callers that must preserve what
was printed on the document keep the original alongside it, which is why
``ExtractedField`` carries ``original_value``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# U+0660-U+0669 Arabic-Indic, U+06F0-U+06F9 Extended (Persian/Urdu) Arabic-Indic.
ARABIC_INDIC_START: Final[int] = 0x0660
EASTERN_ARABIC_INDIC_START: Final[int] = 0x06F0

_DIGIT_MAP: Final[dict[int, str]] = {
    **{ARABIC_INDIC_START + i: str(i) for i in range(10)},
    **{EASTERN_ARABIC_INDIC_START + i: str(i) for i in range(10)},
}

# Tatweel is a purely cosmetic elongation and carries no meaning.
_TATWEEL: Final[str] = "ـ"
# Combining marks (fatha, damma, shadda, ...) that do not change the word.
_DIACRITICS: Final[re.Pattern[str]] = re.compile(r"[ً-ْٰۖ-ۭ]")

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")

# PDF text layers carry invisible characters that break exact comparison:
# zero-width joiners between Arabic letters, byte-order marks left by a
# generator. They render as nothing, so a human sees a match where a string
# comparison does not.
_FORMAT_CHARS: Final[re.Pattern[str]] = re.compile(r"[​-‏⁠-⁯﻿]")

# Typographic dashes and spaces: a document may carry an en dash or a
# non-breaking space where the value has an ASCII hyphen or space.
#
# U+00AD (soft hyphen) is in this list rather than deleted. In theory it is a
# discretionary line-break hint that renders as nothing; in practice PDF fonts
# routinely map a drawn hyphen glyph onto it, so "SA-2026-0334" comes back as
# "SA<U+00AD>2026<U+00AD>0334" while the page visibly shows hyphens. Folding it
# to "-" matches what the reader sees; deleting it would not.
_DASHES: Final[str] = "­‐‑‒–—―−"
_SPACES: Final[str] = "        　"
_PUNCT_MAP: Final[dict[int, str]] = {
    **{ord(ch): "-" for ch in _DASHES},
    **{ord(ch): " " for ch in _SPACES},
}

ARABIC_RANGE: Final[tuple[int, int]] = (0x0600, 0x06FF)
ARABIC_PRESENTATION_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0xFB50, 0xFDFF),  # Presentation Forms-A
    (0xFE70, 0xFEFF),  # Presentation Forms-B
)


def normalize_numerals(text: str) -> str:
    """Fold Arabic-Indic and Eastern Arabic-Indic digits to ASCII."""
    return text.translate(_DIGIT_MAP)


def has_arabic(text: str) -> bool:
    """True if the text contains Arabic script, in base OR presentation form."""
    for ch in text:
        cp = ord(ch)
        if ARABIC_RANGE[0] <= cp <= ARABIC_RANGE[1]:
            return True
        if any(lo <= cp <= hi for lo, hi in ARABIC_PRESENTATION_RANGES):
            return True
    return False


def has_arabic_presentation_forms(text: str) -> bool:
    """True if the text carries shaped glyphs that need NFKC folding.

    Used as a signal that a PDF's text layer stored presentation forms — worth
    recording, because it is the same condition behind the ZATCA
    ARABIC_ENCODING_SUSPECT failure mode.
    """
    return any(any(lo <= ord(ch) <= hi for lo, hi in ARABIC_PRESENTATION_RANGES) for ch in text)


def normalize_text(text: str, *, fold_diacritics: bool = True) -> str:
    """Canonical form used for comparison, matching and storage.

    NFKC first — that is what converts Arabic presentation forms to base
    letters — then numerals, then cosmetic marks, then whitespace.
    """
    out = unicodedata.normalize("NFKC", text)
    out = _FORMAT_CHARS.sub("", out)
    out = out.translate(_PUNCT_MAP)
    out = normalize_numerals(out)
    out = out.replace(_TATWEEL, "")
    if fold_diacritics:
        out = _DIACRITICS.sub("", out)
    return _WHITESPACE.sub(" ", out).strip()


def normalize_for_match(text: str) -> str:
    """Aggressive form for fuzzy matching only. Never stored."""
    return normalize_text(text).casefold()
