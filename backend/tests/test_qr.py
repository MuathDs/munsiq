"""Reading the ZATCA QR printed on a page, and trusting it like the signed XML.

Every B2C simplified invoice must carry the ZATCA TLV QR (tags 1-5: seller
name, seller VAT number, timestamp, total incl. VAT, VAT). Decoding it gives
those five values exactly, without the model — the same way Step Zero reads the
embedded XML for B2B. All QR payloads and receipts here are synthetic.
"""

from __future__ import annotations

import base64

from app.services.extraction.qr_values import COMPUTED, QR, apply_zatca_qr
from app.services.extraction.runner import ExtractedValue
from app.services.qr import ZatcaQR, find_zatca_qr, parse_zatca_payload
from app.services.validation.engine import Severity
from tests import fixtures

EXPECTED = {
    "seller_name": fixtures.SELLER_NAME,
    "seller_trn": fixtures.SELLER_TRN,
    "issue_date": fixtures.QR_TIMESTAMP[:10],
    "total_amount": fixtures.QR_TOTAL_WITH_VAT,
    "vat_amount": fixtures.QR_VAT_TOTAL,
}


# --------------------------------------------------------------------------- #
# Reading the page
# --------------------------------------------------------------------------- #
def test_the_qr_on_a_receipt_is_found_and_decoded() -> None:
    qr = find_zatca_qr(fixtures.build_receipt_pdf_with_qr())

    assert qr is not None
    assert qr.seller_name == fixtures.SELLER_NAME
    assert qr.seller_trn == fixtures.SELLER_TRN
    assert qr.timestamp == fixtures.QR_TIMESTAMP
    assert qr.total_with_vat == fixtures.QR_TOTAL_WITH_VAT
    assert qr.vat_total == fixtures.QR_VAT_TOTAL
    assert qr.issue_date == "2026-02-10"
    assert qr.page_number == 1


def test_a_page_without_a_qr_yields_nothing() -> None:
    assert find_zatca_qr(fixtures.build_receipt_pdf_with_qr(qr_texts=())) is None


def test_a_qr_that_is_not_a_zatca_payload_is_ignored() -> None:
    """A store's website link is a QR too. It must not be mistaken for the
    invoice's own data."""
    pdf = fixtures.build_receipt_pdf_with_qr(qr_texts=("https://example.com/loyalty",))
    assert find_zatca_qr(pdf) is None


def test_the_zatca_qr_is_found_next_to_another_qr() -> None:
    pdf = fixtures.build_receipt_pdf_with_qr(
        qr_texts=("https://example.com/loyalty", fixtures.build_qr_base64())
    )
    qr = find_zatca_qr(pdf)
    assert qr is not None and qr.seller_trn == fixtures.SELLER_TRN


def test_a_payload_missing_the_amounts_is_rejected() -> None:
    """Tags 1-3 alone decode fine, but a QR that cannot say the total and VAT
    is not trusted with anything."""
    partial = base64.b64encode(
        fixtures.build_tlv({1: b"Seller", 2: fixtures.SELLER_TRN.encode(), 3: b"2026-02-10"})
    ).decode()
    assert parse_zatca_payload(partial) is None


def test_garbage_payloads_are_rejected_without_raising() -> None:
    assert parse_zatca_payload("not base64 at all!!") is None
    assert parse_zatca_payload(base64.b64encode(b"\x01\xff").decode()) is None  # truncated TLV
    assert parse_zatca_payload("") is None


def test_amounts_that_do_not_parse_are_rejected() -> None:
    payload = base64.b64encode(
        fixtures.build_tlv(
            {1: b"Seller", 2: fixtures.SELLER_TRN.encode(), 3: b"2026-02-10T10:00:00Z",
             4: b"lots", 5: b"some"}
        )
    ).decode()
    assert parse_zatca_payload(payload) is None


def test_a_timestamp_without_a_date_gives_no_issue_date() -> None:
    qr = ZatcaQR("S", fixtures.SELLER_TRN, "yesterday", "115.00", "15.00", page_number=1)
    assert qr.issue_date is None


# --------------------------------------------------------------------------- #
# Trusting it: the QR owns five fields, and the subtotal follows from two
# --------------------------------------------------------------------------- #
QR_READ = ZatcaQR(
    seller_name=fixtures.SELLER_NAME,
    seller_trn=fixtures.SELLER_TRN,
    timestamp=fixtures.QR_TIMESTAMP,
    total_with_vat=fixtures.QR_TOTAL_WITH_VAT,
    vat_total=fixtures.QR_VAT_TOTAL,
    page_number=1,
)


def model(key: str, value: str | None, source: str = "vlm") -> ExtractedValue:
    return ExtractedValue(
        field_key=key, value=value, source=source, confidence=0.9,
        validation_state="auto_validated", original_value=value,
    )


def model_reading() -> list[ExtractedValue]:
    """What a model might read off a tax-inclusive receipt: a copied subtotal,
    a misread VAT, a date in another format, and one field the QR cannot know."""
    return [
        model("invoice_number", "RC-2026-0077"),
        model("seller_name", "Al Jazeera Maintenance"),
        model("seller_trn", fixtures.SELLER_TRN),
        model("issue_date", "10/02/2026"),
        model("subtotal", "52118.00"),
        model("vat_amount", "6789.00"),
        model("total_amount", "52118.00"),
    ]


