"""Blob storage for uploaded files."""

from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)
        self._resolved = root.resolve()

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
            raise ValueError("invalid blob key")
        path = (self._resolved / key).resolve()
        if not path.is_relative_to(self._resolved):
            raise ValueError("invalid blob key")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError) as exc:
            raise KeyError(key) from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
