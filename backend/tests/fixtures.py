"""Synthetic test fixtures built in-process.

Read the caveat in samples/README.md before trusting these. A PDF built here is
attached with pypdf and read back with pypdf, so these tests prove our name-tree
walking and UBL parsing are self-consistent — not that we can read output from
ZATCA-certified e-invoicing software. Only a real sample proves that.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Final

import pymupdf
from pypdf import PdfWriter

# --------------------------------------------------------------------------- #
# ZATCA QR (base64 TLV)
# --------------------------------------------------------------------------- #
SELLER_NAME: Final[str] = "شركة الجزيرة للصيانة الصناعية"
SELLER_TRN: Final[str] = "310122393510003"
BUYER_NAME: Final[str] = "Jubail Maintenance Services Ltd."
BUYER_TRN: Final[str] = "311111111110003"
# Both TRNs above satisfy validate_trn: 15 digits, leading 3, trailing 3, and
# '1' in the 11th position. Keep them valid — Phase 5's TRN_CHECKSUM rule runs
# against this fixture, and a fixture that fails its own compliance rule makes
# every downstream test ambiguous.
QR_TIMESTAMP: Final[str] = "2026-02-10T11:35:00Z"
QR_TOTAL_WITH_VAT: Final[str] = "52118.00"
QR_VAT_TOTAL: Final[str] = "6798.00"


def build_tlv(values: dict[int, bytes]) -> bytes:
    """Encode a {tag: value} map as ZATCA single-byte-length TLV."""
    out = bytearray()
    for tag, value in values.items():
        if len(value) > 255:
            raise ValueError(f"Tag {tag} value exceeds the single-byte length field")
        out.append(tag)
        out.append(len(value))
        out.extend(value)
    return bytes(out)


def build_qr_base64(*, include_crypto_tags: bool = True) -> str:
    """Build a realistic ZATCA QR payload, base64-encoded."""
    values: dict[int, bytes] = {
        1: SELLER_NAME.encode("utf-8"),
        2: SELLER_TRN.encode("utf-8"),
        3: QR_TIMESTAMP.encode("utf-8"),
        4: QR_TOTAL_WITH_VAT.encode("utf-8"),
        5: QR_VAT_TOTAL.encode("utf-8"),
    }
    if include_crypto_tags:
        # Phase 2 cryptographic tags. Shapes are realistic; contents are not
        # real signatures and are never verified.
        values[6] = bytes(range(32))  # SHA-256 XML hash
        values[7] = bytes(range(64))  # ECDSA signature
        values[8] = bytes(range(77))  # public key
        values[9] = bytes(range(64))  # stamp signature
    return base64.b64encode(build_tlv(values)).decode("ascii")


# --------------------------------------------------------------------------- #
# UBL 2.1 XML
# --------------------------------------------------------------------------- #
def build_ubl_xml(
    *,
    invoice_id: str = "SA-2026-0334",
    invoice_uuid: str = "3cf5ee18-ee25-4ea6-8f6d-2b9d0a2b0f4c",
    type_code: str = "388",
    type_name: str = "0100000",
    include_qr: bool = True,
    include_icv_pih: bool = True,
) -> bytes:
    """Build a ZATCA-shaped UBL 2.1 invoice.

    Numbers are internally consistent: two lines totalling 45,320.00, 15% VAT of
    6,798.00, payable 52,118.00 — so the Phase 5 arithmetic rules will have
    something honest to check against.
    """
    refs = ""
    if include_icv_pih:
        refs += """
  <cac:AdditionalDocumentReference>
    <cbc:ID>ICV</cbc:ID>
    <cbc:UUID>17</cbc:UUID>
  </cac:AdditionalDocumentReference>
  <cac:AdditionalDocumentReference>
    <cbc:ID>PIH</cbc:ID>
    <cac:Attachment>
      <cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain"
        >NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzk=</cbc:EmbeddedDocumentBinaryObject>
    </cac:Attachment>
  </cac:AdditionalDocumentReference>"""
    if include_qr:
        refs += f"""
  <cac:AdditionalDocumentReference>
    <cbc:ID>QR</cbc:ID>
    <cac:Attachment>
      <cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain"
        >{build_qr_base64()}</cbc:EmbeddedDocumentBinaryObject>
    </cac:Attachment>
  </cac:AdditionalDocumentReference>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ProfileID>reporting:1.0</cbc:ProfileID>
  <cbc:ID>{invoice_id}</cbc:ID>
  <cbc:UUID>{invoice_uuid}</cbc:UUID>
  <cbc:IssueDate>2026-02-10</cbc:IssueDate>
  <cbc:IssueTime>11:35:00</cbc:IssueTime>
  <cbc:InvoiceTypeCode name="{type_name}">{type_code}</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode>
  <cbc:TaxCurrencyCode>SAR</cbc:TaxCurrencyCode>{refs}
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PostalAddress>
        <cbc:StreetName>طريق الملك فهد</cbc:StreetName>
        <cbc:BuildingNumber>1234</cbc:BuildingNumber>
        <cbc:CityName>الدمام</cbc:CityName>
        <cbc:PostalZone>32241</cbc:PostalZone>
        <cac:Country>
          <cbc:IdentificationCode>SA</cbc:IdentificationCode>
        </cac:Country>
      </cac:PostalAddress>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{SELLER_TRN}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>{SELLER_NAME}</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PostalAddress>
        <cbc:CityName>Jubail</cbc:CityName>
        <cac:Country>
          <cbc:IdentificationCode>SA</cbc:IdentificationCode>
        </cac:Country>
      </cac:PostalAddress>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{BUYER_TRN}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>{BUYER_NAME}</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="SAR">6798.00</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="SAR">45320.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="SAR">6798.00</cbc:TaxAmount>
      <cac:TaxCategory>
        <cbc:ID>S</cbc:ID>
        <cbc:Percent>15.00</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="SAR">45320.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="SAR">45320.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="SAR">52118.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="SAR">52118.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="PCE">2</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="SAR">40000.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Centrifugal pump</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="SAR">20000.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
  <cac:InvoiceLine>
    <cbc:ID>2</cbc:ID>
    <cbc:InvoicedQuantity unitCode="PCE">4</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="SAR">5320.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>صمام كروي 6 انش</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="SAR">1330.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>
