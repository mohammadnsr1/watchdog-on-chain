"""Generate a Merkle proof for one chunk of a step manifest and print it as JSON.

Example::

    wdchain-prove --manifest commitments/S1/manifests/executor/3.json --chunk-index 0 > proof.json

The manifest's root is first recomputed from its chunk digests; a manifest whose root does
not match is rejected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..evidence.manifest import ManifestError, StepManifest
from ..evidence.merkle import MerkleError, from_hex, leaf_from_digest, to_hex


def build_proof_document(manifest: StepManifest, index: int) -> Dict[str, Any]:
    manifest.check_root()
    n = len(manifest.chunk_digests)
    if not 0 <= index < n:
        raise MerkleError(f"--chunk-index {index} out of range (manifest has {n} chunks)")
    digest = manifest.chunk_digests[index]
    return {
        "hash_scheme": manifest.hash_scheme,
        "session_id": manifest.session_id,
        "role": manifest.role,
        "step_id": manifest.step_id,
        "chunk_index": index,
        "chunk_source": manifest.chunk_sources[index].to_dict(),
        "chunk_digest": digest,
        "leaf": to_hex(leaf_from_digest(from_hex(digest))),
        "proof": [to_hex(h) for h in manifest.proof(index)],
        "merkle_root": manifest.merkle_root,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wdchain-prove", description=__doc__.splitlines()[0])
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--chunk-index", required=True, type=int)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = StepManifest.read(args.manifest)
        doc = build_proof_document(manifest, args.chunk_index)
    except (ManifestError, MerkleError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
