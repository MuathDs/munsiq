"""Reading order in the text layer, reproduced with synthetic PDFs.

Both bugs came from the first real invoice (a marketplace B2C receipt). That PDF is
personal data and is not in the repository; each test builds a fixture that
reproduces the *mechanism* instead.

1. A text extractor reads a content stream, not a picture. A producer that
   draws a right-to-left line from its left end to its right end writes the
   Arabic words to the stream in VISUAL order, and MuPDF then puts each on its
   own line. Printed "شركة حلول نور" came back as "نور حلول شركة". Grouping by
   MuPDF's own lines cannot fix that, because it has already split the words.
2. A value wrapped across two lines ("SA7KXWTPB-" / "LQP3081947") was rejoined
   with a space, which changes the value.
"""

from __future__ import annotations

import io

import pymupdf
import pytest

from app.services.extraction.grounding import ground_value
from app.services.normalize import normalize_text
from app.services.pagetext import PageText, extract_page_text
from tests.fixtures import (
    Op,
    build_pdf_from_ops,
    logical_stream,
    visual_line,
    visual_stream,
)

VENDOR = "شركة حلول نور للتسويق الإلكتروني"
VENDOR_WORDS = tuple(VENDOR.split())
VENDOR_NORMALIZED = [normalize_text(w) for w in VENDOR_WORDS]


def read(pdf: bytes) -> PageText:
    with pymupdf.open(stream=io.BytesIO(pdf), filetype="pdf") as doc:
        return extract_page_text(doc[0], 1)


def word_texts(page: PageText) -> list[str]:
    return [w.text for w in page.words]


# ----------------------------------------------------------------------------- #
# 1. Arabic word order
# ----------------------------------------------------------------------------- #

# The vendor as PRINTED: an RTL line reads from the right, so the first word of
# the name is the rightmost thing on it.
VENDOR_PRINTED = list(reversed(VENDOR_WORDS))


# Two English lines below the row under test, so the page reads as an English one.
ENGLISH_CONTEXT: list[Op] = [
    op
    for row, y in (("TAX INVOICE", 200.0), ("Invoice No: SA-2026-0334", 226.0))
    for token in visual_line(row.split(), y=y)
    for op in token
]


def vendor_line() -> list[list[Op]]:
    return visual_line(VENDOR_PRINTED)


def test_a_visual_order_arabic_line_is_read_in_logical_order() -> None:
    page = read(build_pdf_from_ops(visual_stream(vendor_line())))

    assert word_texts(page) == VENDOR_NORMALIZED
    assert normalize_text(VENDOR) in page.text


def test_a_logical_order_stream_is_not_reversed_a_second_time() -> None:
    """The fix orders by position. It does not assume the producer's habit."""
    page = read(build_pdf_from_ops(logical_stream(vendor_line())))

    assert word_texts(page) == VENDOR_NORMALIZED
    assert normalize_text(VENDOR) in page.text


def test_both_stream_orders_give_identical_text_and_boxes() -> None:
    line = vendor_line()
    visual = read(build_pdf_from_ops(visual_stream(line)))
    logical = read(build_pdf_from_ops(logical_stream(line)))

    assert visual.text == logical.text
    assert [(w.text, w.x0, w.x1) for w in visual.words] == [
        (w.text, w.x0, w.x1) for w in logical.words
    ]


def test_digits_on_an_arabic_line_stay_where_a_reader_finds_them() -> None:
    """Logical "شركة حلول نور 310122393510003": the number is read LAST, so it is
    printed at the LEFT end of the line, and a left-to-right stream meets it
    first."""
    vat = "310122393510003"
    line = visual_line([vat, *reversed(VENDOR_WORDS[:3])])

    page = read(build_pdf_from_ops(visual_stream(line)))

    assert word_texts(page) == [*VENDOR_NORMALIZED[:3], vat]
    assert page.text.split() == word_texts(page)


