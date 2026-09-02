"""Shared test configuration and real-sample discovery."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# Make `app` importable without an editable install, so `pytest` works straight
# out of a fresh venv on Windows.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent
SAMPLES_DIR = REPO_ROOT / "samples"

# Filename markers that declare what a sample is. See samples/README.md.
COMPLIANT_MARKERS = ("ubl", "compliant")
SCAN_MARKERS = ("scan", "plain")


@dataclass(frozen=True)
class Sample:
    """A real invoice on disk, plus what the tests are entitled to assert."""

    path: Path
    expects_embedded_xml: bool | None
    """True: must yield XML. False: must yield None. None: unclassified, best effort."""

    @property
    def name(self) -> str:
        return self.path.name


def _classify(path: Path) -> bool | None:
    stem = path.stem.lower()
    if any(marker in stem for marker in COMPLIANT_MARKERS):
        return True
    if any(marker in stem for marker in SCAN_MARKERS):
        return False
    return None


def discover_samples() -> list[Sample]:
    """Return every PDF in samples/, classified by filename convention."""
    if not SAMPLES_DIR.is_dir():
        return []
    return [
        Sample(path=path, expects_embedded_xml=_classify(path))
        for path in sorted(SAMPLES_DIR.glob("*.pdf"))
    ]


SAMPLES = discover_samples()
HAS_COMPLIANT_SAMPLE = any(s.expects_embedded_xml is True for s in SAMPLES)
HAS_SCAN_SAMPLE = any(s.expects_embedded_xml is False for s in SAMPLES)


@pytest.fixture(scope="session")
def samples() -> list[Sample]:
    return SAMPLES
