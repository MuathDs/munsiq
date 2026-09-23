"""Tests for ZATCA Step Zero.

Two layers, per samples/README.md:

* Synthetic — always runs, proves internal consistency of our own writer/reader.
* Real samples — parametrized over samples/*.pdf, fails loudly on a
  misclassification rather than skipping.

``test_a_real_zatca_sample_exists`` is marked xfail so the absence of a real
sample shows up in every run instead of hiding behind a green bar.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.invoice import ExtractedField
from app.services.ubl import (
    QR_TAG_PUBLIC_KEY,
    QR_TAG_SELLER_NAME,
    QR_TAG_SIGNATURE,
    QR_TAG_STAMP_SIGNATURE,
    QR_TAG_TOTAL_WITH_VAT,
    QR_TAG_VAT_NUMBER,
    QR_TAG_VAT_TOTAL,
    QR_TAG_XML_HASH,
    MalformedPDFError,
    MalformedXMLError,
    UBLError,
    decode_zatca_qr,
    extract_embedded_xml,
    parse_ubl_invoice,
    trn_tax_type,
    validate_trn,
)
from tests import fixtures
from tests.conftest import SAMPLES, Sample


# --------------------------------------------------------------------------- #
# 1. extract_embedded_xml
# --------------------------------------------------------------------------- #
def test_extracts_xml_from_catalog_embedded_files() -> None:
    pdf = fixtures.build_pdf_with_embedded_xml()
    xml = extract_embedded_xml(pdf)
    assert xml is not None
    assert xml.lstrip().startswith(b"<?xml")
    assert b"AccountingSupplierParty" in xml


def test_returns_none_when_no_attachment() -> None:
    assert extract_embedded_xml(fixtures.build_pdf_without_attachment()) is None


def test_returns_none_when_only_non_xml_attachment() -> None:
    assert extract_embedded_xml(fixtures.build_pdf_with_non_xml_attachment()) is None


def test_detects_xml_by_content_when_extension_is_wrong() -> None:
    """Filename is not authoritative — a .dat holding XML still counts."""
    pdf = fixtures.build_pdf_with_embedded_xml(filename="attachment.dat")
    assert extract_embedded_xml(pdf) is not None


def test_malformed_pdf_raises() -> None:
    with pytest.raises(MalformedPDFError):
        extract_embedded_xml(b"this is definitively not a PDF")


def test_multipage_pdf_without_attachment_returns_none() -> None:
    assert extract_embedded_xml(fixtures.build_pdf_without_attachment(pages=4)) is None


# --------------------------------------------------------------------------- #
# 2. parse_ubl_invoice
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def parsed():  # type: ignore[no-untyped-def]
    return parse_ubl_invoice(fixtures.build_ubl_xml())


def test_parses_header_fields(parsed) -> None:  # type: ignore[no-untyped-def]
    assert parsed.id == "SA-2026-0334"
    assert parsed.uuid == "3cf5ee18-ee25-4ea6-8f6d-2b9d0a2b0f4c"
    assert parsed.issue_date.isoformat() == "2026-02-10"
    assert parsed.issue_time.isoformat() == "11:35:00"
    assert parsed.invoice_type_code == "388"
    assert parsed.invoice_type_name == "0100000"
    assert parsed.document_currency_code == "SAR"


def test_parses_parties_including_arabic(parsed) -> None:  # type: ignore[no-untyped-def]
    assert parsed.supplier.name == fixtures.SELLER_NAME
    assert parsed.supplier.trn == fixtures.SELLER_TRN
    assert parsed.supplier.address is not None
    assert parsed.supplier.address.city_name == "الدمام"
    assert parsed.supplier.address.country_code == "SA"
    assert parsed.customer.name == fixtures.BUYER_NAME
    assert parsed.customer.trn == fixtures.BUYER_TRN


def test_money_is_decimal_never_float(parsed) -> None:  # type: ignore[no-untyped-def]
    assert isinstance(parsed.tax_amount, Decimal)
    assert parsed.tax_amount == Decimal("6798.00")
    total = parsed.monetary_total
    assert isinstance(total.payable_amount, Decimal)
    assert total.line_extension_amount == Decimal("45320.00")
    assert total.tax_exclusive_amount == Decimal("45320.00")
    assert total.tax_inclusive_amount == Decimal("52118.00")
    assert total.payable_amount == Decimal("52118.00")


def test_arithmetic_of_fixture_is_internally_consistent(parsed) -> None:  # type: ignore[no-untyped-def]
    """Guards the fixture itself, so Phase 5's rules get an honest baseline."""
    lines_sum = sum(line.line_extension_amount for line in parsed.lines)
    assert lines_sum == parsed.monetary_total.line_extension_amount
    subtotal = parsed.monetary_total.tax_exclusive_amount
    assert subtotal + parsed.tax_amount == parsed.monetary_total.tax_inclusive_amount


