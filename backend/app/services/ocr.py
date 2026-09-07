"""OCR engines behind one protocol.

OCR is the FALLBACK path. It runs only on pages with no text layer — see
app/services/pagetext.py for why.

Engine selection is ``settings.OCR_ENGINE``. Every engine declares
``supports_arabic`` honestly, because the pipeline surfaces that limitation to
the user rather than returning empty text as if the read had succeeded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.services.pagetext import Word

logger = logging.getLogger(__name__)


class OCRUnavailableError(Exception):
    """The configured engine could not be loaded."""


@dataclass
class OCRResult:
    words: list[Word] = field(default_factory=list)
    engine: str = "none"


class OCREngine(Protocol):
    name: str
    supports_arabic: bool

    def run(self, image_bytes: bytes) -> OCRResult: ...


class NullOCREngine:
    """Explicitly does nothing. For OCR_ENGINE="none" and for tests.

    Returns no words, so pagetext records the page as degraded rather than
    pretending it read something.
    """

    name = "none"
    supports_arabic = False

    def run(self, image_bytes: bytes) -> OCRResult:
        return OCRResult(engine=self.name)


class RapidOCREngine:
    """RapidOCR (ONNX Runtime).

    ARABIC IS NOT SUPPORTED. The bundled recogniser is ``ch_PP-OCRv4_rec``,
    whose character dictionary was inspected directly and contains 6280 CJK
    characters, 77 Latin, 10 digits and ZERO Arabic codepoints. It is not that
    Arabic accuracy is poor — the model cannot emit an Arabic character at all.

    That is why ``supports_arabic`` is False and why the pipeline raises a
    validation finding instead of silently returning empty text. To close the
    gap, supply an Arabic recognition model (RapidOCR accepts custom ONNX
    weights) or add a Tesseract engine with the `ara` traineddata.
    """

    name = "rapidocr"
    supports_arabic = False

    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - import guard
            raise OCRUnavailableError(f"rapidocr_onnxruntime is not installed: {exc}") from exc
        self._engine = RapidOCR()

    def run(self, image_bytes: bytes) -> OCRResult:
        from PIL import Image

        from app.services.normalize import normalize_text
        from app.services.pagetext import Word

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        result, _elapsed = self._engine(image)
        if not result:
            return OCRResult(engine=self.name)

        words: list[Word] = []
        for box, raw_text, _confidence in result:
            text = normalize_text(raw_text)
            if not text:
                continue
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            words.append(
                Word(
                    text=text,
                    original=raw_text,
                    x0=max(0.0, min(1.0, min(xs) / width)),
                    y0=max(0.0, min(1.0, min(ys) / height)),
                    x1=max(0.0, min(1.0, max(xs) / width)),
                    y1=max(0.0, min(1.0, max(ys) / height)),
                )
            )
        return OCRResult(words=words, engine=self.name)


_ENGINES: dict[str, OCREngine] = {}


def get_ocr_engine(name: str) -> OCREngine:
    """Return the configured engine, constructed once per process."""
    key = (name or "none").strip().lower()
    if key in _ENGINES:
        return _ENGINES[key]

    engine: OCREngine
    if key in {"none", ""}:
        engine = NullOCREngine()
    elif key == "rapidocr":
        engine = RapidOCREngine()
    else:
        raise OCRUnavailableError(f"unknown OCR_ENGINE: {name!r}")

    _ENGINES[key] = engine
    return engine