""".encode()


# --------------------------------------------------------------------------- #
# PDFs
# --------------------------------------------------------------------------- #
def build_pdf_without_attachment(pages: int = 1) -> bytes:
    """A PDF carrying no embedded files — stands in for a plain scan."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_pdf_with_embedded_xml(
    xml_bytes: bytes | None = None,
    filename: str = "invoice.xml",
) -> bytes:
    """A PDF with UBL XML attached via the catalog /Names /EmbeddedFiles tree."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_attachment(filename, xml_bytes if xml_bytes is not None else build_ubl_xml())
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_pdf_with_non_xml_attachment() -> bytes:
    """A PDF whose only attachment is not XML — Step Zero must return None."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_attachment("terms.txt", b"Payment due within 30 days.")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_pdf_with_text_layer(
    lines: tuple[str, ...] = (
        "TAX INVOICE",
        "Invoice No: SA-2026-0334",
        "Seller: Al Jazeera Industrial Maintenance",
        "VAT No: 310122393510003",
        "Subtotal: 45320.00",
        "VAT 15%: 6798.00",
        "Total: 52118.00 SAR",
    ),
    font_path: str = r"C:\Windows\Fonts\arial.ttf",
) -> bytes:
    """A digital PDF with a real text layer — the common ZATCA-era case.

    No attachment, so Step Zero finds nothing and the model path runs.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 100
    for line in lines:
        page.insert_text((72, y), line, fontsize=12, fontfile=font_path, fontname="F0")
        y += 26
    buffer = BytesIO()
    doc.save(buffer)
    doc.close()
    return buffer.getvalue()