def test_parses_tax_subtotals(parsed) -> None:  # type: ignore[no-untyped-def]
    assert len(parsed.tax_subtotals) == 1
    subtotal = parsed.tax_subtotals[0]
    assert subtotal.category_id == "S"
    assert subtotal.percent == Decimal("15.00")
    assert subtotal.taxable_amount == Decimal("45320.00")
    assert subtotal.tax_amount == Decimal("6798.00")


def test_parses_invoice_lines(parsed) -> None:  # type: ignore[no-untyped-def]
    assert len(parsed.lines) == 2
    first, second = parsed.lines
    assert first.id == "1"
    assert first.invoiced_quantity == Decimal("2")
    assert first.unit_code == "PCE"
    assert first.item_name == "Centrifugal pump"
    assert first.price_amount == Decimal("20000.00")
    assert second.item_name == "صمام كروي 6 انش"
    assert second.line_extension_amount == Decimal("5320.00")


def test_detects_icv_pih_and_qr(parsed) -> None:  # type: ignore[no-untyped-def]
    assert parsed.has_icv is True
    assert parsed.icv == "17"
    assert parsed.has_pih is True
    assert parsed.pih is not None
    assert parsed.qr_base64 is not None
    assert parsed.qr_decoded is not None
    assert parsed.qr_decoded[QR_TAG_SELLER_NAME] == fixtures.SELLER_NAME


def test_absent_icv_pih_and_qr_are_false_not_errors() -> None:
    invoice = parse_ubl_invoice(fixtures.build_ubl_xml(include_icv_pih=False, include_qr=False))
    assert invoice.has_icv is False
    assert invoice.has_pih is False
    assert invoice.qr_base64 is None
    assert invoice.qr_decoded is None
    # Absence must not damage the rest of the parse.
    assert invoice.id == "SA-2026-0334"


def test_malformed_xml_raises() -> None:
    with pytest.raises(MalformedXMLError):
        parse_ubl_invoice(b"<Invoice><unclosed>")


def test_xxe_entity_is_not_resolved(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Uploaded XML is untrusted: external entities must never be expanded."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-TRN", encoding="utf-8")
    hostile = f"""<?xml version="1.0"?>
<!DOCTYPE Invoice [<!ENTITY xxe SYSTEM "file://{secret.as_posix()}">]>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>&xxe;</cbc:ID>
</Invoice>""".encode()
    try:
        invoice = parse_ubl_invoice(hostile)
    except MalformedXMLError:
        return  # Rejecting outright is also an acceptable outcome.
    assert invoice.id != "TOP-SECRET-TRN"


def test_to_extracted_fields_tags_provenance(parsed) -> None:  # type: ignore[no-untyped-def]
    fields = parsed.to_extracted_fields()
    assert isinstance(fields["seller_trn"], ExtractedField)
    assert fields["seller_trn"].value == fixtures.SELLER_TRN
    assert fields["total_amount"].value == "52118.00"
    for field in fields.values():
        assert field.source == "ubl_xml"
        assert field.confidence == 1.0


# --------------------------------------------------------------------------- #
# 3. decode_zatca_qr
# --------------------------------------------------------------------------- #
def test_decodes_phase_one_text_tags() -> None:
    decoded = decode_zatca_qr(fixtures.build_qr_base64())
    assert decoded[QR_TAG_SELLER_NAME] == fixtures.SELLER_NAME
    assert decoded[QR_TAG_VAT_NUMBER] == fixtures.SELLER_TRN
    assert decoded[QR_TAG_TOTAL_WITH_VAT] == fixtures.QR_TOTAL_WITH_VAT
    assert decoded[QR_TAG_VAT_TOTAL] == fixtures.QR_VAT_TOTAL


def test_crypto_tags_stay_raw_bytes() -> None:
    """Tags 6-9 are decoded, never interpreted or verified."""
    decoded = decode_zatca_qr(fixtures.build_qr_base64())
    for tag, expected_len in (
        (QR_TAG_XML_HASH, 32),
        (QR_TAG_SIGNATURE, 64),
        (QR_TAG_PUBLIC_KEY, 77),
        (QR_TAG_STAMP_SIGNATURE, 64),
    ):
        assert isinstance(decoded[tag], bytes)
        assert len(decoded[tag]) == expected_len


