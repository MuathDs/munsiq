"""ZATCA "Step Zero" — the deterministic extraction path.

Under ZATCA Phase 2, a compliant Saudi tax invoice is a PDF/A-3 carrying the
UBL 2.1 XML as an embedded file attachment. That XML is authoritative: it is
what the seller cryptographically signed and reported to ZATCA. Reading it costs
no GPU, cannot hallucinate, and is exact.

So we always look for it first, before any model runs. Everything downstream
treats a ``source="ubl_xml"`` value as ground truth that a model may be compared
against but must never overwrite.

This module contains no OCR, no model and no database code, by design.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import date, time
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Final

from lxml import etree
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.schemas.invoice import (
    UBLInvoice,
    UBLLine,
    UBLMonetaryTotal,
    UBLParty,
    UBLPartyAddress,
    UBLTaxSubtotal,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MalformedPDFError",
    "MalformedXMLError",
    "UBLError",
    "decode_zatca_qr",
    "extract_embedded_xml",
    "parse_ubl_invoice",
    "validate_trn",
]


class UBLError(Exception):
    """Base class for Step Zero failures."""


class MalformedPDFError(UBLError):
    """The bytes given were not a readable PDF."""


class MalformedXMLError(UBLError):
    """The bytes given were not parseable XML."""


# --------------------------------------------------------------------------- #
# 1. Embedded attachment extraction
# --------------------------------------------------------------------------- #
_XML_PREFIXES: Final[tuple[bytes, ...]] = (b"<?xml", b"<Invoice", b"<ubl:Invoice")
_BOM: Final[bytes] = b"\xef\xbb\xbf"
_MAX_NAME_TREE_NODES: Final[int] = 1_000
"""Guard against a malicious or corrupt PDF with a cyclic name tree."""


def extract_embedded_xml(pdf_bytes: bytes) -> bytes | None:
    """Return the embedded UBL XML from a PDF, or None if there is none.

    Looks in both places the spec allows, because real-world generators disagree
    about which to use:

    1. The document catalog's ``/Names /EmbeddedFiles`` name tree — where PDF/A-3
       associated files normally live.
    2. Page-level ``/Annots`` of subtype ``/FileAttachment`` — used by several
       ZATCA-certified tools that attach the XML as a visible paperclip.

    Returns the first attachment whose filename ends in ``.xml`` or whose content
    starts with an XML declaration. Individual unreadable attachments are skipped
    rather than raising, so one broken entry cannot hide a good one.

    Raises:
        MalformedPDFError: the input was not a readable PDF at all.
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        catalog = reader.root_object
    except (PdfReadError, OSError, ValueError) as exc:
        raise MalformedPDFError(f"Could not read PDF: {exc}") from exc

    for name, data in _iter_catalog_attachments(catalog):
        if _looks_like_xml(name, data):
            logger.info("step_zero.attachment_found", extra={"location": "catalog"})
            return data

    for name, data in _iter_annotation_attachments(reader):
        if _looks_like_xml(name, data):
            logger.info("step_zero.attachment_found", extra={"location": "annots"})
            return data

    return None


def _looks_like_xml(name: str | None, data: bytes | None) -> bool:
    if not data:
        return False
    if name and name.lower().endswith(".xml"):
        return True
    head = data.lstrip(_BOM).lstrip()[:16]
    return head.startswith(_XML_PREFIXES)


def _iter_catalog_attachments(catalog: Any) -> list[tuple[str | None, bytes | None]]:
    """Walk /Names /EmbeddedFiles, descending through /Kids."""
    found: list[tuple[str | None, bytes | None]] = []
    try:
        names = catalog.get("/Names")
        if names is None:
            return found
        embedded = names.get_object().get("/EmbeddedFiles")
        if embedded is None:
            return found
        stack: list[Any] = [embedded.get_object()]
    except (AttributeError, KeyError, TypeError):
        return found

    visited = 0
    while stack and visited < _MAX_NAME_TREE_NODES:
        visited += 1
        node = stack.pop()
        try:
            if "/Kids" in node:
                stack.extend(kid.get_object() for kid in node["/Kids"])
                continue
            entries = node.get("/Names", [])
        except (AttributeError, KeyError, TypeError):
            continue

        # /Names is a flat [key1, value1, key2, value2, ...] array.
        for index in range(0, len(entries) - 1, 2):
            try:
                filename = str(entries[index])
                filespec = entries[index + 1].get_object()
            except (AttributeError, IndexError, TypeError):
                continue
            found.append((filename, _filespec_data(filespec)))
    return found


