"""Deterministic sources applied after extraction: the ZATCA QR, then totals.

The QR is trusted like the signed XML. For the five fields it carries, its value
replaces the model's; the model's reading is kept as the field's shadow value
(and persisted as `model_value`) so QR_MODEL_MISMATCH can say when they
disagree. The model never overrides the QR. Signed XML still outranks both.

The subtotal is not in the QR, but its total and VAT are, so the subtotal
follows exactly as total - VAT, with provenance `computed`. Unlike the subtotal
`derive_tax_exclusive_subtotal` computes from two MODEL readings, both inputs
here are the QR's own, so it is settled rather than sent for review.
"""

from __future__ import annotations

import logging

from app.services.extraction.grounding import ground_value
from app.services.extraction.runner import ExtractedValue
from app.services.extraction.totals import derive_tax_exclusive_subtotal
from app.services.pagetext import PageText
from app.services.qr import ZatcaQR
from app.services.validation.engine import COMPUTED, QR, money, to_decimal

__all__ = ["COMPUTED", "QR", "apply_deterministic_sources", "apply_zatca_qr"]

logger = logging.getLogger(__name__)

UBL_SOURCE = "ubl_xml"
MODEL_SOURCE = "vlm"
SUBTOTAL = "subtotal"


def _qr_fields(qr: ZatcaQR) -> dict[str, str | None]:
    return {
        "seller_name": qr.seller_name,
        "seller_trn": qr.seller_trn,
        "issue_date": qr.issue_date,
        "total_amount": qr.total_with_vat,
        "vat_amount": qr.vat_total,
    }


def apply_zatca_qr(
    values: list[ExtractedValue], qr: ZatcaQR, *, pages: list[PageText]
) -> list[str]:
    """Overwrite the QR's fields (and derive the subtotal) in place.

    Only fields already in ``values`` — i.e. that the schema asks for — are
    touched; nothing is invented. Returns the keys it set.
    """
    header = {v.field_key: v for v in values if v.row_index is None}
    applied: list[str] = []
    for key, qr_value in _qr_fields(qr).items():
        entry = header.get(key)
        if entry is None or qr_value is None or entry.source == UBL_SOURCE:
            continue
        entry.shadow_value = entry.value if entry.source == MODEL_SOURCE else None
        entry.original_value = entry.value
        entry.value = qr_value
        entry.source = QR
        entry.confidence = 1.0
        entry.validation_state = "auto_validated"
        # WHERE it is printed, if it is — like a UBL value, the QR is the authority
        # either way and an unprinted value simply gets no box.
        entry.bbox = ground_value(qr_value, pages).bbox if pages else None
        applied.append(key)

    subtotal = header.get(SUBTOTAL)
    total, vat = to_decimal(qr.total_with_vat), to_decimal(qr.vat_total)
    if (
        subtotal is not None
        and subtotal.source != UBL_SOURCE
        and total is not None
        and vat is not None
    ):
        derived = money(total - vat)
        if derived > 0:
            subtotal.original_value = subtotal.value
            subtotal.value = str(derived)
            subtotal.source = COMPUTED
            subtotal.confidence = 1.0
            subtotal.validation_state = "auto_validated"
            subtotal.bbox = None
            subtotal.shadow_value = None
            applied.append(SUBTOTAL)

    logger.info("extraction.qr_applied", extra={"fields": len(applied), "page": qr.page_number})
    return applied


def apply_deterministic_sources(
    values: list[ExtractedValue], *, qr: ZatcaQR | None, pages: list[PageText]
) -> None:
    """Everything after the model that is decided without it, in precedence
    order: the QR, then a subtotal the model copied from the total. The pipeline,
    the benchmark and the eval-set scorer all call this one function."""
    if qr is not None:
        apply_zatca_qr(values, qr, pages=pages)
    derive_tax_exclusive_subtotal(values)