def test_a_latin_run_inside_an_arabic_line_keeps_its_own_direction() -> None:
    """Two Latin words in an Arabic line must not come out as "Trading Noor"."""
    line = visual_line([VENDOR_WORDS[1], "Noor", "Trading", VENDOR_WORDS[0]], y=120.0)
    # An Arabic page: the rest of it is Arabic, which is what makes this row RTL.
    context = visual_line(VENDOR_PRINTED, y=160.0)

    page = read(build_pdf_from_ops(visual_stream(line) + visual_stream(context)))

    assert word_texts(page)[:4] == [
        VENDOR_NORMALIZED[0],
        "Noor",
        "Trading",
        VENDOR_NORMALIZED[1],
    ]


def test_an_arabic_value_after_an_english_label_keeps_label_first() -> None:
    """On an English page the row is left to right: "Seller: شركة حلول نور".

    The text is flat, so a value that came BEFORE its label would be read as the
    previous field's.
    """
    line = visual_line(["Seller:", *reversed(VENDOR_WORDS[:3])], y=120.0)

    page = read(build_pdf_from_ops(visual_stream(line) + ENGLISH_CONTEXT))

    assert word_texts(page)[:4] == ["Seller:", *VENDOR_NORMALIZED[:3]]


def test_the_same_row_reads_label_last_on_an_arabic_page() -> None:
    """Identical pixels, opposite page direction, opposite reading order.

    That is not a contradiction: an Arabic invoice reads from the right, so the
    Arabic label at the right end is read first and the value at the left is read
    last. Only the rest of the page can say which the row is.
    """
    line = visual_line(["310122393510003", *reversed(VENDOR_WORDS[:3])], y=120.0)
    arabic_context = visual_line(VENDOR_PRINTED, y=160.0)

    on_arabic = read(build_pdf_from_ops(visual_stream(line) + visual_stream(arabic_context)))
    on_english = read(build_pdf_from_ops(visual_stream(line) + ENGLISH_CONTEXT))

    assert word_texts(on_arabic)[:4] == [*VENDOR_NORMALIZED[:3], "310122393510003"]
    assert word_texts(on_english)[:4] == ["310122393510003", *VENDOR_NORMALIZED[:3]]


def test_an_english_line_is_left_exactly_as_extracted() -> None:
    line = visual_line(["Invoice", "No:", "SA-2026-0334"])

    page = read(build_pdf_from_ops(visual_stream(line)))

    assert word_texts(page) == ["Invoice", "No:", "SA-2026-0334"]
    assert page.text == "Invoice No: SA-2026-0334"


def test_two_arabic_columns_far_apart_are_not_fused_into_one_line() -> None:
    """A wide gap is a table column, not a word space, so the columns keep the
    order the stream gave them instead of being interleaved by position."""
    right_column = visual_line([VENDOR_WORDS[1], VENDOR_WORDS[0]], left=430.0)
    left_column = visual_line([VENDOR_WORDS[3], VENDOR_WORDS[2]], left=100.0)

    page = read(build_pdf_from_ops(visual_stream(left_column) + visual_stream(right_column)))

    assert word_texts(page) == [
        VENDOR_NORMALIZED[2],
        VENDOR_NORMALIZED[3],
        VENDOR_NORMALIZED[0],
        VENDOR_NORMALIZED[1],
    ]


def test_the_vendor_grounds_to_one_box_across_every_word() -> None:
    """Reversed, the whole-name window scored low and the field lost its box."""
    page = read(build_pdf_from_ops(visual_stream(vendor_line())))

    grounding = ground_value(VENDOR, [page])

    assert grounding.matched
    assert grounding.score == pytest.approx(100.0)
    assert grounding.bbox is not None
    assert grounding.bbox["x0"] == min(w.x0 for w in page.words)
    assert grounding.bbox["x1"] == max(w.x1 for w in page.words)


# --------------------------------------------------------------------------- #
# 2. A value wrapped after a hyphen
# --------------------------------------------------------------------------- #


def wrapped(first: str, second: str, *, gap: float = 14.0) -> bytes:
    return build_pdf_from_ops(
        [
            ("Invoice No:", 72.0, 100.0),
            (first, 200.0, 100.0),
            (second, 200.0, 100.0 + gap),
        ]
    )