def _iter_annotation_attachments(reader: PdfReader) -> list[tuple[str | None, bytes | None]]:
    """Walk every page's /Annots for subtype /FileAttachment."""
    found: list[tuple[str | None, bytes | None]] = []
    for page in reader.pages:
        try:
            annots = page.get("/Annots")
            if annots is None:
                continue
            annot_list = annots.get_object()
        except (AttributeError, KeyError, TypeError):
            continue

        for annot_ref in annot_list:
            try:
                annot = annot_ref.get_object()
                if annot.get("/Subtype") != "/FileAttachment":
                    continue
                filespec = annot["/FS"].get_object()
            except (AttributeError, KeyError, TypeError):
                continue
            filename = filespec.get("/UF") or filespec.get("/F")
            found.append((str(filename) if filename else None, _filespec_data(filespec)))
    return found


def _filespec_data(filespec: Any) -> bytes | None:
    """Pull the decoded bytes out of a /Filespec's /EF stream."""
    try:
        embedded_file = filespec["/EF"].get_object()
    except (AttributeError, KeyError, TypeError):
        return None
    # /F is the classic key; /UF the Unicode one. Generators use either.
    for key in ("/F", "/UF"):
        stream = embedded_file.get(key)
        if stream is None:
            continue
        try:
            data = stream.get_object().get_data()
        # Broad by intent: one bad stream must not abort the walk.
        except Exception as exc:
            logger.warning("step_zero.attachment_unreadable", extra={"error": str(exc)})
            continue
        if isinstance(data, bytes):
            return data
    return None


# --------------------------------------------------------------------------- #
# 2. UBL 2.1 parsing
# --------------------------------------------------------------------------- #
NS: Final[dict[str, str]] = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}
"""Explicit namespace map. UBL is namespace-heavy and prefixes are not stable
across generators, so we never match on a prefix — only on a namespace URI."""

_ICV_REF: Final[str] = "ICV"
_PIH_REF: Final[str] = "PIH"
_QR_REF: Final[str] = "QR"


def parse_ubl_invoice(xml_bytes: bytes) -> UBLInvoice:
    """Parse ZATCA UBL 2.1 XML into a typed invoice.

    Money is ``Decimal`` throughout — never float. Missing elements yield None
    rather than raising: a UBL document that omits an optional field is valid,
    and deciding whether an absence is a compliance problem is the validation
    engine's job (Phase 5), not the parser's.

    Raises:
        MalformedXMLError: the bytes were not well-formed XML.
    """
    # Hardened parser. This XML arrives from an uploaded document, so it is
    # untrusted input: no entity resolution (blocks XXE / billion-laughs) and
    # no network access for external DTDs.
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
    )
    try:
        root = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise MalformedXMLError(f"Could not parse UBL XML: {exc}") from exc

    invoice = UBLInvoice(
        uuid=_text(root, "cbc:UUID"),
        id=_text(root, "cbc:ID"),
        issue_date=_date(_text(root, "cbc:IssueDate")),
        issue_time=_time(_text(root, "cbc:IssueTime")),
        invoice_type_code=_text(root, "cbc:InvoiceTypeCode"),
        invoice_type_name=_attr(root, "cbc:InvoiceTypeCode", "name"),
        document_currency_code=_text(root, "cbc:DocumentCurrencyCode"),
        supplier=_party(root, "cac:AccountingSupplierParty"),
        customer=_party(root, "cac:AccountingCustomerParty"),
        tax_amount=_decimal(_text(root, "cac:TaxTotal/cbc:TaxAmount")),
        tax_subtotals=_tax_subtotals(root),
        monetary_total=_monetary_total(root),
        lines=_lines(root),
    )

    _apply_document_references(root, invoice)
    return invoice


def _apply_document_references(root: etree._Element, invoice: UBLInvoice) -> None:
    """Read AdditionalDocumentReference entries for ICV, PIH and the QR code."""
    for ref in root.findall("cac:AdditionalDocumentReference", NS):
        ref_id = _text(ref, "cbc:ID")
        if ref_id == _ICV_REF:
            invoice.has_icv = True
            invoice.icv = _text(ref, "cbc:UUID")
        elif ref_id == _PIH_REF:
            invoice.has_pih = True
            invoice.pih = _text(ref, "cac:Attachment/cbc:EmbeddedDocumentBinaryObject")
        elif ref_id == _QR_REF:
            qr = _text(ref, "cac:Attachment/cbc:EmbeddedDocumentBinaryObject")
            invoice.qr_base64 = qr
            if qr:
                try:
                    decoded = decode_zatca_qr(qr)
                except UBLError as exc:
                    # A malformed QR is a compliance finding, not a parse failure.
                    logger.warning("step_zero.qr_undecodable", extra={"error": str(exc)})
                else:
                    invoice.qr_decoded = {
                        tag: value for tag, value in decoded.items() if isinstance(value, str)
                    }