def test_phase_one_qr_without_crypto_tags() -> None:
    decoded = decode_zatca_qr(fixtures.build_qr_base64(include_crypto_tags=False))
    assert set(decoded) == {1, 2, 3, 4, 5}


def test_invalid_base64_raises() -> None:
    with pytest.raises(UBLError):
        decode_zatca_qr("not!valid!base64!")


def test_truncated_tlv_raises() -> None:
    import base64 as _b64

    payload = fixtures.build_tlv({1: b"ACME"})[:-2]  # chop the value short
    with pytest.raises(UBLError):
        decode_zatca_qr(_b64.b64encode(payload).decode("ascii"))


# --------------------------------------------------------------------------- #
# 4. validate_trn
#
# The rule used to reject a TRN whose 11th digit was not '1' — a constraint
# invented for this project, not a ZATCA one. A Saudi TRN's 11th digit is the
# first of three BRANCH digits (000 = head office), so that rule rejected
# every head-office registration, which is most of them. Restored to a real
# example on a real invoice: it was blocked by the old rule and should not be.
#
# What IS public and stable: 15 digits, a leading 3 (Saudi Arabia's country
# digit), a trailing 3. The check digit's algorithm (position 10) is not
# published anywhere, so there is nothing to verify there — "TRN_CHECKSUM" was
# always the wrong name for a check this code never actually made.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "trn",
    [
        "310122393500003",  # the official ZATCA documentation sample
        "399999999900003",  # head office (branch digits 000), synthetic, real-invoice shape
        "388888888800003",  # head office (branch digits 000), synthetic, real-invoice shape
        "311111111110003",
        " 310122393500003 ",
        "310-1223935-00003",
        "310122393520003",  # a non-head-office branch digit — the OLD rule
        # rejected this shape too (checked position 10, not just 10 == '1');
        # nothing published says a branch digit other than 0 is invalid.
    ],
)
def test_valid_trns(trn: str) -> None:
    assert validate_trn(trn) is True


@pytest.mark.parametrize(
    ("trn", "why"),
    [
        ("31012239350000", "14 digits, too short"),
        ("3101223935000034", "16 digits, too long"),
        ("410122393500003", "does not start with 3"),
        ("310122393500004", "does not end with 3"),
        ("31012239350000X", "contains a non-digit"),
        ("", "empty"),
        ("               ", "whitespace only"),
    ],
)
def test_invalid_trns(trn: str, why: str) -> None:
    assert validate_trn(trn) is False, why


# --------------------------------------------------------------------------- #
# 4b. trn_tax_type — informational only, never a validity verdict
# --------------------------------------------------------------------------- #
def test_tax_type_is_the_last_two_digits() -> None:
    assert trn_tax_type("399999999900003") == "03"
    assert trn_tax_type("310122393520003") == "03"


def test_tax_type_is_none_for_a_malformed_trn() -> None:
    """Nothing to report on a TRN that is not even shaped like one."""
    assert trn_tax_type("not a trn") is None
    assert trn_tax_type("") is None


# --------------------------------------------------------------------------- #
# 5. Real samples
# --------------------------------------------------------------------------- #
@pytest.mark.xfail(
    reason="no real ZATCA sample yet — synthetic fixtures only prove a round trip "
    "against our own pypdf writer, not that we can read certified e-invoicing output",
    strict=False,
)
def test_a_real_zatca_sample_exists() -> None:
    """Fails until a genuine compliant invoice lands in samples/.

    Deliberately visible in the test report. See samples/README.md.
    """
    compliant = [s for s in SAMPLES if s.expects_embedded_xml is True]
    assert compliant, "drop a compliant PDF/A-3 into samples/ (see samples/README.md)"


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_sample_step_zero_matches_its_classification(sample: Sample) -> None:
    """Real samples must land exactly where their filename says. No skipping."""
    xml = extract_embedded_xml(sample.path.read_bytes())

    if sample.expects_embedded_xml is True:
        assert xml is not None, (
            f"{sample.name} is named as a compliant UBL sample but no embedded "
            f"XML was found. Either Step Zero is broken or the file is misnamed."
        )
        invoice = parse_ubl_invoice(xml)
        assert invoice.id or invoice.uuid, (
            f"{sample.name} yielded XML that parsed to neither an ID nor a UUID."
        )
    elif sample.expects_embedded_xml is False:
        assert xml is None, f"{sample.name} is named as a plain scan but embedded XML was found."
    else:
        # Unclassified: assert only that it does not blow up.
        if xml is not None:
            parse_ubl_invoice(xml)
