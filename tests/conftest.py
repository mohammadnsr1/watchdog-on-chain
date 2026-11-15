"""Synthetic WatchDog session fixtures. No real data is used in tests."""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def iso(seconds: float) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def epoch(seconds: float) -> float:
    return BASE.timestamp() + seconds


def _write_jsonl(path: Path, records) -> None:
    # Deliberately non-canonical (spaces after separators, insertion key order).
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def write_session(root: Path, name: str, n_steps: int = 3, with_frames: bool = False) -> Path:
    """Create a fake session directory.

    Per step s (t0 = 10*s seconds):
      executor  mcp_calls_executor.jsonl : t0+0.1, t0+1.1, t0+2.1
      watchdog  mcp_calls_watchdog.jsonl : t0+0.6, t0+1.6
      watchdog  events_watchdog.jsonl    : t0+1.2 (verdict)
      frames/   (optional)               : t0+0.8
    ``timestamp_ns`` values are per-process and deliberately disagree with wall time
    across files (events have tiny values, calls huge ones).
    """
    d = root / name
    d.mkdir(parents=True)
    executor, wd_calls, wd_events = [], [], []
    for s in range(n_steps):
        t0 = 10 * s
        for k in range(3):
            executor.append({
                "wall_time_iso": iso(t0 + 0.1 + k),
                "timestamp_ns": 9_000_000_000_000 + s * 3 + k,
                "role": "executor",
                "step_id": s,
                "tool": "move_arm",
                "args": {"joint": k, "target": round(0.1 * k, 2)},
            })
        for k in range(2):
            wd_calls.append({
                "step_id": s,
                "role": "watchdog",
                "wall_time_iso": iso(t0 + 0.6 + k),
                "timestamp_ns": 5_000_000_000 + s * 2 + k,
                "tool": "inspect_scene",
                "args": {"camera": "front"},
            })
        wd_events.append({
            "role": "watchdog",
            "event": "verdict",
            "step_id": s,
            "verdict": "violation" if s == 1 else "ok",
            "wall_time_iso": iso(t0 + 1.2),
            "timestamp_ns": 10 + s,
        })
    _write_jsonl(d / "mcp_calls_executor.jsonl", executor)
    _write_jsonl(d / "mcp_calls_watchdog.jsonl", wd_calls)
    _write_jsonl(d / "events_watchdog.jsonl", wd_events)
    if with_frames:
        fd = d / "frames"
        fd.mkdir()
        for s in range(n_steps):
            t = epoch(10 * s + 0.8)
            (fd / f"frame_{t:.3f}.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-frame-" + str(s).encode())
    return d


@pytest.fixture
def make_session(tmp_path):
    counter = itertools.count()

    def _make(n_steps: int = 3, with_frames: bool = False, name: str = None) -> Path:
        return write_session(
            tmp_path / "sessions", name or f"session_synth_{next(counter)}", n_steps, with_frames
        )

    return _make