def _party(root: etree._Element, path: str) -> UBLParty:
    node = root.find(f"{path}/cac:Party", NS)
    if node is None:
        return UBLParty()
    address_node = node.find("cac:PostalAddress", NS)
    address = None
    if address_node is not None:
        address = UBLPartyAddress(
            street_name=_text(address_node, "cbc:StreetName"),
            building_number=_text(address_node, "cbc:BuildingNumber"),
            city_name=_text(address_node, "cbc:CityName"),
            postal_zone=_text(address_node, "cbc:PostalZone"),
            country_code=_text(address_node, "cac:Country/cbc:IdentificationCode"),
        )
    return UBLParty(
        name=_text(node, "cac:PartyLegalEntity/cbc:RegistrationName")
        or _text(node, "cac:PartyName/cbc:Name"),
        trn=_text(node, "cac:PartyTaxScheme/cbc:CompanyID"),
        address=address,
    )


def _tax_subtotals(root: etree._Element) -> list[UBLTaxSubtotal]:
    subtotals: list[UBLTaxSubtotal] = []
    for node in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        subtotals.append(
            UBLTaxSubtotal(
                taxable_amount=_decimal(_text(node, "cbc:TaxableAmount")),
                tax_amount=_decimal(_text(node, "cbc:TaxAmount")),
                category_id=_text(node, "cac:TaxCategory/cbc:ID"),
                percent=_decimal(_text(node, "cac:TaxCategory/cbc:Percent")),
            )
        )
    return subtotals


def _monetary_total(root: etree._Element) -> UBLMonetaryTotal:
    node = root.find("cac:LegalMonetaryTotal", NS)
    if node is None:
        return UBLMonetaryTotal()
    return UBLMonetaryTotal(
        line_extension_amount=_decimal(_text(node, "cbc:LineExtensionAmount")),
        tax_exclusive_amount=_decimal(_text(node, "cbc:TaxExclusiveAmount")),
        tax_inclusive_amount=_decimal(_text(node, "cbc:TaxInclusiveAmount")),
        payable_amount=_decimal(_text(node, "cbc:PayableAmount")),
    )


def _lines(root: etree._Element) -> list[UBLLine]:
    lines: list[UBLLine] = []
    for node in root.findall("cac:InvoiceLine", NS):
        lines.append(
            UBLLine(
                id=_text(node, "cbc:ID"),
                invoiced_quantity=_decimal(_text(node, "cbc:InvoicedQuantity")),
                unit_code=_attr(node, "cbc:InvoicedQuantity", "unitCode"),
                line_extension_amount=_decimal(_text(node, "cbc:LineExtensionAmount")),
                item_name=_text(node, "cac:Item/cbc:Name"),
                price_amount=_decimal(_text(node, "cac:Price/cbc:PriceAmount")),
            )
        )
    return lines


def _text(node: etree._Element, path: str) -> str | None:
    found = node.find(path, NS)
    if found is None or found.text is None:
        return None
    stripped = found.text.strip()
    return stripped or None


def _attr(node: etree._Element, path: str, attribute: str) -> str | None:
    found = node.find(path, NS)
    if found is None:
        return None
    value = found.get(attribute)
    return value.strip() if value else None