def by_key(values: list[ExtractedValue]) -> dict[str, ExtractedValue]:
    return {v.field_key: v for v in values}


def test_all_five_qr_fields_and_the_subtotal_come_from_the_qr() -> None:
    values = model_reading()

    applied = apply_zatca_qr(values, QR_READ, pages=[])

    fields = by_key(values)
    for key, expected in EXPECTED.items():
        assert (fields[key].value, fields[key].source) == (expected, QR), key
        assert fields[key].validation_state == "auto_validated"
        assert fields[key].confidence == 1.0
    assert (fields["subtotal"].value, fields["subtotal"].source) == ("45320.00", COMPUTED)
    assert sorted(applied) == sorted([*EXPECTED, "subtotal"])


def test_the_subtotal_derived_from_qr_values_is_settled() -> None:
    """Unlike a subtotal derived from two MODEL readings, both inputs here are the
    QR's own, so the derivation is exact and needs no second look."""
    values = model_reading()
    apply_zatca_qr(values, QR_READ, pages=[])
    subtotal = by_key(values)["subtotal"]
    assert subtotal.validation_state == "auto_validated" and subtotal.bbox is None


def test_the_model_never_overrides_the_qr_but_its_reading_is_kept() -> None:
    """Kept as the shadow value, which is what QR_MODEL_MISMATCH compares."""
    values = model_reading()
    apply_zatca_qr(values, QR_READ, pages=[])

    vat = by_key(values)["vat_amount"]
    assert vat.value == fixtures.QR_VAT_TOTAL
    assert vat.shadow_value == "6789.00"


def test_fields_the_qr_does_not_carry_are_untouched() -> None:
    values = model_reading()
    apply_zatca_qr(values, QR_READ, pages=[])
    invoice_number = by_key(values)["invoice_number"]
    assert (invoice_number.value, invoice_number.source) == ("RC-2026-0077", "vlm")


def test_signed_xml_still_outranks_the_qr() -> None:
    values = model_reading()
    values[2] = model("seller_trn", fixtures.SELLER_TRN, source="ubl_xml")

    apply_zatca_qr(values, QR_READ, pages=[])

    assert by_key(values)["seller_trn"].source == "ubl_xml"


def test_only_fields_the_schema_asks_for_are_filled() -> None:
    values = [model("total_amount", None), model("vat_amount", None)]

    applied = apply_zatca_qr(values, QR_READ, pages=[])

    assert sorted(applied) == ["total_amount", "vat_amount"]
    assert len(values) == 2, "no rows invented for fields the schema lacks"


# --------------------------------------------------------------------------- #
# QR_MODEL_MISMATCH — a disagreement is a warning, never a veto
# --------------------------------------------------------------------------- #
def test_a_model_disagreement_with_the_qr_is_a_warning_on_that_field() -> None:
    from app.services.validation.engine import FieldView, ValidationContext
    from app.services.validation.rules.provenance import qr_and_model_agree

    context = ValidationContext(
        fields={
            "vat_amount": FieldView("vat_amount", "6798.00", source=QR, shadow_value="6789.00"),
            "total_amount": FieldView("total_amount", "52118.00", source=QR, shadow_value="52118"),
            "issue_date": FieldView(
                "issue_date", "2026-02-10", source=QR, shadow_value="10/02/2026"
            ),
        },
        numeric_keys=frozenset({"vat_amount", "total_amount"}),
    )

    findings = qr_and_model_agree(context)

    assert findings is not None
    assert [(f.field_key, f.severity) for f in findings] == [("vat_amount", Severity.WARNING)]
    assert "6798.00" in findings[0].message_en and "6789.00" in findings[0].message_en


def test_the_mismatch_rule_is_not_applicable_without_qr_values() -> None:
    from app.services.validation.engine import FieldView, ValidationContext
    from app.services.validation.rules.provenance import qr_and_model_agree

    context = ValidationContext(fields={"vat_amount": FieldView("vat_amount", "1", source="vlm")})
    assert qr_and_model_agree(context) is None


def test_a_name_in_the_other_script_is_not_a_disagreement() -> None:
    """The QR carries the seller's Arabic legal name; a bilingual page often
    prints an English trading name too, and the model may return that. A name
    in another script is a translation, not a misread. The same script is
    still compared."""
    from app.services.validation.engine import FieldView, ValidationContext
    from app.services.validation.rules.provenance import qr_and_model_agree

    def check(model_read: str) -> list[str]:
        context = ValidationContext(
            fields={
                "seller_name": FieldView(
                    "seller_name", fixtures.SELLER_NAME, source=QR, shadow_value=model_read
                )
            }
        )
        findings = qr_and_model_agree(context)
        assert findings is not None, "compared, so applicable"
        return [f.field_key for f in findings]

    assert check("Al Jazeera Industrial Maintenance") == []
    assert check("شركة النخيل للتجارة") == ["seller_name"]
