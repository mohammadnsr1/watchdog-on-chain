"""Per-step, per-role evidence manifest and write-once JSON helpers.

One manifest is written per (role, step) to ``<out>/manifests/<role>/<step_id>.json``::

    {
      "session_id": "...",
      "role": "executor" | "watchdog" | ...,
      "step_id": 3 | "w000006" | ...,
      "t_start": "<wall_time_iso of first chunk>",
      "t_end": "<wall_time_iso of last chunk>",
      "contract_version": null,
      "hash_scheme": "keccak256-oz-sorted-v1",
      "chunk_digests": ["0x<keccak256(chunk_bytes)>", ...],
      "chunk_sources": [{"file": "...", "line_or_frame": 12}, ...],
      "merkle_root": "0x..."
    }

``chunk_digests[i]`` and ``chunk_sources[i]`` describe chunk ``i``. The Merkle leaves are
``keccak256(chunk_digest)`` in this order (see :mod:`wdchain.evidence.merkle`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .merkle import (
    HASH_SCHEME,
    EmptyStepError,
    MerkleError,
    chunk_digest,
    from_hex,
    leaf_from_digest,
    merkle_proof,
    merkle_root,
    to_hex,
)

StepIdValue = Union[int, str]

_REQUIRED_KEYS = (
    "session_id",
    "role",
    "step_id",
    "t_start",
    "t_end",
    "hash_scheme",
    "chunk_digests",
    "chunk_sources",
    "merkle_root",
)


class ManifestError(ValueError):
    """Malformed or inconsistent manifest."""


class ManifestConflictError(ManifestError):
    """A different manifest / index already exists at the target path."""


@dataclass(frozen=True)
class ChunkSource:
    """Where a chunk came from.

    JSONL record: ``file`` is the log file name, and ``line_or_frame`` is the 1-based line
    number. Frame: ``file`` is the frames directory, and ``line_or_frame`` is the frame path
    relative to it.
    """

    file: str
    line_or_frame: Union[int, str]

    def to_dict(self) -> Dict[str, Any]:
        return {"file": self.file, "line_or_frame": self.line_or_frame}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkSource":
        try:
            return cls(file=data["file"], line_or_frame=data["line_or_frame"])
        except (KeyError, TypeError) as exc:
            raise ManifestError(f"malformed chunk source: {data!r}") from exc


@dataclass
class StepManifest:
    session_id: str
    role: str
    step_id: StepIdValue
    t_start: str
    t_end: str
    chunk_digests: List[str]
    chunk_sources: List[ChunkSource]
    merkle_root: str
    contract_version: Optional[str] = None
    hash_scheme: str = HASH_SCHEME

    def __post_init__(self) -> None:
        if self.hash_scheme != HASH_SCHEME:
            raise ManifestError(
                f"unsupported hash_scheme {self.hash_scheme!r} (expected {HASH_SCHEME!r})"
            )
        if not self.chunk_digests:
            raise EmptyStepError(
                f"manifest for role {self.role!r} step {self.step_id!r} has no chunks: "
                f"an empty step has no Merkle root"
            )
        if len(self.chunk_digests) != len(self.chunk_sources):
            raise ManifestError(
                f"{len(self.chunk_digests)} chunk_digests but {len(self.chunk_sources)} chunk_sources"
            )
        try:
            self.chunk_digests = [to_hex(from_hex(d)) for d in self.chunk_digests]
            self.merkle_root = to_hex(from_hex(self.merkle_root))
        except MerkleError as exc:
            raise ManifestError(f"bad hash in manifest: {exc}") from exc
        self.chunk_sources = [
            s if isinstance(s, ChunkSource) else ChunkSource.from_dict(s) for s in self.chunk_sources
        ]

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        role: str,
        step_id: StepIdValue,
        t_start: str,
        t_end: str,
        chunk_digests: List[str],
        chunk_sources: List[ChunkSource],
        contract_version: Optional[str] = None,
    ) -> "StepManifest":
        """Build a manifest and compute its Merkle root from ``chunk_digests``."""
        leaves = [leaf_from_digest(from_hex(d)) for d in chunk_digests]
        root = merkle_root(leaves)  # raises EmptyStepError for no chunks
        return cls(
            session_id=session_id,
            role=role,
            step_id=step_id,
            t_start=t_start,
            t_end=t_end,
            chunk_digests=list(chunk_digests),
            chunk_sources=list(chunk_sources),
            merkle_root=to_hex(root),
            contract_version=contract_version,
        )

    # --- Merkle helpers -------------------------------------------------------------

    def leaves(self) -> List[bytes]:
        return [leaf_from_digest(from_hex(d)) for d in self.chunk_digests]

    def compute_root(self) -> bytes:
        """Root recomputed from ``chunk_digests`` (trusts the digests, not the store)."""
        return merkle_root(self.leaves())

    def check_root(self) -> None:
        """Raise :class:`ManifestError` if ``merkle_root`` does not match ``chunk_digests``."""
        if self.compute_root() != from_hex(self.merkle_root):
            raise ManifestError(
                f"manifest merkle_root {self.merkle_root} does not match its chunk_digests"
            )

    def proof(self, index: int) -> List[bytes]:
        return merkle_proof(self.leaves(), index)

    def recompute_root_from_store(self, store: Any) -> bytes:
        """Re-hash every chunk's *stored bytes* and rebuild the root.

        This does not trust the digest names. If any stored chunk was altered, the result
        differs from ``merkle_root``. ``store`` is a :class:`~wdchain.evidence.store.ContentStore`.
        """
        leaves = [
            leaf_from_digest(chunk_digest(store.get(d, verify=False))) for d in self.chunk_digests
        ]
        return merkle_root(leaves)

    # --- (de)serialization ------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "role": self.role,
            "step_id": self.step_id,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "contract_version": self.contract_version,
            "hash_scheme": self.hash_scheme,
            "chunk_digests": list(self.chunk_digests),
            "chunk_sources": [s.to_dict() for s in self.chunk_sources],
            "merkle_root": self.merkle_root,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepManifest":
        if not isinstance(data, dict):
            raise ManifestError("manifest must be a JSON object")
        missing = [k for k in _REQUIRED_KEYS if k not in data]
        if missing:
            raise ManifestError(f"manifest is missing keys: {missing}")
        return cls(
            session_id=data["session_id"],
            role=data["role"],
            step_id=data["step_id"],
            t_start=data["t_start"],
            t_end=data["t_end"],
            chunk_digests=list(data["chunk_digests"]),
            chunk_sources=[ChunkSource.from_dict(s) for s in data["chunk_sources"]],
            merkle_root=data["merkle_root"],
            contract_version=data.get("contract_version"),
            hash_scheme=data["hash_scheme"],
        )

    @classmethod
    def read(cls, path: Union[str, Path]) -> "StepManifest":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{path}: invalid JSON: {exc}") from exc
        return cls.from_dict(data)

    def write(self, path: Union[str, Path]) -> bool:
        return write_json_once(path, self.to_dict())


# --- write-once JSON files -----------------------------------------------------------------


def json_file_bytes(obj: Any) -> bytes:
    """Deterministic on-disk JSON: 2-space indent, insertion key order, UTF-8, trailing newline."""
    return (json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def ensure_writable_once(path: Union[str, Path], obj: Any) -> None:
    """Raise :class:`ManifestConflictError` if ``path`` exists with different content."""
    path = Path(path)
    if path.exists() and path.read_bytes() != json_file_bytes(obj):
        raise ManifestConflictError(
            f"{path} already exists with different content; refusing to overwrite "
            f"(commit into a fresh --out directory)"
        )


def write_json_once(path: Union[str, Path], obj: Any) -> bool:
    """Write ``obj`` to ``path`` unless an identical file exists. Never overwrites.

    Returns True if a new file was written and False if an identical one already existed.
    """
    path = Path(path)
    data = json_file_bytes(obj)
    ensure_writable_once(path, obj)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "xb") as fh:
            fh.write(data)
    except FileExistsError:
        ensure_writable_once(path, obj)
        return False
    return True
