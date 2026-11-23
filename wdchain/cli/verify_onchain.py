"""Verify one chunk off-chain and on-chain, and compare the two answers.

Builds the proof locally from the manifest, then:

1. **off-chain**: re-reads the chunk from the store, checks its bytes hash to the digest and
   folds the proof to the manifest's root (the same check as ``wdchain-verify``);
2. **on-chain**: calls ``EvidenceRegistry.verifyChunk`` against the root *anchored on the
   chain*, which is the root nobody can edit afterwards.

The two differ in an important case: if someone rewrote the local manifest and store together,
the off-chain check still passes while the on-chain check fails, because the anchored root no
longer matches. That is the tamper evidence the chain buys.

Example::

    wdchain-verify-onchain --manifest commitments/<S>/manifests/watchdog/w000000.json \\
        --store commitments/<S>/store --chunk-index 0

Exit status: 0 only if both checks pass and agree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..chain.config import ChainConfigError, load_config
from ..chain.registry import RegistryClient, Role, step_key_hex
from ..evidence.manifest import ManifestError, StepManifest
from ..evidence.merkle import MerkleError, chunk_digest, from_hex, leaf_from_digest, to_hex, verify_proof
from ..evidence.store import ContentStore, StoreError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wdchain-verify-onchain", description=__doc__.splitlines()[0])
    p.add_argument("--manifest", required=True, type=Path, help="step manifest JSON")
    p.add_argument("--store", required=True, type=Path, help="content-addressed chunk store")
    p.add_argument("--chunk-index", required=True, type=int)
    p.add_argument("--session-id", help="override the manifest's session id")
    p.add_argument("--rpc-url", help="overrides WDCHAIN_RPC_URL")
    p.add_argument("--registry-address", help="overrides deployments/anvil.json")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        manifest = StepManifest.read(args.manifest)
        n = len(manifest.chunk_digests)
        if not 0 <= args.chunk_index < n:
            print(f"error: --chunk-index {args.chunk_index} out of range (manifest has {n} chunks)",
                  file=sys.stderr)
            return 2

        session_id = args.session_id or manifest.session_id
        digest_hex = manifest.chunk_digests[args.chunk_index]
        digest = from_hex(digest_hex)
        proof = manifest.proof(args.chunk_index)
        role = Role.parse(manifest.role)

        print(f"session    : {session_id}")
        print(f"role       : {manifest.role} (on-chain Role.{role.name})")
        print(f"step       : {manifest.step_id}")
        print(f"chunk      : {args.chunk_index} of {n}")
        print(f"source     : {manifest.chunk_sources[args.chunk_index].to_dict()}")
        print(f"digest     : {digest_hex}")
        print(f"proof      : {len(proof)} sibling(s)")
        print(f"step key   : {step_key_hex(session_id, role, manifest.step_id)}")

        # --- off-chain --------------------------------------------------------------
        store = ContentStore(args.store)
        off_reason = ""
        try:
            data = store.get(digest, verify=False)
            if chunk_digest(data) != digest:
                off_ok, off_reason = False, "stored bytes do not hash to the manifest's digest"
            elif not verify_proof(proof, from_hex(manifest.merkle_root), leaf_from_digest(digest)):
                off_ok, off_reason = False, "proof does not lead to the manifest's root"
            else:
                off_ok, off_reason = True, "chunk bytes and proof match the local manifest root"
        except StoreError as exc:
            off_ok, off_reason = False, str(exc)

        print(f"\noff-chain  : {'VALID' if off_ok else 'INVALID'}  ({off_reason})")
        print(f"  local root   : {manifest.merkle_root}")

        # --- on-chain ---------------------------------------------------------------
        client = RegistryClient(load_config(rpc_url=args.rpc_url,
                                            registry_address=args.registry_address))
        record = client.get_commit(session_id, role, manifest.step_id)
        if not record.exists:
            print("\non-chain   : NOT ANCHORED  (no commit for this step)")
            print(f"  anchor it with:  wdchain-anchor-session --out {Path(args.manifest).parents[2]}")
            return 1

        on_ok = client.verify_chunk_onchain(session_id, role, manifest.step_id, digest, proof)
        print(f"\non-chain   : {'VALID' if on_ok else 'INVALID'}")
        print(f"  registry     : {client.address}")
        print(f"  anchored root: {record.root}")
        print(f"  committer    : {record.committer}")
        print(f"  block time   : {record.time}")

        roots_match = record.root.lower() == manifest.merkle_root.lower()
        if not roots_match:
            print("\n  !! the anchored root differs from the local manifest's root.")
            print("     The local commitment was rebuilt or edited after anchoring.")

        print()
        if off_ok and on_ok and roots_match:
            print("RESULT: VALID (both checks agree)")
            return 0
        if off_ok and not on_ok:
            print("RESULT: INVALID on-chain — the local evidence does not match what was anchored.")
        elif on_ok and not off_ok:
            print("RESULT: INVALID off-chain — the stored chunk is damaged, but the anchor stands.")
        else:
            print("RESULT: INVALID")
        return 1

    except (ManifestError, MerkleError, ChainConfigError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
