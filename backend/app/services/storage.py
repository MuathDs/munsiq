"""Object storage.

Local filesystem only in this phase — we have no Docker, so no MinIO. The
``Storage`` protocol exists so an S3 implementation can be added later without
touching a caller; that implementation is deliberately NOT built now.

Keys are namespaced per tenant from the first byte:

    {org_id}/documents/{document_id}/original.pdf
    {org_id}/documents/{document_id}/pages/{n}.webp
    {org_id}/documents/{document_id}/embedded.xml

so a future bucket layout matches this one exactly and no migration of key
shapes is needed.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class StorageError(Exception):
    """Raised when a key is unsafe or an object is missing."""


# A key is a plain relative path built from UUIDs and known suffixes. Anything
# else — absolute paths, drive letters, "..", backslashes — is rejected rather
# than sanitised, because a traversal here writes outside the tenant's tree.
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.\-]*$")


def _validate(key: str) -> str:
    if not _SAFE_KEY.match(key) or ".." in key.split("/"):
        raise StorageError(f"unsafe storage key: {key!r}")
    return key


def document_key(org_id: uuid.UUID, document_id: uuid.UUID, name: str) -> str:
    return _validate(f"{org_id}/documents/{document_id}/{name}")


def page_key(org_id: uuid.UUID, document_id: uuid.UUID, page_number: int) -> str:
    return _validate(f"{org_id}/documents/{document_id}/pages/{page_number}.webp")


class Storage(Protocol):
    """The seam an S3 backend would implement."""

    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...


class LocalStorage:
    """Filesystem-backed storage rooted at ``settings.STORAGE_DIR``.

    The root is git-ignored: uploaded invoices carry live TRNs and IBANs and
    must never enter the repository.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or get_settings().STORAGE_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _validate(key)).resolve()
        # Belt and braces: even with a validated key, confirm the resolved path
        # is inside the root before writing.
        if not path.is_relative_to(self.root):
            raise StorageError(f"key escapes storage root: {key!r}")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"no object at key: {key!r}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete_prefix(self, prefix: str) -> int:
        """Remove everything under a prefix. Used by document deletion."""
        base = self._path(prefix)
        if not base.exists():
            return 0
        removed = 0
        for path in sorted(base.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
                removed += 1
            elif path.is_dir():
                path.rmdir()
        base.rmdir()
        return removed


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = LocalStorage()
    return _storage
