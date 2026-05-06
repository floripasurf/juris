"""Abstract storage backend — local filesystem for v1, S3/MinIO for multi-tenant."""

from __future__ import annotations

import hashlib
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Metadata about a stored object."""

    key: str
    size: int
    sha256: str
    content_type: str


class StorageBackend(ABC):
    """Interface for object storage."""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        """Store an object. Returns metadata."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve an object by key."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if an object exists."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object."""

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


class LocalFileStorage(StorageBackend):
    """Filesystem-based storage. Paths mirror S3 key structure for easy migration."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Sanitize key to prevent directory traversal
        safe_key = Path(key)
        if ".." in safe_key.parts:
            msg = f"Invalid key (directory traversal): {key}"
            raise ValueError(msg)
        return self._root / safe_key

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(
            key=key,
            size=len(data),
            sha256=self._sha256(data),
            content_type=content_type,
        )

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            msg = f"Object not found: {key}"
            raise FileNotFoundError(msg)
        return path.read_bytes()

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def cleanup(self) -> None:
        """Remove all stored files. Use only in tests."""
        if self._root.exists():
            shutil.rmtree(self._root)
