"""Deterministic repair of the totals block after extraction.

A simplified (B2C) tax invoice is tax-inclusive: it prints the total and the
VAT contained in it, and no subtotal at all. Asked for a subtotal, the model
copies the total into it — so subtotal == total while a positive VAT is stated,
which no real invoice can be (subtotal + VAT = total), and GRAND_TOTAL_MISMATCH
and VAT_CALC_MISMATCH then block a receipt that is perfectly consistent.

The guideline tells the model not to do this, but a prompt is a request, not a
guarantee. This is the guarantee: when the three numbers have exactly that
shape, the subtotal is derived as total - VAT (Decimal, two places) and marked
`computed`, so the review UI shows it was calculated rather than read. It is not
auto-validated — the derivation is only as right as the total and VAT it came
from, and a reviewer should see it once.

Signed XML is never touched, and nothing else is inferred: a null subtotal, a
zero VAT (a zero-rated invoice really has subtotal == total) or a VAT not below
the total are all left exactly as extracted.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.services.extraction.runner import ExtractedValue
from app.services.validation.engine import COMPUTED, money, to_decimal

__all__ = ["COMPUTED", "derive_tax_exclusive_subtotal"]

logger = logging.getLogger(__name__)

SUBTOTAL = "subtotal"
VAT_AMOUNT = "vat_amount"
TOTAL_AMOUNT = "total_amount"
MODEL_SOURCE = "vlm"


def derive_tax_exclusive_subtotal(values: list[ExtractedValue]) -> bool:
    """Replace a subtotal copied from the total with total - VAT, in place.

    Returns True when it changed the subtotal. Only a model-read subtotal is
    eligible; the condition is subtotal == total (as Decimals), VAT > 0 and
    total - VAT > 0.
    """
    header = {v.field_key: v for v in values if v.row_index is None}
    subtotal, vat, total = header.get(SUBTOTAL), header.get(VAT_AMOUNT), header.get(TOTAL_AMOUNT)
    if subtotal is None or vat is None or total is None or subtotal.source != MODEL_SOURCE:
        return False

    subtotal_amount = to_decimal(subtotal.value)
    vat_amount = to_decimal(vat.value)
    total_amount = to_decimal(total.value)
    if subtotal_amount is None or vat_amount is None or total_amount is None:
        return False
    if subtotal_amount != total_amount or vat_amount <= 0:
        return False
    derived: Decimal = money(total_amount - vat_amount)
    if derived <= 0:
        return False

    subtotal.original_value = subtotal.value
    subtotal.value = str(derived)
    subtotal.source = COMPUTED
    # Printed nowhere: the box the copied total was grounded to is the TOTAL's.
    subtotal.bbox = None
    # As trustworthy as the two amounts it was calculated from, and no more.
    subtotal.confidence = min(vat.confidence, total.confidence)
    subtotal.validation_state = "review_suggested"
    logger.info("extraction.subtotal_derived", extra={"from": "total_minus_vat"})
    return True
