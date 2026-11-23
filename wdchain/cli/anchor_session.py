"""Anchor a committed session's step roots on-chain.

Reads ``<out>/session_index.json`` produced by ``wdchain-commit-session`` and sends one
transaction per batch of steps, per role. Executor roots are signed with the executor key and
WatchDog roots with the WatchDog key, so the two witnesses are attributable to different
addresses (CLAUDE.md rule 2).

Idempotent: steps that are already anchored are skipped, so re-running after an interruption
anchors only what is missing.

Example::

    wdchain-anchor-session --out commitments/20261007T205057Z --batch-size 25

Every transaction appends a row to ``<out>/anchor_log.csv``:
``session_id, role, n_steps, tx_hash, block, gas_used, wall_time_iso``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..chain.config import ChainConfigError, load_config
from ..chain.registry import HASH_SCHEME_ID, RegistryClient, Role, utc_now_iso

LOG_COLUMNS = ["session_id", "role", "n_steps", "tx_hash", "block", "gas_used", "wall_time_iso"]


def load_session_index(out_dir: Path) -> Dict[str, Any]:
    path = Path(out_dir) / "session_index.json"
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChainConfigError(
            f"{path} not found; commit the session first:\n"
            f"  wdchain-commit-session --session-dir <session> --out {out_dir}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ChainConfigError(f"{path}: invalid JSON: {exc}") from exc
    if index.get("hash_scheme") != HASH_SCHEME_ID:
        raise ChainConfigError(
            f"{path}: hash scheme is {index.get('hash_scheme')!r}, but this client anchors "
            f"{HASH_SCHEME_ID!r}. A different scheme needs a different id and its own verifier."
        )
    return index


def append_log_row(out_dir: Path, row: Dict[str, Any]) -> None:
    """Append one transaction to anchor_log.csv, writing the header if the file is new."""
    path = Path(out_dir) / "anchor_log.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wdchain-anchor-session", description=__doc__.splitlines()[0])
    p.add_argument("--out", required=True, type=Path,
                   help="commitment directory from wdchain-commit-session")
    p.add_argument("--batch-size", type=int, default=25,
                   help="steps per transaction (default: 25)")
    p.add_argument("--roles", nargs="*",
                   help="limit to these roles (default: every role the registry knows: "
                        f"{[r.name.lower() for r in Role]})")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be anchored and send nothing")
    p.add_argument("--rpc-url", help="overrides WDCHAIN_RPC_URL")
    p.add_argument("--registry-address", help="overrides deployments/anvil.json")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out)

    try:
        index = load_session_index(out_dir)
        session_id = index["session_id"]
        on_chain_roles = {r.name.lower() for r in Role}
        wanted = {r.lower() for r in args.roles} if args.roles else on_chain_roles

        # wdchain also produces 'backend' and 'executor_monitor' roles; the registry's enum has
        # only Executor and WatchDog, so those are reported and left off-chain.
        selected, skipped_roles = {}, []
        for role, entries in index.get("roles", {}).items():
            if role.lower() in wanted and role.lower() in on_chain_roles:
                selected[role] = entries
            else:
                skipped_roles.append(role)

        if not selected:
            print(f"error: no anchorable roles in {out_dir}/session_index.json "
                  f"(found {sorted(index.get('roles', {}))})", file=sys.stderr)
            return 2

        config = load_config(rpc_url=args.rpc_url, registry_address=args.registry_address,
                             require_keys=not args.dry_run)
        print(f"session   : {session_id}")
        print(f"scheme    : {index['hash_scheme']}")
        if skipped_roles:
            print(f"off-chain : {', '.join(sorted(skipped_roles))} (no on-chain role yet)")

        if args.dry_run:
            for role, entries in sorted(selected.items()):
                print(f"[{role}] would anchor {len(entries)} steps in "
                      f"{(len(entries) + args.batch_size - 1) // max(args.batch_size, 1)} transaction(s)")
            print("dry run: nothing sent")
            return 0

        client = RegistryClient(config)
        print(f"rpc       : {config.rpc_url}  chain {client.w3.eth.chain_id}")
        print(f"registry  : {client.address}")

        total_gas = 0
        total_steps = 0
        for role, entries in sorted(selected.items()):
            signer = client.address_for_role(role)
            print(f"\n[{role}] signer {signer}  {len(entries)} steps")

            pending: List[Dict[str, Any]] = []
            for entry in entries:
                step_id = str(entry["step_id"])
                if client.is_committed(session_id, role, step_id):
                    continue
                pending.append({"step_id": step_id, "root": entry["merkle_root"]})

            already = len(entries) - len(pending)
            if already:
                print(f"  {already} step(s) already anchored, skipped")
            if not pending:
                continue

            for start in range(0, len(pending), args.batch_size):
                batch = pending[start:start + args.batch_size]
                step_ids = [b["step_id"] for b in batch]
                roots = [b["root"] for b in batch]
                if len(batch) == 1:
                    result = client.commit(session_id, role, step_ids[0], roots[0])
                else:
                    result = client.commit_batch(session_id, role, step_ids, roots)
                if not result.ok:
                    print(f"  transaction {result.tx_hash} failed (status {result.status})",
                          file=sys.stderr)
                    return 1
                total_gas += result.gas_used
                total_steps += len(batch)
                print(f"  {len(batch):>4} steps  block {result.block_number:<6} "
                      f"gas {result.gas_used:>9}  {result.tx_hash}")
                append_log_row(out_dir, {
                    "session_id": session_id,
                    "role": role,
                    "n_steps": len(batch),
                    "tx_hash": result.tx_hash,
                    "block": result.block_number,
                    "gas_used": result.gas_used,
                    "wall_time_iso": utc_now_iso(),
                })

        print(f"\nanchored {total_steps} step(s), {total_gas} gas total")
        if total_steps:
            print(f"log: {out_dir / 'anchor_log.csv'}")
        return 0

    except ChainConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
