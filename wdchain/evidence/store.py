"""Content-addressed, write-once chunk store.

Layout: ``<store>/<hexdigest>``, where ``hexdigest`` is ``keccak256(chunk_bytes)`` as 64
lowercase hex characters with no ``0x``. The file content is exactly the chunk bytes.

Write-once rules:

* Writing bytes that are already stored under their digest is a no-op (idempotent).
* Writing *different* bytes where a file already exists raises
  :class:`StoreConflictError`, and the existing file is never overwritten. This includes
  the case where a stored chunk has been tampered with: the store reports it and does not
  "repair" it.
* New files are created atomically (temp file + hard link, or exclusive create) and set
  read-only (0444).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Union

from .merkle import HASH_LEN, MerkleError, chunk_digest, from_hex

Digest = Union[str, bytes]


class StoreError(RuntimeError):
    """Base class for store errors."""


class StoreConflictError(StoreError):
    """Different bytes already exist under this digest; the store never overwrites."""


class StoreIntegrityError(StoreError):
    """Bytes do not hash to the digest they are filed under."""


class ChunkNotFoundError(StoreError):
    """No chunk with this digest in the store."""


class ContentStore:
    """A directory of chunks named by their keccak256 digest."""

    def __init__(self, root: Union[str, Path]):
        self.root = Path(root)

    @staticmethod
    def normalize_digest(digest: Digest) -> str:
        """Return the digest as 64 lowercase hex characters (no ``0x``)."""
        if isinstance(digest, (bytes, bytearray)):
            if len(digest) != HASH_LEN:
                raise StoreError(f"digest must be {HASH_LEN} bytes, got {len(digest)}")
            return bytes(digest).hex()
        try:
            return from_hex(digest).hex()
        except MerkleError as exc:
            raise StoreError(f"invalid digest {digest!r}: {exc}") from exc

    def path_for(self, digest: Digest) -> Path:
        return self.root / self.normalize_digest(digest)

    def has(self, digest: Digest) -> bool:
        return self.path_for(digest).is_file()

    def put(self, data: bytes) -> str:
        """Store ``data`` under ``keccak256(data)`` and return that digest as hex (no ``0x``)."""
        data = bytes(data)
        digest = chunk_digest(data).hex()
        self.write_once(digest, data)
        return digest

    def write_once(self, digest: Digest, data: bytes) -> None:
        """Low-level write of ``data`` under ``digest``. Never overwrites.

        Raises :class:`StoreConflictError` if a file already exists under ``digest`` with
        different content, and :class:`StoreIntegrityError` if ``data`` does not hash to
        ``digest``.
        """
        data = bytes(data)
        path = self.path_for(digest)
        if path.exists():
            self._check_existing(path, data)
            return
        if chunk_digest(data).hex() != path.name:
            raise StoreIntegrityError(
                f"refusing to store bytes under {path.name}: they hash to {chunk_digest(data).hex()}"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "xb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o444)
            try:
                os.link(tmp, path)  # atomic, fails if path exists
            except FileExistsError:
                self._check_existing(path, data)
            except OSError:
                self._exclusive_write(path, data)  # filesystem without hard links
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def _exclusive_write(self, path: Path, data: bytes) -> None:
        try:
            with open(path, "xb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(path, 0o444)
        except FileExistsError:
            self._check_existing(path, data)

    @staticmethod
    def _check_existing(path: Path, data: bytes) -> None:
        if path.read_bytes() != data:
            raise StoreConflictError(
                f"{path} already exists with different content; the store is write-once "
                f"and will not overwrite it (if this is unexpected, the stored chunk may "
                f"have been tampered with)"
            )

    def get(self, digest: Digest, verify: bool = True) -> bytes:
        """Return the stored bytes. With ``verify``, check that they hash to ``digest``."""
        path = self.path_for(digest)
        if not path.is_file():
            raise ChunkNotFoundError(f"chunk {path.name} not found in store {self.root}")
        data = path.read_bytes()
        if verify and chunk_digest(data).hex() != path.name:
            raise StoreIntegrityError(
                f"stored chunk {path} does not hash to its name (tampered or corrupt)"
            )
        return data
