"""Commit a session: chunks -> content store, per-role/per-step manifests, session index.

Output layout (``<out>``)::

    store/<hexdigest>                    chunk bytes, write-once
    manifests/<role>/<step_id>.json      one manifest per role per step
    session_index.json                   every step root per role + provenance

Nothing time-of-commit dependent is written, so committing the same session with the same
settings always produces byte-identical manifests and index. Existing files are never
overwritten: re-committing identical results is a no-op, and different results raise
before anything new is written.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .canonical import canonical_json
from .chunker import ChunkingError, SessionLayout, StepId, StepSegmenter, build_steps, load_session
from .manifest import StepManifest, ensure_writable_once, write_json_once
from .merkle import HASH_SCHEME, keccak256, to_hex
from .store import ContentStore

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def step_filename(step_id: StepId) -> str:
    """Filesystem-safe manifest name for a step id."""
    name = _UNSAFE.sub("_", str(step_id))
    if not name or name.startswith("."):
        name = "_" + name
    return name + ".json"


def commit_session(
    session_dir: Union[str, Path],
    out_dir: Union[str, Path],
    segmenter: StepSegmenter,
    layout: Optional[SessionLayout] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit one session directory (read-only) into ``out_dir`` and return the session index."""
    session_dir = Path(session_dir).resolve()
    out_dir = Path(out_dir).resolve()
    if out_dir == session_dir or session_dir in out_dir.parents:
        raise ValueError(
            f"--out {out_dir} is inside the session directory; sessions are read-only inputs"
        )
    layout = layout or SessionLayout()
    session = load_session(session_dir, layout, session_id)
    steps_by_role, seg_params = build_steps(session.chunks_by_role, segmenter)

    store = ContentStore(out_dir / "store")
    planned: List[Tuple[Path, Any]] = []
    roles_index: Dict[str, List[Dict[str, Any]]] = {}

    for role, steps in steps_by_role.items():
        names: Dict[str, StepId] = {}
        entries: List[Dict[str, Any]] = []
        for step in steps:
            digests = ["0x" + store.put(c.get_bytes()) for c in step.chunks]
            manifest = StepManifest.build(
                session_id=session.session_id,
                role=role,
                step_id=step.step_id,
                t_start=step.t_start,
                t_end=step.t_end,
                chunk_digests=digests,
                chunk_sources=[c.source for c in step.chunks],
            )
            fname = step_filename(step.step_id)
            if fname in names:
                raise ChunkingError(
                    f"step ids {names[fname]!r} and {step.step_id!r} of role {role!r} both map "
                    f"to manifest file {fname}"
                )
            names[fname] = step.step_id
            rel = f"manifests/{role}/{fname}"
            planned.append((out_dir / rel, manifest.to_dict()))
            entries.append(
                {
                    "step_id": step.step_id,
                    "merkle_root": manifest.merkle_root,
                    "t_start": manifest.t_start,
                    "t_end": manifest.t_end,
                    "n_chunks": len(step.chunks),
                    "manifest": rel,
                }
            )
        roles_index[role] = entries

    index: Dict[str, Any] = {
        "session_id": session.session_id,
        "hash_scheme": HASH_SCHEME,
        "canonical_json": "sorted-keys, compact separators, UTF-8, no NaN, no duplicate keys",
        "time_field": layout.time_field,
        "role_aliases": dict(sorted(layout.role_aliases.items())),
        "segmentation": seg_params,
        "source_files": [
            {
                "file": sf.file,
                "role": sf.role,
                "bytes": sf.path.stat().st_size,
                "keccak256": to_hex(keccak256(sf.path.read_bytes())),
            }
            for sf in session.log_files
        ],
        # Fingerprinted only (not chunked): e.g. the recorder's manifest.json, agent configs.
        "other_files": [
            {
                "file": p.name,
                "bytes": p.stat().st_size,
                "keccak256": to_hex(keccak256(p.read_bytes())),
            }
            for p in session.other_files
        ],
        "frames": session.frames,
        "not_committed": session.ignored,
        "roles": roles_index,
    }
    canonical_json(index)  # fail early on anything non-JSON
    planned.append((out_dir / "session_index.json", index))

    # Check every target first so a conflict leaves no partial new output behind.
    for path, obj in planned:
        ensure_writable_once(path, obj)
    for path, obj in planned:
        write_json_once(path, obj)
    return index