def _decimal(raw: str | None) -> Decimal | None:
    """Parse money and quantities as Decimal. Never float — see CLAUDE.md."""
    if raw is None:
        return None
    try:
        return Decimal(raw.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        logger.warning("step_zero.undecodable_decimal", extra={"raw_length": len(raw)})
        return None


def _date(raw: str | None) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _time(raw: str | None) -> time | None:
    if raw is None:
        return None
    try:
        return time.fromisoformat(raw.strip().removesuffix("Z"))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 3. ZATCA QR (base64 TLV)
# --------------------------------------------------------------------------- #
QR_TAG_SELLER_NAME: Final[int] = 1
QR_TAG_VAT_NUMBER: Final[int] = 2
QR_TAG_TIMESTAMP: Final[int] = 3
QR_TAG_TOTAL_WITH_VAT: Final[int] = 4
QR_TAG_VAT_TOTAL: Final[int] = 5
QR_TAG_XML_HASH: Final[int] = 6
QR_TAG_SIGNATURE: Final[int] = 7
QR_TAG_PUBLIC_KEY: Final[int] = 8
QR_TAG_STAMP_SIGNATURE: Final[int] = 9

_TEXT_TAGS: Final[frozenset[int]] = frozenset(
    {
        QR_TAG_SELLER_NAME,
        QR_TAG_VAT_NUMBER,
        QR_TAG_TIMESTAMP,
        QR_TAG_TOTAL_WITH_VAT,
        QR_TAG_VAT_TOTAL,
    }
)


def decode_zatca_qr(b64: str) -> dict[int, str | bytes]:
    """Decode the base64 TLV payload from a ZATCA invoice QR code.

    Tags 1-5 are the Phase 1 human-readable fields (seller name, VAT number,
    timestamp, total with VAT, VAT total) and are returned as ``str``.

    Tags 6-9 are the Phase 2 cryptographic fields (XML hash, ECDSA signature,
    public key, stamp signature) and are returned as raw ``bytes``. We decode
    them so their presence can be asserted; we deliberately do NOT attempt to
    verify them. Signature verification is ZATCA's job, not ours — we are on the
    receiving side of the invoice.

    Raises:
        UBLError: the payload was not valid base64, or the TLV framing was
            inconsistent (a truncated or over-long value).
    """
    try:
        payload = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UBLError(f"QR payload is not valid base64: {exc}") from exc

    decoded: dict[int, str | bytes] = {}
    offset = 0
    length = len(payload)

    while offset < length:
        if offset + 2 > length:
            raise UBLError("Truncated TLV: tag/length header runs past end of payload")
        tag = payload[offset]
        value_length = payload[offset + 1]
        offset += 2
        end = offset + value_length
        if end > length:
            raise UBLError(f"Truncated TLV: tag {tag} declares {value_length} bytes past end")
        value = payload[offset:end]
        offset = end

        if tag in _TEXT_TAGS:
            decoded[tag] = value.decode("utf-8", errors="replace")
        else:
            decoded[tag] = value

    return decoded


# --------------------------------------------------------------------------- #
# 4. Saudi TRN validation
# --------------------------------------------------------------------------- #
TRN_LENGTH: Final[int] = 15
TRN_REQUIRED_PREFIX: Final[str] = "3"
TRN_REQUIRED_SUFFIX: Final[str] = "3"
TRN_VAT_TAX_TYPE: Final[str] = "03"
"""The last two digits are the registration's tax type; '03' is VAT. Not
enforced by ``validate_trn`` — see ``trn_tax_type``."""


def validate_trn(trn: str) -> bool:
    """Return True if ``trn`` is a structurally valid Saudi VAT registration number.

    THE RULE THIS REPLACES WAS WRONG. A Saudi TRN is documented as: 1 digit
    country code (3), 8 serial digits, 1 check digit, 3 branch digits (000 for
    the head office), 2 tax-type digits. An earlier version of this function
    additionally required the 11th digit — the FIRST BRANCH DIGIT — to be '1'.
    That digit is 0 for every head-office registration, so the old rule
    rejected most real Saudi companies; it blocked a real invoice's two
    otherwise-valid TRNs. There was never a ZATCA source for that constraint.

    So this checks only what is public and stable: 15 digits, starting and
    ending with 3. The check digit (position 10) has no published algorithm,
    so there is nothing to verify there — this was called "checksum" before
    and never actually computed one; see ``rules/zatca.py``'s TRN_FORMAT
    (renamed from TRN_CHECKSUM for the same reason). This proves the number is
    well-formed, not that it is registered to anyone.
    """
    candidate = trn.strip().replace(" ", "").replace("-", "")
    return (
        len(candidate) == TRN_LENGTH
        and candidate.isdigit()
        and candidate.startswith(TRN_REQUIRED_PREFIX)
        and candidate.endswith(TRN_REQUIRED_SUFFIX)
    )


def trn_tax_type(trn: str) -> str | None:
    """The last two digits (the registration's tax type), or None if malformed.

    Informational only — ``rules/zatca.py`` uses this for a WARNING when it is
    not '03' (VAT), never a validity verdict. A well-formed TRN with a
    different tax type (customs, excise, ...) is not wrong; it is just worth a
    second look on a VAT invoice.
    """
    if not validate_trn(trn):
        return None
    candidate = trn.strip().replace(" ", "").replace("-", "")
    return candidate[-2:]
