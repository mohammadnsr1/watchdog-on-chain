"""Merkle trees over evidence chunks, compatible with OpenZeppelin ``MerkleProof.verify``.

Hashing scheme ``keccak256-oz-sorted-v1``
-----------------------------------------
* Hash function: keccak256, Ethereum's original Keccak and NOT NIST SHA3-256
  (``eth_hash.auto.keccak``). Sanity value: keccak256(b"") =
  ``c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470``.
* ``chunk_digest = keccak256(chunk_bytes)``. This is the content address in the store.
* ``leaf = keccak256(chunk_digest)``. Hashing the 32-byte digest again means a leaf can
  never be reinterpreted as an internal node or a 64-byte pair (second-preimage defence).
* ``node = keccak256(min(a, b) || max(a, b))``. The pair is sorted by unsigned byte-wise
  comparison, the same as comparing ``bytes32`` values in Solidity. The operation is
  commutative, so proofs need no left/right flags.
* An odd node at the end of a level is carried up to the next level unchanged. It is not
  duplicated or hashed with itself.
* Zero leaves: there is no root, and :class:`EmptyStepError` is raised.
* A proof is the list of sibling hashes from the leaf level up to the top (bottom to top).
  A level where the node was carried up contributes no sibling.

On-chain check (later work)::

    bytes32 leaf = keccak256(abi.encodePacked(chunkDigest));   // chunkDigest is bytes32
    bool ok = MerkleProof.verify(proof, root, leaf);

``MerkleProof.verify`` folds the proof with the same sorted-pair hash, so trees built here
are accepted as is. Note that this is *not* OpenZeppelin's ``StandardMerkleTree`` JS layout,
which uses ``abi.encode`` leaves and a different tree shape. Only the verifier is shared.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from eth_hash.auto import keccak

HASH_SCHEME = "keccak256-oz-sorted-v1"
HASH_LEN = 32


class MerkleError(ValueError):
    """Malformed Merkle input (wrong hash length, bad hex, bad index)."""


class EmptyStepError(MerkleError):
    """A step with no chunks has no Merkle root."""


def keccak256(data: bytes) -> bytes:
    """keccak256 (Ethereum) of ``data``."""
    return keccak(bytes(data))


def _check32(value: bytes, what: str) -> bytes:
    if not isinstance(value, (bytes, bytearray)) or len(value) != HASH_LEN:
        got = len(value) if isinstance(value, (bytes, bytearray)) else type(value).__name__
        raise MerkleError(f"{what} must be {HASH_LEN} bytes, got {got}")
    return bytes(value)


def chunk_digest(chunk_bytes: bytes) -> bytes:
    """``keccak256(chunk_bytes)``: the chunk's content address."""
    return keccak256(chunk_bytes)


def leaf_from_digest(digest: bytes) -> bytes:
    """``keccak256(chunk_digest)``: the Merkle leaf for a chunk (double hash)."""
    return keccak256(_check32(digest, "chunk digest"))


def leaf_from_chunk(chunk_bytes: bytes) -> bytes:
    """``keccak256(keccak256(chunk_bytes))``."""
    return leaf_from_digest(chunk_digest(chunk_bytes))


def hash_pair(a: bytes, b: bytes) -> bytes:
    """``keccak256(min(a, b) || max(a, b))``: commutative internal-node hash."""
    a = _check32(a, "node")
    b = _check32(b, "node")
    return keccak256(a + b) if a <= b else keccak256(b + a)


def build_levels(leaves: Sequence[bytes]) -> List[List[bytes]]:
    """Return every tree level, ``levels[0]`` = leaves and ``levels[-1]`` = ``[root]``.

    Pairs are hashed left to right with :func:`hash_pair`. A trailing odd node is carried
    up unchanged. Raises :class:`EmptyStepError` for zero leaves.
    """
    if len(leaves) == 0:
        raise EmptyStepError(
            "cannot build a Merkle tree from zero leaves: an empty step has no root"
        )
    level = [_check32(leaf, "leaf") for leaf in leaves]
    levels = [level]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(hash_pair(level[i], level[i + 1]))
            else:
                nxt.append(level[i])  # odd node carried up unchanged
        levels.append(nxt)
        level = nxt
    return levels


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    """Root of the tree over ``leaves`` (a single leaf is its own root)."""
    return build_levels(leaves)[-1][0]


def merkle_proof(leaves: Sequence[bytes], index: int) -> List[bytes]:
    """Sibling hashes for ``leaves[index]``, bottom to top.

    Levels where the node is the carried-up odd node contribute no sibling, which matches
    how :func:`verify_proof` and OpenZeppelin ``processProof`` fold the proof.
    """
    if not 0 <= index < len(leaves):
        raise MerkleError(f"leaf index {index} out of range for {len(leaves)} leaves")
    levels = build_levels(leaves)
    proof: List[bytes] = []
    idx = index
    for level in levels[:-1]:
        sibling = idx ^ 1
        if sibling < len(level):
            proof.append(level[sibling])
        idx //= 2
    return proof


def process_proof(proof: Sequence[bytes], leaf: bytes) -> bytes:
    """Fold ``proof`` onto ``leaf`` with :func:`hash_pair` (OpenZeppelin ``processProof``)."""
    computed = _check32(leaf, "leaf")
    for sibling in proof:
        computed = hash_pair(computed, sibling)
    return computed


def verify_proof(proof: Sequence[bytes], root: bytes, leaf: bytes) -> bool:
    """True iff ``proof`` links ``leaf`` to ``root`` (OpenZeppelin ``MerkleProof.verify``)."""
    return process_proof(proof, leaf) == _check32(root, "root")


def to_hex(value: bytes) -> str:
    """``0x``-prefixed lowercase hex."""
    return "0x" + bytes(value).hex()


def from_hex(text: str, length: Optional[int] = HASH_LEN) -> bytes:
    """Parse hex with or without ``0x``. Checks the byte length unless ``length`` is None."""
    if not isinstance(text, str):
        raise MerkleError(f"expected a hex string, got {type(text).__name__}")
    s = text.strip()
    if s[:2].lower() == "0x":
        s = s[2:]
    try:
        value = bytes.fromhex(s)
    except ValueError as exc:
        raise MerkleError(f"not valid hex: {text!r}") from exc
    if length is not None and len(value) != length:
        raise MerkleError(f"expected {length} bytes of hex, got {len(value)}: {text!r}")
    return value