def test_a_value_wrapped_after_a_hyphen_is_joined_without_a_space() -> None:
    page = read(wrapped("SA7KXWTPB-", "LQP3081947"))

    assert "SA7KXWTPB-LQP3081947" in page.text
    assert "SA7KXWTPB- LQP3081947" not in page.text


def test_the_wrapped_value_grounds_across_both_lines_exactly() -> None:
    page = read(wrapped("SA7KXWTPB-", "LQP3081947"))

    grounding = ground_value("SA7KXWTPB-LQP3081947", [page])

    assert grounding.score == pytest.approx(100.0)
    assert grounding.bbox is not None
    first, second = sorted(page.words[-2:], key=lambda w: w.y0)
    assert grounding.bbox["y0"] == first.y0
    assert grounding.bbox["y1"] == second.y1


def test_each_half_keeps_its_own_box() -> None:
    """Joining the TEXT must not merge the two word rectangles into one."""
    page = read(wrapped("SA7KXWTPB-", "LQP3081947"))

    assert word_texts(page)[-2:] == ["SA7KXWTPB-", "LQP3081947"]


@pytest.mark.parametrize(
    ("first", "second", "wrongly_joined"),
    [
        # The next line is a label, not a continuation.
        ("Item code: A-", "Total: 5", "A-Total:"),
        # A bare dash is a separator or an empty cell, not a wrapped identifier.
        ("Discount -", "LQP3081947", "-LQP3081947"),
        ("-", "LQP3081947", "-LQP3081947"),
    ],
)
def test_a_trailing_hyphen_that_is_not_a_wrap_is_left_alone(
    first: str, second: str, wrongly_joined: str
) -> None:
    page = read(wrapped(first, second))

    assert wrongly_joined not in page.text


def test_a_hyphenated_line_far_from_the_next_is_not_joined() -> None:
    """A paragraph break is not a line wrap."""
    page = read(wrapped("SA7KXWTPB-", "LQP3081947", gap=90.0))

    assert "SA7KXWTPB-LQP3081947" not in page.text
    assert "SA7KXWTPB- LQP3081947" in page.text


# --------------------------------------------------------------------------- #
# A page whose stream is already in a sensible order must not be disturbed
# --------------------------------------------------------------------------- #

_ARABIC_HTML = """<body>
<p>رقم الفاتورة: ARB-2026-0211</p>
<p>تاريخ الإصدار: 2026-04-09</p>
<p>البائع: شركة النخبة للتجهيزات الصناعية</p>
<table>
<tr><th>البيان</th><th>الكمية</th><th>سعر الوحدة</th><th>المبلغ</th></tr>
<tr><td>مضخة غاطسة</td><td class='n'>3</td>
<td class='n'>4,200.00</td><td class='n'>12,600.00</td></tr>
</table>
</body>"""

_ARABIC_CSS = """
@font-face { font-family: ArabicFace; src: url(arial.ttf); }
body { font-family: ArabicFace; font-size: 11pt; direction: rtl; text-align: right; }
p { margin: 0 0 5pt 0; }
table { width: 100%; margin: 14pt 0; border-collapse: collapse; }
th, td { padding: 4pt; }
.n { text-align: left; }
"""


def test_an_html_rendered_arabic_page_reads_exactly_as_it_did_before() -> None:
    """MuPDF's own HTML engine already writes this page in a usable order, with a
    date whose pieces run right to left and table cells that are separate text
    objects. The fix regroups by position, so it must leave all of that alone: the
    text has to equal what plain extraction gave."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(
        pymupdf.Rect(60, 60, 535, 780),
        _ARABIC_HTML,
        css=_ARABIC_CSS,
        archive=pymupdf.Archive(r"C:\Windows\Fonts"),
    )
    buffer = io.BytesIO()
    doc.save(buffer)

    with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as reopened:
        extracted = extract_page_text(reopened[0], 1)
        before = normalize_text(reopened[0].get_text().strip(), fold_diacritics=False)

    assert extracted.text == before
    assert "2026 - 04 - 09" in extracted.text or "2026-04-09" in extracted.text
    assert "رقم الفاتورة: ARB-2026-0211" in extracted.text
