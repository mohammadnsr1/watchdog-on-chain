"""Evidence commitment: canonical JSON, chunking, Merkle trees, content store, manifests."""

from .canonical import CanonicalizationError, canonical_bytes, canonical_json, parse_json_strict
from .merkle import (
    HASH_SCHEME,
    EmptyStepError,
    MerkleError,
    chunk_digest,
    hash_pair,
    leaf_from_chunk,
    leaf_from_digest,
    merkle_proof,
    merkle_root,
    verify_proof,
)
from .store import ContentStore, StoreConflictError, StoreError, StoreIntegrityError
from .manifest import ChunkSource, ManifestConflictError, ManifestError, StepManifest

__all__ = [
    "CanonicalizationError",
    "canonical_bytes",
    "canonical_json",
    "parse_json_strict",
    "HASH_SCHEME",
    "EmptyStepError",
    "MerkleError",
    "chunk_digest",
    "hash_pair",
    "leaf_from_chunk",
    "leaf_from_digest",
    "merkle_proof",
    "merkle_root",
    "verify_proof",
    "ContentStore",
    "StoreConflictError",
    "StoreError",
    "StoreIntegrityError",
    "ChunkSource",
    "ManifestConflictError",
    "ManifestError",
    "StepManifest",
]
