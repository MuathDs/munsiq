"""Find and decode the ZATCA QR code printed on an invoice page.

Every Saudi tax invoice must carry a QR code holding a base64 TLV payload
(ZATCA Phase 1 tags 1-5: seller name, seller VAT number, timestamp, total
including VAT, VAT). A B2C simplified invoice has no embedded XML, so this QR is
the only machine-readable copy of those five values — and it is read here
deterministically, without a model, the same way Step Zero reads the XML.

Everything runs locally: the page is rasterized with PyMuPDF and scanned with
OpenCV's QR detector, which RapidOCR already installs (checked: it loads under
this machine's WDAC policy). Nothing is sent anywhere.

Only a COMPLETE payload is trusted: all of tags 1-5 present, and the two amounts
parse as numbers. A store's link QR, a truncated TLV or random base64 is
ignored rather than half-used. Tags 6-9 (Phase 2 signatures) are not verified —
that is ZATCA's job on the reporting side, not a receiver's.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import pymupdf

from app.config import get_settings
from app.services.ubl import (
    QR_TAG_SELLER_NAME,
    QR_TAG_TIMESTAMP,
    QR_TAG_TOTAL_WITH_VAT,
    QR_TAG_VAT_NUMBER,
    QR_TAG_VAT_TOTAL,
    UBLError,
    decode_zatca_qr,
)
from app.services.validation.engine import to_decimal

logger = logging.getLogger(__name__)

_ISO_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class ZatcaQR:
    seller_name: str
    seller_trn: str
    timestamp: str
    total_with_vat: str
    vat_total: str
    page_number: int

    @property
    def issue_date(self) -> str | None:
        """The invoice date as the schema stores it (YYYY-MM-DD): the date part of
        the ISO 8601 timestamp in tag 3. None if the tag is not ISO-shaped."""
        match = _ISO_DATE_PREFIX.match(self.timestamp.strip())
        return match.group(1) if match else None


def parse_zatca_payload(text: str, page_number: int = 1) -> ZatcaQR | None:
    """A decoded QR string as a ZATCA payload, or None if it is not a complete one."""
    try:
        tags = decode_zatca_qr(text.strip())
    except UBLError:
        return None
    values = [
        tags.get(tag)
        for tag in (
            QR_TAG_SELLER_NAME,
            QR_TAG_VAT_NUMBER,
            QR_TAG_TIMESTAMP,
            QR_TAG_TOTAL_WITH_VAT,
            QR_TAG_VAT_TOTAL,
        )
    ]
    if not all(isinstance(v, str) and v.strip() for v in values):
        return None
    name, trn, timestamp, total, vat = (str(v).strip() for v in values)
    if to_decimal(total) is None or to_decimal(vat) is None:
        return None
    return ZatcaQR(name, trn, timestamp, total, vat, page_number)


def find_zatca_qr(pdf_bytes: bytes, *, dpi: int | None = None) -> ZatcaQR | None:
    """The first complete ZATCA QR on any page, scanning pages in order."""
    import cv2  # Imported here: only this path needs OpenCV.
    import numpy as np

    resolution = dpi or get_settings().QR_RASTER_DPI
    detectors: list[Any] = [cv2.QRCodeDetectorAruco(), cv2.QRCodeDetector()]
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        for page_number, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(dpi=resolution, colorspace=pymupdf.csGRAY)
            gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.stride
            )[:, : pixmap.width]
            for decoded in _decode_all(detectors, gray):
                qr = parse_zatca_payload(decoded, page_number)
                if qr is not None:
                    logger.info("qr.zatca_found", extra={"page": page_number})
                    return qr
    return None


def _decode_all(detectors: list[Any], image: Any) -> list[str]:
    """Every QR string any detector can read on the image, first detector first."""
    import cv2

    found: list[str] = []
    for detector in detectors:
        try:
            ok, texts, _points, _ = detector.detectAndDecodeMulti(image)
        except cv2.error:  # A detector failure must not fail the document.
            logger.warning("qr.detector_failed", exc_info=True)
            continue
        if ok:
            found.extend(t for t in texts if t and t not in found)
    return found
