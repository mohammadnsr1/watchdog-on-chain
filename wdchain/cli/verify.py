"""Verify one stored chunk + Merkle proof against a root. Prints VALID/INVALID, exits 0/1.

Example::

    wdchain-verify --store commitments/S1/store --digest 0x<chunk_digest> \\
        --proof proof.json --root 0x<merkle_root>

Checks, in order:
1. the chunk exists in the store, and its bytes hash to ``--digest`` (detects tampering);
2. ``leaf = keccak256(digest)`` folded with the proof equals ``--root``.

``--root`` is taken from the command line, never from the proof file: later it will come
from the chain. The proof file is the JSON printed by ``wdchain-prove`` (only its "proof"
list is used), or a bare JSON list of hex hashes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from ..evidence.merkle import chunk_digest, from_hex, leaf_from_digest, verify_proof
from ..evidence.store import ChunkNotFoundError, ContentStore, StoreError


def load_proof(path: Union[str, Path]) -> List[bytes]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(obj, dict):
        obj = obj.get("proof")
    if not isinstance(obj, list):
        raise ValueError("proof file must be a JSON list of hex hashes or an object with a 'proof' list")
    return [from_hex(h) for h in obj]


def verify_chunk(
    store_dir: Union[str, Path], digest: str, proof: Sequence[bytes], root: bytes
) -> Tuple[bool, str]:
    expected = from_hex(digest)
    try:
        data = ContentStore(store_dir).get(expected, verify=False)
    except ChunkNotFoundError as exc:
        return False, str(exc)
    if chunk_digest(data) != expected:
        return False, "stored chunk bytes do not hash to --digest (chunk tampered or corrupt)"
    if not verify_proof(proof, root, leaf_from_digest(expected)):
        return False, "Merkle proof does not lead from the chunk's leaf to --root"
    return True, "chunk bytes match --digest and the proof leads to --root"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wdchain-verify", description=__doc__.splitlines()[0])
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--digest", required=True, help="chunk digest (hex, 0x optional)")
    p.add_argument("--proof", required=True, type=Path, help="proof JSON from wdchain-prove")
    p.add_argument("--root", required=True, help="Merkle root to verify against (hex)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        proof = load_proof(args.proof)
        ok, reason = verify_chunk(args.store, args.digest, proof, from_hex(args.root))
    except (ValueError, StoreError, OSError) as exc:  # MerkleError and JSON errors are ValueErrors
        ok, reason = False, f"error: {exc}"
    print("VALID" if ok else "INVALID")
    print(reason, file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
