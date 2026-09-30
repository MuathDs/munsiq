"""The test-invoice generator makes claims about what each file should trigger.

Those claims are computed by running the deterministic stages on the files it
writes. This pins them, so a rule change that alters what a test invoice does is
noticed here instead of during a manual upload session. No database, no model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.make_test_invoices import LATIN_FONT, generate

pytestmark = pytest.mark.skipif(
    not LATIN_FONT.exists(), reason="needs Arial, which has the Arabic glyphs"
)


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[bytes, object]]:
    out = tmp_path_factory.mktemp("invoices")
    return {inv.filename: (pdf, result) for inv, pdf, result in generate(Path(out))}


RECEIPTS = ["07_receipt_english_qr.pdf", "08_receipt_arabic_qr.pdf"]


def test_eight_invoices_with_the_intended_mix(generated: dict[str, tuple[bytes, object]]) -> None:
    assert sorted(generated) == [
        "01_ubl_english_compliant.pdf",
        "02_ubl_arabic_primary.pdf",
        "03_digital_english_no_ubl.pdf",
        "04_digital_arabic_no_ubl.pdf",
        "05_arithmetic_error.pdf",
        "06_invalid_trn.pdf",
        *RECEIPTS,
    ]


@pytest.mark.parametrize("name", RECEIPTS)
def test_receipts_carry_a_readable_zatca_qr_matching_the_page(
    generated: dict[str, tuple[bytes, object]], name: str
) -> None:
    """Tax-inclusive simplified receipts: the page prints no subtotal and no
    buyer, and the QR printed on it decodes to the receipt's own values."""
    from app.services.qr import find_zatca_qr
    from scripts.make_test_invoices import INVOICES, expected_values

    pdf = generated[name][0]
    inv = next(i for i in INVOICES if i.filename == name)
    qr = find_zatca_qr(pdf)
    assert qr is not None, f"{name}: no ZATCA QR read back"
    expected = expected_values(inv)
    assert (qr.seller_name, qr.seller_trn, qr.issue_date) == (
        expected["seller_name"], expected["seller_trn"], expected["issue_date"]
    )
    assert (qr.total_with_vat, qr.vat_total) == (expected["total_amount"], expected["vat_amount"])
    assert expected["buyer_name"] is None and expected["buyer_trn"] is None


@pytest.mark.parametrize("name", RECEIPTS)
def test_receipts_raise_nothing_once_the_qr_is_read(
    generated: dict[str, tuple[bytes, object]], name: str
) -> None:
    result = generated[name][1]
    assert result.blockers == [] and result.warnings == []  # type: ignore[attr-defined]
    assert "QR" in result.note  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", ["01_ubl_english_compliant.pdf", "02_ubl_arabic_primary.pdf"])
def test_compliant_ubl_invoices_are_clean(
    generated: dict[str, tuple[bytes, object]], name: str
) -> None:
    result = generated[name][1]
    assert result.blockers == [] and result.warnings == []  # type: ignore[attr-defined]
    assert "model is never called" in result.note  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", ["03_digital_english_no_ubl.pdf", "04_digital_arabic_no_ubl.pdf"])
def test_clean_digital_invoices_raise_nothing(
    generated: dict[str, tuple[bytes, object]], name: str
) -> None:
    result = generated[name][1]
    assert result.blockers == [] and result.warnings == []  # type: ignore[attr-defined]


def test_the_arithmetic_error_is_only_the_vat_line(
    generated: dict[str, tuple[bytes, object]],
) -> None:
    """The total is added up from the wrong VAT, so the sum itself is consistent:
    exactly one rule fires, and it is the right one."""
    assert generated["05_arithmetic_error.pdf"][1].blockers == [  # type: ignore[attr-defined]
        "VAT_CALC_MISMATCH(vat_amount)"
    ]


def test_the_invalid_trn_is_only_the_sellers(generated: dict[str, tuple[bytes, object]]) -> None:
    assert generated["06_invalid_trn.pdf"][1].blockers == [  # type: ignore[attr-defined]
        "TRN_FORMAT(seller_trn)"
    ]


def test_every_pdf_is_a_real_pdf_with_a_text_layer(
    generated: dict[str, tuple[bytes, object]],
) -> None:
    import pymupdf

    for name, (pdf, _) in generated.items():
        assert pdf.startswith(b"%PDF-"), name
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            assert len(doc[0].get_text().strip()) > 40, f"{name} has no text layer"
