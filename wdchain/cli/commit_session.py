"""Commit a WatchDog session directory: chunks -> content store + per-role, per-step manifests.

Examples::

    wdchain-commit-session --session-dir data/transcripts/sessions/20260901T204152Z \\
        --out commitments/20260901T204152Z --segment by_window --window-s 5

    wdchain-commit-session --session-dir <session> --out <out> \\
        --segment by_field --step-field arguments.step_id --missing-step unassigned

The session directory is only read. ``--out`` must be outside it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ..evidence.chunker import (
    DEFAULT_FRAME_TIME_REGEX,
    DEFAULT_FRAMES_DIR,
    DEFAULT_LOG_PATTERN,
    DEFAULT_ROLE_ALIASES,
    DEFAULT_STEP_FIELD,
    DEFAULT_TIME_FIELD,
    MISSING_STEP_POLICIES,
    SessionLayout,
    make_segmenter,
)
from ..evidence.commit import commit_session
from ..evidence.manifest import ManifestError
from ..evidence.merkle import MerkleError
from ..evidence.store import StoreError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wdchain-commit-session",
        description="Commit a WatchDog session (read-only) into a content store + manifests.",
    )
    p.add_argument("--session-dir", required=True, type=Path, help="WATCHDOG_SESSION_DIR")
    p.add_argument("--out", required=True, type=Path, help="output directory (outside the session)")
    p.add_argument("--session-id", help="session id (default: session directory name)")

    seg = p.add_argument_group("step segmentation")
    seg.add_argument("--segment", choices=["by_field", "by_window"], default="by_window",
                     help="default: by_window (the real logs carry no per-record step field)")
    seg.add_argument("--step-field", default=DEFAULT_STEP_FIELD,
                     help=f"by_field: record field holding the step id, dotted paths allowed "
                          f"(default: {DEFAULT_STEP_FIELD})")
    seg.add_argument("--missing-step", choices=MISSING_STEP_POLICIES, default="error",
                     help="by_field: what to do with records/frames that have no step "
                          "(default: error; 'unassigned' puts them in step _unassigned)")
    seg.add_argument("--window-s", default="5",
                     help="by_window: window length in seconds (default: 5)")

    lay = p.add_argument_group("session layout")
    lay.add_argument("--time-field", default=DEFAULT_TIME_FIELD,
                     help=f"UTC ISO-8601 wall-clock field (default: {DEFAULT_TIME_FIELD})")
    lay.add_argument("--log-pattern", default=DEFAULT_LOG_PATTERN,
                     help="regex for evidence log file names with a (?P<role>...) group "
                          f"(default: {DEFAULT_LOG_PATTERN})")
    lay.add_argument("--role-alias", action="append", default=[], metavar="NAME=ROLE",
                     help="map the role captured from a log file name to a committed role; "
                          "repeatable, overrides defaults "
                          f"({', '.join(f'{k}={v}' for k, v in DEFAULT_ROLE_ALIASES.items())}). "
                          "Use e.g. gripper=gripper to keep a server as its own role.")
    lay.add_argument("--frames-dir", default=DEFAULT_FRAMES_DIR,
                     help=f"frames sub-directory (default: {DEFAULT_FRAMES_DIR})")
    lay.add_argument("--frames-role",
                     help="role whose evidence the frames are (required if the frames dir exists)")
    lay.add_argument("--no-frames", action="store_true", help="do not commit frames")
    lay.add_argument("--frame-time-regex", default=DEFAULT_FRAME_TIME_REGEX,
                     help="regex with a (?P<ts>...) group applied to frame file names "
                          f"(default: {DEFAULT_FRAME_TIME_REGEX})")
    return p


def _parse_aliases(parser: argparse.ArgumentParser, items: List[str]) -> Dict[str, str]:
    aliases = dict(DEFAULT_ROLE_ALIASES)
    for item in items:
        name, sep, role = item.partition("=")
        if not sep or not name or not role:
            parser.error(f"--role-alias must look like NAME=ROLE, got {item!r}")
        aliases[name] = role
    return aliases


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    layout = SessionLayout(
        time_field=args.time_field,
        log_pattern=args.log_pattern,
        role_aliases=_parse_aliases(parser, args.role_alias),
        frames_dir=None if args.no_frames else args.frames_dir,
        frames_role=args.frames_role,
        frame_time_regex=args.frame_time_regex,
    )
    try:
        segmenter = make_segmenter(
            args.segment,
            step_field=args.step_field,
            missing_step=args.missing_step,
            window_s=args.window_s,
        )
        index = commit_session(args.session_dir, args.out, segmenter, layout, args.session_id)
    except (ValueError, ManifestError, MerkleError, StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"session {index['session_id']}  scheme {index['hash_scheme']}")
    for role, entries in index["roles"].items():
        n_chunks = sum(e["n_chunks"] for e in entries)
        print(f"[{role}] {len(entries)} steps, {n_chunks} chunks")
        for e in entries:
            print(f"  {e['step_id']!s:>12}  {e['n_chunks']:>6}  {e['merkle_root']}")
    if index["other_files"]:
        print(f"fingerprinted only: {', '.join(f['file'] for f in index['other_files'])}")
    if index["not_committed"]:
        print(f"not committed: {', '.join(index['not_committed'])}")
    print(f"index: {Path(args.out) / 'session_index.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
