"""Split a WatchDog session directory into per-role, per-step evidence chunks.

Inputs (read-only)
------------------
A session directory (``WATCHDOG_SESSION_DIR``) containing:

* JSONL logs matched by ``--log-pattern`` (default :data:`DEFAULT_LOG_PATTERN`), e.g.
  ``events_watchdog.jsonl`` and ``mcp_calls_<role>.jsonl``. The regex's ``role`` named
  group, mapped through ``role_aliases``, gives the witness role. So
  ``events_watchdog.jsonl`` and ``mcp_calls_watchdog.jsonl`` are ``watchdog``,
  ``mcp_calls_executor.jsonl`` is ``executor``, ``events_executor_monitor.jsonl`` is
  ``executor_monitor``, and the skill-server logs ``events_{gripper,motion,scene}.jsonl``
  are ``backend``.
* Other top-level files (e.g. the recorder's own ``manifest.json``) are fingerprinted in
  the session index but not chunked. Sub-directories (``bag/``, ``orchestrator/``) are
  listed as not committed.
* Optionally, a frames directory (default ``frames/``). Frames belong to exactly one role,
  and that role must be given explicitly (``--frames-role``). The tool never guesses which
  witness captured them.

Chunks
------
* Every non-blank JSONL line is parsed strictly and canonicalized
  (:mod:`wdchain.evidence.canonical`). The canonical bytes form one chunk.
* Every frame file is one chunk (its raw bytes). Its time comes from the file name
  (``--frame-time-regex``).
* Chunks are ordered by ``(wall_time_iso, source path, line number)``. ``wall_time_iso``
  (UTC ISO-8601) is the only cross-process clock. ``timestamp_ns`` is per-process monotonic
  and is never read.

Steps
-----
Step boundaries are pluggable (:class:`StepSegmenter`):

* :class:`ByFieldSegmenter`: groups records by a step-id field (``--step-field``).
* :class:`ByWindowSegmenter`: fixed windows of ``--window-s`` seconds over ``wall_time_iso``.

Role separation
---------------
Executor and WatchDog are independent witnesses. Chunks carry the role of the file they
came from, segmentation is done per role, and :func:`build_steps` refuses any step that
mixes roles or drops chunks. Roles share only the clock: ``by_window`` uses one
session-wide origin so that window ``w000003`` covers the same interval for every role.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .canonical import CanonicalizationError, canonical_bytes, parse_json_strict
from .manifest import ChunkSource
from .merkle import EmptyStepError

# Defaults, checked against the imported WatchDog_V1 sessions (see README "Log field names").
# All of them can be overridden from the CLI.
DEFAULT_TIME_FIELD = "wall_time_iso"
# Real logs have no top-level step field. The task's step ids appear only in the executor's
# scene.begin_step / scene.end_step calls, as arguments.step_id.
DEFAULT_STEP_FIELD = "arguments.step_id"
DEFAULT_LOG_PATTERN = r"^(?:events|mcp_calls)_(?P<role>.+)\.jsonl$"
# events_{gripper,motion,scene}.jsonl are skill events from the robot-side MCP servers.
# They also exist in unguarded (S4) sessions where no WatchDog ran, so they are neither
# WatchDog nor executor testimony, and they are committed as their own role, "backend".
# events_executor_monitor.jsonl (S4) keeps its own role, "executor_monitor".
DEFAULT_ROLE_ALIASES = {"gripper": "backend", "motion": "backend", "scene": "backend"}
DEFAULT_FRAMES_DIR = "frames"
# Epoch seconds with a fraction (1767268800.250), or an integer epoch in s/ms/us/ns.
DEFAULT_FRAME_TIME_REGEX = r"(?P<ts>\d{10}\.\d+|\d{10,19})"
UNASSIGNED_STEP = "_unassigned"
MISSING_STEP_POLICIES = ("error", "unassigned")

StepId = Union[int, str]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_NS = 10**9
_ROLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_MISSING = object()


def _epoch_seconds(dt: datetime) -> int:
    return (dt - _EPOCH) // timedelta(seconds=1)


# Plausibility window for frame timestamps decoded from file names.
_MIN_FRAME_NS = _epoch_seconds(datetime(2000, 1, 1, tzinfo=timezone.utc)) * _NS
_MAX_FRAME_NS = _epoch_seconds(datetime(2100, 1, 1, tzinfo=timezone.utc)) * _NS


class ChunkingError(ValueError):
    """The session cannot be chunked as configured (bad input or configuration)."""


# --- time handling --------------------------------------------------------------------------


def parse_wall_time_ns(value: Any) -> int:
    """Parse a UTC ISO-8601 wall-clock string to integer nanoseconds since the Unix epoch.

    Accepts ``Z`` or ``+HH:MM`` offsets. A string with no offset is taken as UTC. Fractions
    are kept to nanosecond precision (digits past 9 are truncated). Uses exact integer
    arithmetic, no floats.
    """
    if not isinstance(value, str):
        raise ChunkingError(
            f"time value must be an ISO-8601 string, got {type(value).__name__}: {value!r}"
        )
    m = _ISO_RE.match(value.strip())
    if m is None:
        raise ChunkingError(f"not an ISO-8601 timestamp: {value!r}")
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            tzinfo=timezone.utc,
        )
    except ValueError as exc:
        raise ChunkingError(f"invalid timestamp {value!r}: {exc}") from exc
    seconds = _epoch_seconds(dt)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        seconds -= sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    frac_ns = int((frac or "").ljust(9, "0")[:9])
    return seconds * _NS + frac_ns


def ns_to_iso(ns: int) -> str:
    """Format nanoseconds since the epoch as ``YYYY-MM-DDTHH:MM:SS.fffffffffZ``."""
    secs, rem = divmod(int(ns), _NS)
    dt = _EPOCH + timedelta(seconds=secs)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{rem:09d}Z"


def parse_frame_time_ns(text: str) -> int:
    """Parse a timestamp taken from a frame file name.

    Accepts ISO-8601, epoch seconds with a fraction, or an integer epoch whose unit is
    inferred from its magnitude (s, ms, us, ns). Results outside 2000..2100 are rejected,
    so a frame counter or a compact date is never silently misread as a time.
    """
    text = text.strip()
    if _ISO_RE.match(text):
        ns = parse_wall_time_ns(text)
    else:
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ChunkingError(f"cannot parse frame timestamp {text!r}") from exc
        if not value.is_finite() or value < 0:
            raise ChunkingError(f"invalid frame timestamp {text!r}")
        if "." in text:
            ns = int(value * _NS)
        else:
            iv = int(value)
            if iv < 10**11:
                ns = iv * _NS
            elif iv < 10**14:
                ns = iv * 10**6
            elif iv < 10**17:
                ns = iv * 10**3
            else:
                ns = iv
    if not _MIN_FRAME_NS <= ns < _MAX_FRAME_NS:
        raise ChunkingError(
            f"frame timestamp {text!r} does not decode to a time between 2000 and 2100; "
            f"adjust --frame-time-regex"
        )
    return ns


def get_field(record: Mapping[str, Any], path: str, default: Any = _MISSING) -> Any:
    """Look up ``path`` in ``record``. A literal key wins; otherwise dots mean nesting."""
    if path in record:
        return record[path]
    cur: Any = record
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


# --- chunks and steps -----------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """One unit of evidence: a canonicalized JSONL record or a raw frame file."""

    role: str
    source: ChunkSource
    sort_path: str  # session-relative POSIX path of the source file (tie-breaker)
    line_index: int  # 1-based line number for JSONL records, 0 for frames
    time_ns: int
    time_iso: str
    payload: Optional[bytes] = field(default=None, repr=False)  # canonical record bytes
    path: Optional[Path] = None  # frame file (read lazily, frames can be large)
    record: Optional[Dict[str, Any]] = field(default=None, compare=False, repr=False)

    @property
    def sort_key(self) -> Tuple[int, str, int]:
        return (self.time_ns, self.sort_path, self.line_index)

    @property
    def is_frame(self) -> bool:
        return self.record is None

    def get_bytes(self) -> bytes:
        if self.payload is not None:
            return self.payload
        if self.path is None:
            raise ChunkingError(f"chunk {self.source} has neither payload nor path")
        return self.path.read_bytes()


@dataclass
class Step:
    role: str
    step_id: StepId
    chunks: List[Chunk]  # sorted by Chunk.sort_key

    @property
    def t_start(self) -> str:
        return self.chunks[0].time_iso

    @property
    def t_end(self) -> str:
        return max(self.chunks, key=lambda c: c.sort_key).time_iso


@dataclass
class SessionLayout:
    """How to find and interpret evidence inside a session directory."""

    time_field: str = DEFAULT_TIME_FIELD
    log_pattern: str = DEFAULT_LOG_PATTERN
    # Maps the (?P<role>...) value captured from a file name to the committed role.
    role_aliases: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROLE_ALIASES))
    frames_dir: Optional[str] = DEFAULT_FRAMES_DIR  # None disables frames
    frames_role: Optional[str] = None
    frame_time_regex: str = DEFAULT_FRAME_TIME_REGEX


@dataclass
class SourceFile:
    file: str
    role: str
    path: Path


@dataclass
class LoadedSession:
    session_dir: Path
    session_id: str
    chunks_by_role: Dict[str, List[Chunk]]
    log_files: List[SourceFile]
    frames: Optional[Dict[str, Any]]
    other_files: List[Path]  # top-level non-log files: fingerprinted, not chunked
    ignored: List[str]  # sub-directories and hidden frame files: not committed


def _check_role(role: str, where: str) -> str:
    if not _ROLE_RE.match(role):
        raise ChunkingError(
            f"{where}: role {role!r} is not a safe name (letters, digits, '.', '_', '-')"
        )
    return role


def read_jsonl_chunks(path: Path, rel: str, role: str, time_field: str) -> List[Chunk]:
    """Read one JSONL log into chunks. Blank lines are skipped, but line numbers are kept."""
    chunks: List[Chunk] = []
    raw = path.read_bytes()
    for lineno, line in enumerate(raw.split(b"\n"), start=1):
        if line.endswith(b"\r"):
            line = line[:-1]
        if lineno == 1 and line.startswith(b"\xef\xbb\xbf"):
            line = line[3:]  # UTF-8 BOM
        if not line.strip():
            continue
        where = f"{rel}:{lineno}"
        try:
            record = parse_json_strict(line)
            payload = canonical_bytes(record)
        except CanonicalizationError as exc:
            raise ChunkingError(f"{where}: {exc}") from exc
        if not isinstance(record, dict):
            raise ChunkingError(f"{where}: JSONL record must be a JSON object")
        t = get_field(record, time_field)
        if t is _MISSING:
            raise ChunkingError(
                f"{where}: record has no {time_field!r} field (set --time-field)"
            )
        try:
            ns = parse_wall_time_ns(t)
        except ChunkingError as exc:
            raise ChunkingError(f"{where}: {exc}") from exc
        chunks.append(
            Chunk(
                role=role,
                source=ChunkSource(rel, lineno),
                sort_path=rel,
                line_index=lineno,
                time_ns=ns,
                time_iso=t,
                payload=payload,
                record=record,
            )
        )
    return chunks


def read_frame_chunks(
    frames_dir: Path, rel_dir: str, role: str, time_regex: str, ignored: List[str]
) -> List[Chunk]:
    """One chunk per file under ``frames_dir`` (recursive). Hidden files are reported as ignored."""
    try:
        rx = re.compile(time_regex)
    except re.error as exc:
        raise ChunkingError(f"invalid --frame-time-regex {time_regex!r}: {exc}") from exc
    if "ts" not in rx.groupindex:
        raise ChunkingError("--frame-time-regex must contain a named group (?P<ts>...)")
    chunks: List[Chunk] = []
    for p in sorted(frames_dir.rglob("*"), key=lambda q: q.as_posix()):
        if not p.is_file():
            continue
        inner = p.relative_to(frames_dir).as_posix()
        if p.name.startswith("."):
            ignored.append(f"{rel_dir}/{inner}")
            continue
        m = rx.search(p.name)
        if m is None:
            raise ChunkingError(
                f"{rel_dir}/{inner}: cannot extract a timestamp from the file name with "
                f"--frame-time-regex {time_regex!r}"
            )
        try:
            ns = parse_frame_time_ns(m.group("ts"))
        except ChunkingError as exc:
            raise ChunkingError(f"{rel_dir}/{inner}: {exc}") from exc
        chunks.append(
            Chunk(
                role=role,
                source=ChunkSource(rel_dir, inner),
                sort_path=f"{rel_dir}/{inner}",
                line_index=0,
                time_ns=ns,
                time_iso=ns_to_iso(ns),
                path=p,
            )
        )
    return chunks


def load_session(
    session_dir: Union[str, Path],
    layout: Optional[SessionLayout] = None,
    session_id: Optional[str] = None,
) -> LoadedSession:
    """Read every evidence source of a session into per-role chunk lists (read-only)."""
    session_dir = Path(session_dir)
    if not session_dir.is_dir():
        raise ChunkingError(f"session directory not found: {session_dir}")
    layout = layout or SessionLayout()
    try:
        pattern = re.compile(layout.log_pattern)
    except re.error as exc:
        raise ChunkingError(f"invalid --log-pattern {layout.log_pattern!r}: {exc}") from exc
    if "role" not in pattern.groupindex:
        raise ChunkingError("--log-pattern must contain a named group (?P<role>...)")

    chunks_by_role: Dict[str, List[Chunk]] = {}
    log_files: List[SourceFile] = []
    other_files: List[Path] = []
    ignored: List[str] = []
    frames_rel = layout.frames_dir

    for p in sorted(session_dir.iterdir(), key=lambda q: q.name):
        if frames_rel is not None and p.name == frames_rel and p.is_dir():
            continue
        if p.is_dir():
            ignored.append(p.name + "/")
            continue
        m = pattern.match(p.name)
        if m is None:
            other_files.append(p)
            continue
        raw_role = m.group("role")
        role = _check_role(layout.role_aliases.get(raw_role, raw_role), p.name)
        chunks_by_role.setdefault(role, []).extend(
            read_jsonl_chunks(p, p.name, role, layout.time_field)
        )
        log_files.append(SourceFile(p.name, role, p))

    frames_info: Optional[Dict[str, Any]] = None
    if frames_rel is not None:
        fdir = session_dir / frames_rel
        if fdir.is_dir():
            if not layout.frames_role:
                raise ChunkingError(
                    f"found frames directory {frames_rel!r} but no frames role was given; "
                    f"pass --frames-role ROLE (the witness that captured them) or --no-frames"
                )
            role = _check_role(layout.frames_role, "--frames-role")
            frames = read_frame_chunks(fdir, frames_rel, role, layout.frame_time_regex, ignored)
            chunks_by_role.setdefault(role, []).extend(frames)
            frames_info = {"dir": frames_rel, "role": role, "count": len(frames)}

    if not any(chunks_by_role.values()):
        found = [p.name for p in other_files] + ignored
        raise ChunkingError(
            f"no evidence records found in {session_dir} (log pattern {layout.log_pattern!r}); "
            f"log files present: {[sf.file for sf in log_files]}; other entries: {found}"
        )
    return LoadedSession(
        session_dir=session_dir,
        session_id=session_id or session_dir.name,
        chunks_by_role=chunks_by_role,
        log_files=log_files,
        frames=frames_info,
        other_files=other_files,
        ignored=ignored,
    )


# --- step segmentation ----------------------------------------------------------------------


@dataclass
class Segmentation:
    steps: Dict[str, Dict[StepId, List[Chunk]]]  # role -> step_id -> chunks
    params: Dict[str, Any]  # recorded in session_index.json


class StepSegmenter(ABC):
    """Strategy that assigns every chunk of every role to a step."""

    name: str = ""

    @abstractmethod
    def segment(self, chunks_by_role: Mapping[str, Sequence[Chunk]]) -> Segmentation:
        """Return role -> step_id -> chunks. Every chunk must be assigned exactly once."""


def _normalize_step_id(value: Any, where: str, field_name: str) -> StepId:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ChunkingError(
            f"{where}: step field {field_name!r} must be an integer or string, got {value!r}"
        )
    if isinstance(value, str) and not value.strip():
        raise ChunkingError(f"{where}: step field {field_name!r} is an empty string")
    return value


class ByFieldSegmenter(StepSegmenter):
    """Group records by the value of a step-id field (dotted paths allowed).

    Records without the field are either an error (default) or go to step ``_unassigned``.
    Frames have no fields. A frame joins the step of its role whose record time span
    ``[t_start, t_end]`` contains the frame time (the earliest such step if spans overlap).
    A frame outside every span is handled like a missing field.
    """

    name = "by_field"

    def __init__(self, step_field: str = DEFAULT_STEP_FIELD, missing: str = "error"):
        if missing not in MISSING_STEP_POLICIES:
            raise ChunkingError(f"--missing-step must be one of {MISSING_STEP_POLICIES}")
        self.step_field = step_field
        self.missing = missing

    def _unassigned(self, where: str, what: str) -> StepId:
        if self.missing == "error":
            raise ChunkingError(
                f"{where}: {what}; use --missing-step unassigned, a different --step-field, "
                f"or --segment by_window"
            )
        return UNASSIGNED_STEP

    def segment(self, chunks_by_role: Mapping[str, Sequence[Chunk]]) -> Segmentation:
        out: Dict[str, Dict[StepId, List[Chunk]]] = {}
        for role, chunks in chunks_by_role.items():
            steps: Dict[StepId, List[Chunk]] = {}
            frames: List[Chunk] = []
            for c in chunks:
                if c.is_frame:
                    frames.append(c)
                    continue
                where = f"{c.source.file}:{c.source.line_or_frame}"
                value = get_field(c.record or {}, self.step_field)
                if value is _MISSING or value is None:
                    sid = self._unassigned(where, f"record has no {self.step_field!r} field")
                else:
                    sid = _normalize_step_id(value, where, self.step_field)
                steps.setdefault(sid, []).append(c)

            if frames:
                spans = sorted(
                    (
                        (min(c.time_ns for c in cs), max(c.time_ns for c in cs), str(sid), sid)
                        for sid, cs in steps.items()
                        if sid != UNASSIGNED_STEP
                    ),
                    key=lambda s: (s[0], s[1], s[2]),
                )
                for f in frames:
                    hit = next((s for s in spans if s[0] <= f.time_ns <= s[1]), None)
                    if hit is not None:
                        sid = hit[3]
                    else:
                        sid = self._unassigned(
                            f"{f.source.file}/{f.source.line_or_frame}",
                            f"frame time {f.time_iso} is outside every {role} step span",
                        )
                    steps.setdefault(sid, []).append(f)
            out[role] = steps
        return Segmentation(
            steps=out,
            params={
                "strategy": self.name,
                "step_field": self.step_field,
                "missing_step": self.missing,
            },
        )


class ByWindowSegmenter(StepSegmenter):
    """Fixed windows of ``window_s`` seconds over ``wall_time_iso``.

    The origin is the earliest chunk time across *all* roles. Only the clock is shared,
    and evidence is still committed per role. Step ids are ``w%06d`` (window index), and
    windows that contain no chunks produce no step.
    """

    name = "by_window"

    def __init__(self, window_s: Union[str, float, int, Decimal]):
        try:
            w = Decimal(str(window_s))
        except InvalidOperation as exc:
            raise ChunkingError(f"--window-s must be a number, got {window_s!r}") from exc
        if not w.is_finite() or w <= 0:
            raise ChunkingError(f"--window-s must be > 0, got {window_s!r}")
        self.window_s = w
        self.window_ns = int(w * _NS)
        if self.window_ns <= 0:
            raise ChunkingError("--window-s is smaller than 1 ns")

    def segment(self, chunks_by_role: Mapping[str, Sequence[Chunk]]) -> Segmentation:
        times = [c.time_ns for cs in chunks_by_role.values() for c in cs]
        params: Dict[str, Any] = {"strategy": self.name, "window_s": str(self.window_s)}
        if not times:
            return Segmentation(steps={r: {} for r in chunks_by_role}, params=params)
        origin = min(times)
        params["origin"] = ns_to_iso(origin)
        out: Dict[str, Dict[StepId, List[Chunk]]] = {}
        for role, chunks in chunks_by_role.items():
            steps: Dict[StepId, List[Chunk]] = {}
            for c in chunks:
                idx = (c.time_ns - origin) // self.window_ns
                steps.setdefault(f"w{idx:06d}", []).append(c)
            out[role] = steps
        return Segmentation(steps=out, params=params)


def make_segmenter(
    strategy: str,
    *,
    step_field: str = DEFAULT_STEP_FIELD,
    missing_step: str = "error",
    window_s: Optional[Union[str, float]] = None,
) -> StepSegmenter:
    if strategy == "by_field":
        return ByFieldSegmenter(step_field, missing_step)
    if strategy == "by_window":
        if window_s is None:
            raise ChunkingError("--segment by_window requires --window-s")
        return ByWindowSegmenter(window_s)
    raise ChunkingError(f"unknown segmentation strategy {strategy!r}")


def build_steps(
    chunks_by_role: Mapping[str, Sequence[Chunk]], segmenter: StepSegmenter
) -> Tuple[Dict[str, List[Step]], Dict[str, Any]]:
    """Segment and sort. Enforces the role-separation and no-dropped-evidence invariants.

    Returns ``(role -> steps ordered by time, segmentation params)``.
    """
    seg = segmenter.segment(chunks_by_role)
    unknown = set(seg.steps) - set(chunks_by_role)
    if unknown:
        raise ChunkingError(f"segmenter produced steps for unknown roles: {sorted(unknown)}")
    result: Dict[str, List[Step]] = {}
    for role in sorted(chunks_by_role):
        steps_map = seg.steps.get(role, {})
        n_in = len(chunks_by_role[role])
        n_out = sum(len(cs) for cs in steps_map.values())
        if n_in != n_out:
            raise ChunkingError(
                f"segmenter {segmenter.name} assigned {n_out} of {n_in} {role!r} chunks; "
                f"refusing to drop or duplicate evidence"
            )
        steps: List[Step] = []
        for sid, cs in steps_map.items():
            if not cs:
                raise EmptyStepError(
                    f"step {sid!r} of role {role!r} has no chunks: an empty step has no root"
                )
            foreign = sorted({c.role for c in cs if c.role != role})
            if foreign:
                raise ChunkingError(
                    f"role separation violated: step {sid!r} of role {role!r} contains "
                    f"chunks from roles {foreign}"
                )
            steps.append(Step(role, sid, sorted(cs, key=lambda c: c.sort_key)))
        steps.sort(key=lambda s: (s.chunks[0].time_ns, str(s.step_id)))
        result[role] = steps
    return result, seg.params
