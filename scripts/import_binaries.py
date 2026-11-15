#!/usr/bin/env python3
"""Copy the binary / large files listed in data/IMPORT_INVENTORY.md from WatchDog_V1.

Rules
-----
* The source (/home/mohammadnsr1/watchdog/WatchDog_V1) is opened read-only. Nothing in it is
  modified, moved, renamed or deleted. Paths that resolve outside it are refused.
* Destinations must lie under this repository's data/ directory.
* Existing destination files are NEVER overwritten. They are only hashed and compared.
* For every entry, the SHA-256 of the source and of the destination is printed with
  MATCH / MISMATCH.

Entries come from two marker-delimited tables in the inventory:

* BINARY_IMPORTS: copied by this script.
* TEXT_COPIES: copied by hand (byte-for-byte). By default they are only *verified* here.
  With --include-text, any of them that are missing at the destination are also copied.

Usage::

    python3 scripts/import_binaries.py --dry-run     # show the plan, copy nothing
    python3 scripts/import_binaries.py               # copy binaries, verify text copies
    python3 scripts/import_binaries.py --include-text

Exit status: 0 if every entry matches, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

SOURCE_ROOT = Path("/home/mohammadnsr1/watchdog/WatchDog_V1")
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"
DEFAULT_INVENTORY = DATA_ROOT / "IMPORT_INVENTORY.md"

BLOCKS = {
    "binary": ("<!-- BEGIN BINARY_IMPORTS -->", "<!-- END BINARY_IMPORTS -->"),
    "text": ("<!-- BEGIN TEXT_COPIES -->", "<!-- END TEXT_COPIES -->"),
}


def parse_block(text: str, begin: str, end: str) -> List[Tuple[str, str]]:
    """Return (source, destination) pairs from the markdown table between the markers."""
    if begin not in text or end not in text:
        raise SystemExit(f"inventory is missing marker {begin!r} or {end!r}")
    body = text.split(begin, 1)[1].split(end, 1)[0]
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or not cells[0] or cells[0].lower().startswith("source"):
            continue
        if re.fullmatch(r":?-{3,}:?", cells[0]):
            continue
        rows.append((cells[0], cells[1]))
    return rows


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_pair(src_s: str, dst_s: str) -> Tuple[Path, Path]:
    src = Path(src_s)
    if not src.is_absolute():
        src = SOURCE_ROOT / src
    src_real = src.resolve()
    if not _inside(src_real, SOURCE_ROOT.resolve()):
        raise ValueError(f"source {src_s} resolves outside {SOURCE_ROOT}")
    dst = Path(dst_s)
    if not dst.is_absolute():
        dst = REPO_ROOT / dst
    dst_parent_real = dst.parent.resolve()
    if not _inside(dst_parent_real, DATA_ROOT.resolve()) or ".." in dst.parts:
        raise ValueError(f"destination {dst_s} is not under {DATA_ROOT}")
    return src_real, dst


def copy_no_overwrite(src: Path, dst: Path) -> None:
    """Stream-copy src -> dst; never replaces an existing dst."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.importing")
    if tmp.exists():
        tmp.unlink()  # stale partial copy from an interrupted earlier run (ours, not source)
    try:
        with open(src, "rb") as fi, open(tmp, "xb") as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
            fo.flush()
            os.fsync(fo.fileno())
        try:
            os.link(tmp, dst)  # fails if dst appeared meanwhile; never overwrites
        except FileExistsError:
            raise
        except OSError:
            with open(tmp, "rb") as fi, open(dst, "xb") as fo:  # no hard-link support
                shutil.copyfileobj(fi, fo, 1 << 20)
    finally:
        if tmp.exists():
            tmp.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, copy nothing")
    ap.add_argument("--include-text", action="store_true",
                    help="also copy TEXT_COPIES entries that are missing at the destination")
    args = ap.parse_args()

    text = args.inventory.read_text(encoding="utf-8")
    entries = [("binary", s, d) for s, d in parse_block(text, *BLOCKS["binary"])]
    entries += [("text", s, d) for s, d in parse_block(text, *BLOCKS["text"])]
    if not entries:
        print("inventory lists no files; nothing to do")
        return 0

    failures = 0
    for kind, src_s, dst_s in entries:
        try:
            src, dst = resolve_pair(src_s, dst_s)
        except ValueError as exc:
            print(f"REFUSED  {exc}")
            failures += 1
            continue
        if not src.is_file():
            print(f"MISSING  source not found: {src}")
            failures += 1
            continue

        may_copy = kind == "binary" or args.include_text
        if dst.exists() or dst.is_symlink():
            action = "exists (not overwritten)"
        elif not may_copy:
            print(f"MISSING  {kind} copy not present: {dst.relative_to(REPO_ROOT)} "
                  f"(copy it by hand or rerun with --include-text)")
            failures += 1
            continue
        elif args.dry_run:
            print(f"PLAN     {kind}  {src}  ->  {dst.relative_to(REPO_ROOT)}  "
                  f"({src.stat().st_size} bytes)")
            continue
        else:
            try:
                copy_no_overwrite(src, dst)
                action = "copied"
            except FileExistsError:
                action = "exists (not overwritten)"

        h_src, h_dst = sha256(src), sha256(dst)
        status = "MATCH   " if h_src == h_dst else "MISMATCH"
        if h_src != h_dst:
            failures += 1
        print(f"{status} {kind}  {dst.relative_to(REPO_ROOT)}  [{action}]")
        print(f"         src sha256 {h_src}  {src}")
        print(f"         dst sha256 {h_dst}  {dst}")

    print(f"\n{len(entries)} entries, {failures} problem(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
