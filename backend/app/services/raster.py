"""PDF rasterization: one WebP per page, for the review UI's document pane."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pymupdf

from app.config import get_settings

logger = logging.getLogger(__name__)


class TooManyPagesError(Exception):
    """The document exceeds settings.MAX_PAGES."""


@dataclass(frozen=True)
class PageImage:
    page_number: int
    data: bytes
    width_px: int
    height_px: int


def rasterize(pdf_bytes: bytes) -> list[PageImage]:
    """Render every page to WebP.

    Width and height come back so the frontend can size its SVG overlay; the
    bounding boxes themselves are normalized 0.0-1.0 and need no pixel maths.

    Raises:
        TooManyPagesError: beyond the configured page cap.
    """
    settings = get_settings()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        if doc.page_count > settings.MAX_PAGES:
            raise TooManyPagesError(
                f"{doc.page_count} pages exceeds MAX_PAGES={settings.MAX_PAGES}"
            )

        images: list[PageImage] = []
        for index, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(dpi=settings.RASTER_DPI)
            images.append(
                PageImage(
                    page_number=index,
                    data=pixmap.pil_tobytes("WEBP", quality=settings.WEBP_QUALITY),
                    width_px=pixmap.width,
                    height_px=pixmap.height,
                )
            )
    return images


def rasterize_pages(
    pdf_bytes: bytes, page_numbers: frozenset[int], *, dpi: int, quality: int
) -> list[PageImage]:
    """Render only the given 1-based pages, at a DPI independent of RASTER_DPI.

    Separate from ``rasterize()`` on purpose: the review UI's page image and the
    vision model's input image are different consumers with different cost
    tradeoffs — a vision model's prompt cost scales with pixel count, so it gets
    its own (lower) DPI setting rather than reusing whatever the UI needs to look
    sharp. See ``VISION_RASTER_DPI`` in config.py.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        images: list[PageImage] = []
        for index, page in enumerate(doc, start=1):
            if index not in page_numbers:
                continue
            pixmap = page.get_pixmap(dpi=dpi)
            images.append(
                PageImage(
                    page_number=index,
                    data=pixmap.pil_tobytes("WEBP", quality=quality),
                    width_px=pixmap.width,
                    height_px=pixmap.height,
                )
            )
    return images
