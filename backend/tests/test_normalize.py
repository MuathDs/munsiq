"""Arabic and numeral normalization.

These are the cases that make or break comparing a model's output against a UBL
value, or checking that an extracted number actually appears on the page.
"""

from __future__ import annotations

import pytest

from app.services.normalize import (
    fold_arabic_orthography,
    has_arabic,
    has_arabic_presentation_forms,
    normalize_for_match,
    normalize_numerals,
    normalize_text,
)


def test_arabic_indic_digits_fold_to_ascii() -> None:
    assert normalize_numerals("١٢٣") == "123"


def test_eastern_arabic_indic_digits_fold_to_ascii() -> None:
    assert normalize_numerals("۴۵۶") == "456"


def test_mixed_digits_in_an_amount() -> None:
    assert normalize_numerals("٤٥,٣٢٠.٠٠") == "45,320.00"


def test_presentation_forms_fold_to_base_letters() -> None:
    """The core Arabic-PDF problem: text layers store shaped glyphs.

    A PDF gives us U+FE93 U+FEAD ... where the logical text is U+0629 U+0631 ...
    Without this, no Arabic value ever matches its UBL counterpart.
    """
    shaped = "ﺓﺭﻱﺯﺝﻝ"
    normalized = normalize_text(shaped)
    assert all(0x0600 <= ord(ch) <= 0x06FF for ch in normalized)
    assert normalized == "ةريزجل"


def test_presentation_forms_are_detected_before_folding() -> None:
    assert has_arabic_presentation_forms("ﺓﺭ") is True
    assert has_arabic_presentation_forms("شركة") is False


def test_has_arabic_covers_both_base_and_shaped() -> None:
    assert has_arabic("شركة") is True
    assert has_arabic("ﺓﺭ") is True
    assert has_arabic("Centrifugal pump") is False


def test_tatweel_and_diacritics_are_dropped() -> None:
    assert normalize_text("شــركة") == "شركة"
    assert normalize_text("مَرْحَبًا") == ("مرحبا")


def test_whitespace_is_collapsed() -> None:
    assert normalize_text("  45,320.00\n\n  SAR  ") == "45,320.00 SAR"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Jubail Maintenance", "jubail   maintenance"),
        ("١٢٣.٠٠", "123.00"),
        ("ﺓﺭ", "ةر"),
    ],
)
def test_match_form_makes_equivalent_strings_equal(left: str, right: str) -> None:
    assert normalize_for_match(left) == normalize_for_match(right)


def test_normalization_is_idempotent() -> None:
    once = normalize_text("٤٥ شـركة")
    assert normalize_text(once) == once


def test_soft_hyphen_from_a_pdf_text_layer_folds_to_a_hyphen() -> None:
    """Real PDFs embed odd codepoints mid-token.

    PyMuPDF returns "SA<U+00AD>2026<U+00AD>0334" for text drawn as
    "SA-2026-0334" — the font maps its hyphen glyph onto the soft hyphen. The
    page visibly shows hyphens, so folding to "-" matches what a reader sees.
    Left alone, the value would fail to ground against its own document.
    """
    assert normalize_text("SA\u00ad2026\u00ad0334") == "SA-2026-0334"


def test_zero_width_characters_are_removed() -> None:
    assert normalize_text("45\u200b,\u200c320.00") == "45,320.00"
    assert normalize_text("\ufeffInvoice") == "Invoice"


def test_typographic_dashes_fold_to_ascii() -> None:
    assert normalize_text("SA\u20132026\u20140334") == "SA-2026-0334"


def test_non_breaking_space_folds_to_a_normal_space() -> None:
    assert normalize_text("45,320.00\u00a0SAR") == "45,320.00 SAR"


# --------------------------------------------------------------------------- #
# Arabic orthographic folding — matching only, never storage
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("letter", ["أ", "إ", "آ", "ا"])
def test_the_alef_family_folds_to_one_letter(letter: str) -> None:
    assert fold_arabic_orthography(letter) == fold_arabic_orthography("ا")


@pytest.mark.parametrize("letter", ["ى", "ي"])
def test_alef_maksura_and_yeh_fold_to_one_letter(letter: str) -> None:
    assert fold_arabic_orthography(letter) == fold_arabic_orthography("ي")


@pytest.mark.parametrize("letter", ["ة", "ه"])
def test_ta_marbuta_and_ha_fold_to_one_letter(letter: str) -> None:
    assert fold_arabic_orthography(letter) == fold_arabic_orthography("ه")


def test_two_spellings_of_one_name_match() -> None:
    """The shape of the case that motivated this (a real supplier name, here
    replaced with a synthetic one using the same two variant letters): one name
    read two different but equally correct ways must ground and score as the
    same value, not as a mismatch."""
    left = normalize_for_match("سلمي الانصاري")
    right = normalize_for_match("سلمى الأنصاري")
    assert left == right


def test_orthographic_folding_does_not_touch_stored_or_displayed_text() -> None:
    """Two spellings of a name are different names, not a typo of each other.

    Folding them is a matching heuristic; applying it to a value that gets
    stored or shown to a reviewer would silently corrupt data the model got
    exactly right.
    """
    assert normalize_text("أحمد") == "أحمد"
    assert normalize_text("فاطمة") == "فاطمة"
    assert normalize_text("سلمى") == "سلمى"


def test_folding_is_idempotent() -> None:
    once = fold_arabic_orthography("سلمى الأنصاري")
    assert fold_arabic_orthography(once) == once


def test_latin_text_is_unaffected_by_folding() -> None:
    assert fold_arabic_orthography("Jubail Maintenance") == "Jubail Maintenance"
