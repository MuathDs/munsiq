"""Pydantic v2 models for extracted invoice data.

Two layers live here, and the distinction matters:

* ``UBLInvoice`` and friends are the *typed parse* of a UBL 2.1 document. Money is
  ``Decimal``, dates are ``date``/``time``. Nothing here is provenance-tagged
  because a UBL parse has exactly one provenance.

* ``ExtractedField[T]`` is the *provenance-tagged* wrapper every field carries
  once it reaches the database and the review UI, regardless of whether it came
  from signed XML, a vision model, an OCR rule, or a human. ``to_extracted_fields()``
  flattens a ``UBLInvoice`` into that shape with ``source="ubl_xml"`` and
  ``confidence=1.0`` — the values Phase 3 writes straight to ``extracted_fields``.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FieldSource = Literal["ubl_xml", "vlm", "ocr_rule", "human"]
"""Where a value came from. Drives the provenance badge in the review UI."""

VatCategory = Literal["S", "Z", "E", "O"]
"""ZATCA VAT category: Standard, Zero-rated, Exempt, Out-of-scope."""


class BoundingBox(BaseModel):
    """A box on a rendered page.

    Coordinates are normalized floats in 0.0-1.0, never pixels, so the frontend
    can overlay them on any render size with an SVG viewBox of "0 0 1 1".
    """

    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=0)
    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)


class ExtractedField[T](BaseModel):
    """One extracted value plus everything needed to judge whether to trust it."""

    value: T | None = None
    source: FieldSource
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox | None = None
    original_value: str | None = Field(
        default=None,
        description="The raw string as it appeared on the document, before normalization "
        "or human correction. Preserved so a reviewer can always see what was printed.",
    )


# --------------------------------------------------------------------------- #
# UBL 2.1 parse tree
# --------------------------------------------------------------------------- #
class UBLPartyAddress(BaseModel):
    street_name: str | None = None
    building_number: str | None = None
    city_name: str | None = None
    postal_zone: str | None = None
    country_code: str | None = None


class UBLParty(BaseModel):
    """AccountingSupplierParty or AccountingCustomerParty."""

    name: str | None = None
    trn: str | None = Field(
        default=None,
        description="VAT registration number from PartyTaxScheme/CompanyID.",
    )
    address: UBLPartyAddress | None = None


class UBLTaxSubtotal(BaseModel):
    taxable_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    category_id: str | None = Field(default=None, description="S / Z / E / O")
    percent: Decimal | None = None


class UBLLine(BaseModel):
    id: str | None = None
    invoiced_quantity: Decimal | None = None
    unit_code: str | None = None
    line_extension_amount: Decimal | None = None
    item_name: str | None = None
    price_amount: Decimal | None = None


class UBLMonetaryTotal(BaseModel):
    line_extension_amount: Decimal | None = None
    tax_exclusive_amount: Decimal | None = None
    tax_inclusive_amount: Decimal | None = None
    payable_amount: Decimal | None = None


class UBLInvoice(BaseModel):
    """A parsed ZATCA UBL 2.1 invoice."""

    uuid: str | None = None
    id: str | None = None
    issue_date: date | None = None
    issue_time: time | None = None
    invoice_type_code: str | None = None
    invoice_type_name: str | None = Field(
        default=None,
        description="The @name attribute on InvoiceTypeCode. ZATCA encodes the "
        "standard/simplified distinction and the transaction subtype here.",
    )
    document_currency_code: str | None = None

    supplier: UBLParty = Field(default_factory=UBLParty)
    customer: UBLParty = Field(default_factory=UBLParty)

    tax_amount: Decimal | None = None
    tax_subtotals: list[UBLTaxSubtotal] = Field(default_factory=list)
    monetary_total: UBLMonetaryTotal = Field(default_factory=UBLMonetaryTotal)
    lines: list[UBLLine] = Field(default_factory=list)

    # AdditionalDocumentReference markers. ICV is the invoice counter value and
    # PIH the previous-invoice hash; both are mandatory on standard Phase 2
    # invoices and their absence is a compliance signal, not a parse failure.
    icv: str | None = None
    pih: str | None = None
    has_icv: bool = False
    has_pih: bool = False

    qr_base64: str | None = None
    qr_decoded: dict[int, str] | None = Field(
        default=None,
        description="TLV tags 1-5 decoded as text. Tags 6-9 are cryptographic and "
        "are deliberately not surfaced here; see services.ubl.decode_zatca_qr.",
    )

    def to_extracted_fields(self) -> dict[str, ExtractedField[str]]:
        """Flatten to the provenance-tagged field map Phase 3 persists.

        Everything is stringified: ``extracted_fields.value_extracted`` is text,
        with typed forms living in ``value_normalized``. Values that came out of
        the signed UBL attachment get ``confidence=1.0`` because they are not a
        prediction — they were read, not inferred.
        """
        flat: dict[str, str | None] = {
            "invoice_uuid": self.uuid,
            "invoice_number": self.id,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "issue_time": self.issue_time.isoformat() if self.issue_time else None,
            "invoice_type_code": self.invoice_type_code,
            "invoice_type_name": self.invoice_type_name,
            "currency": self.document_currency_code,
            "seller_name": self.supplier.name,
            "seller_trn": self.supplier.trn,
            "buyer_name": self.customer.name,
            "buyer_trn": self.customer.trn,
            "vat_amount": _str(self.tax_amount),
            "subtotal": _str(self.monetary_total.tax_exclusive_amount),
            "total_amount": _str(self.monetary_total.tax_inclusive_amount),
            "payable_amount": _str(self.monetary_total.payable_amount),
            "line_extension_amount": _str(self.monetary_total.line_extension_amount),
        }
        return {
            key: ExtractedField[str](value=value, source="ubl_xml", confidence=1.0)
            for key, value in flat.items()
            if value is not None
        }


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


# --------------------------------------------------------------------------- #
# API response models
# --------------------------------------------------------------------------- #
class ProbeResponse(BaseModel):
    """Response for the temporary POST /api/v1/documents/probe endpoint."""

    filename: str | None = None
    size_bytes: int
    has_embedded_ubl: bool
    embedded_xml_bytes: int | None = None
    invoice: UBLInvoice | None = None
    parse_error: str | None = None
