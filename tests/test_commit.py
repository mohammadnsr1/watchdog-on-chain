import json
import os

import pytest

from wdchain.cli import commit_session as commit_cli
from wdchain.cli import prove as prove_cli
from wdchain.cli import verify as verify_cli
from wdchain.evidence.chunker import (
    ByFieldSegmenter,
    ByWindowSegmenter,
    ChunkingError,
    SessionLayout,
    parse_wall_time_ns,
)
from wdchain.evidence.commit import commit_session
from wdchain.evidence.manifest import ManifestConflictError, StepManifest
from wdchain.evidence.merkle import (
    chunk_digest,
    from_hex,
    leaf_from_digest,
    verify_proof,
)
from wdchain.evidence.store import ContentStore

FRAMES_LAYOUT = SessionLayout(frames_role="watchdog")


def _roots(index):
    return {
        role: [(e["step_id"], e["merkle_root"]) for e in entries]
        for role, entries in index["roles"].items()
    }


def _manifest_files(out):
    return sorted(p.relative_to(out) for p in (out / "manifests").rglob("*.json"))


# --- determinism ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make_segmenter",
    [lambda: ByFieldSegmenter("step_id"), lambda: ByWindowSegmenter(5)],
    ids=["by_field", "by_window"],
)
def test_commit_twice_gives_identical_roots(make_session, tmp_path, make_segmenter):
    s = make_session(with_frames=True)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    i1 = commit_session(s, out1, make_segmenter(), FRAMES_LAYOUT)
    i2 = commit_session(s, out2, make_segmenter(), FRAMES_LAYOUT)
    assert _roots(i1) == _roots(i2)
    assert (out1 / "session_index.json").read_bytes() == (out2 / "session_index.json").read_bytes()
    assert _manifest_files(out1) == _manifest_files(out2)
    for rel in _manifest_files(out1):
        assert (out1 / rel).read_bytes() == (out2 / rel).read_bytes()
    # re-committing into the same output is an idempotent no-op
    assert _roots(commit_session(s, out1, make_segmenter(), FRAMES_LAYOUT)) == _roots(i1)


def test_recommit_with_different_settings_refuses_to_overwrite(make_session, tmp_path):
    s = make_session()
    out = tmp_path / "out"
    commit_session(s, out, ByFieldSegmenter("step_id"))
    with pytest.raises(ManifestConflictError):
        commit_session(s, out, ByWindowSegmenter(5))
    assert not list((out / "manifests").rglob("w*.json"))


# --- role separation -----------------------------------------------------------------------


def test_role_separation(make_session, tmp_path):
    s = make_session(with_frames=True)
    out = tmp_path / "out"
    index = commit_session(s, out, ByFieldSegmenter("step_id"), FRAMES_LAYOUT)
    assert set(index["roles"]) == {"executor", "watchdog"}
    store = ContentStore(out / "store")
    allowed = {
        "executor": {"mcp_calls_executor.jsonl"},
        "watchdog": {"events_watchdog.jsonl", "mcp_calls_watchdog.jsonl", "frames"},
    }
    digests = {}
    for role, files in allowed.items():
        manifests = sorted((out / "manifests" / role).glob("*.json"))
        assert manifests
        digests[role] = set()
        for path in manifests:
            m = StepManifest.read(path)
            assert m.role == role
            assert {src.file for src in m.chunk_sources} <= files
            for d, src in zip(m.chunk_digests, m.chunk_sources):
                digests[role].add(d)
                if src.file != "frames":
                    assert json.loads(store.get(d))["role"] == role
    assert digests["executor"].isdisjoint(digests["watchdog"])


# --- ordering ------------------------------------------------------------------------------


def test_chunks_ordered_by_wall_time_not_timestamp_ns(make_session, tmp_path):
    s = make_session(with_frames=True)
    out = tmp_path / "out"
    commit_session(s, out, ByFieldSegmenter("step_id"), FRAMES_LAYOUT)
    m = StepManifest.read(out / "manifests" / "watchdog" / "0.json")
    # wall times: call 0.6s, frame 0.8s, verdict 1.2s, call 1.6s
    # (sorting by timestamp_ns would wrongly put the verdict first)
    assert [src.file for src in m.chunk_sources] == [
        "mcp_calls_watchdog.jsonl",
        "frames",
        "events_watchdog.jsonl",
        "mcp_calls_watchdog.jsonl",
    ]
    assert m.chunk_sources[0].line_or_frame == 1
    assert m.chunk_sources[3].line_or_frame == 2


def test_parse_wall_time():
    z = parse_wall_time_ns("2026-01-01T12:00:00Z")
    assert parse_wall_time_ns("2026-01-01T12:00:00+00:00") == z
    assert parse_wall_time_ns("2026-01-01T14:00:00+02:00") == z
    assert parse_wall_time_ns("2026-01-01T12:00:00.000000001Z") == z + 1


# --- segmentation --------------------------------------------------------------------------


def test_by_window_steps_share_a_session_clock(make_session, tmp_path):
    s = make_session(with_frames=True)
    index = commit_session(s, tmp_path / "out", ByWindowSegmenter(5), FRAMES_LAYOUT)
    assert [e["step_id"] for e in index["roles"]["executor"]] == ["w000000", "w000002", "w000004"]
    assert [e["step_id"] for e in index["roles"]["watchdog"]] == ["w000000", "w000002", "w000004"]
    assert index["segmentation"]["origin"].startswith("2026-01-01T12:00:00.1")


def test_missing_step_field(make_session, tmp_path):
    s = make_session()
    with open(s / "mcp_calls_executor.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"wall_time_iso": "2026-01-01T12:00:30.000000Z", "role": "executor"}) + "\n")
    with pytest.raises(ChunkingError):
        commit_session(s, tmp_path / "out1", ByFieldSegmenter("step_id"))
    index = commit_session(s, tmp_path / "out2", ByFieldSegmenter("step_id", missing="unassigned"))
    unassigned = [e for e in index["roles"]["executor"] if e["step_id"] == "_unassigned"]
    assert len(unassigned) == 1 and unassigned[0]["n_chunks"] == 1


def test_frames_require_explicit_role(make_session, tmp_path):
    s = make_session(with_frames=True)
    with pytest.raises(ChunkingError, match="frames-role"):
        commit_session(s, tmp_path / "out", ByFieldSegmenter("step_id"))
    index = commit_session(s, tmp_path / "out2", ByFieldSegmenter("step_id"), SessionLayout(frames_dir=None))
    assert index["frames"] is None


def test_out_inside_session_is_rejected(make_session):
    s = make_session()
    with pytest.raises(ValueError):
        commit_session(s, s / "out", ByFieldSegmenter("step_id"))


# --- tamper demo + CLIs --------------------------------------------------------------------


def test_tamper_one_byte_breaks_proof_and_root(make_session, tmp_path, capsys):
    s = make_session()
    out = tmp_path / "out"
    commit_session(s, out, ByFieldSegmenter("step_id"))
    manifest_path = out / "manifests" / "executor" / "1.json"
    m = StepManifest.read(manifest_path)
    idx = 1
    digest = m.chunk_digests[idx]
    store = ContentStore(out / "store")

    assert prove_cli.main(["--manifest", str(manifest_path), "--chunk-index", str(idx)]) == 0
    proof_doc = json.loads(capsys.readouterr().out)
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(proof_doc))
    verify_args = ["--store", str(out / "store"), "--digest", digest,
                   "--proof", str(proof_path), "--root", m.merkle_root]

    assert verify_cli.main(verify_args) == 0
    assert capsys.readouterr().out.strip() == "VALID"
    assert m.recompute_root_from_store(store) == from_hex(m.merkle_root)

    # flip one byte of the stored chunk
    chunk_file = store.path_for(digest)
    os.chmod(chunk_file, 0o644)
    data = bytearray(chunk_file.read_bytes())
    data[5] ^= 0x01
    chunk_file.write_bytes(bytes(data))

    assert verify_cli.main(verify_args) == 1
    assert capsys.readouterr().out.strip() == "INVALID"
    # even re-addressing the tampered bytes under their new digest does not help
    proof = [from_hex(h) for h in proof_doc["proof"]]
    assert not verify_proof(proof, from_hex(m.merkle_root), leaf_from_digest(chunk_digest(bytes(data))))
    assert m.recompute_root_from_store(store) != from_hex(m.merkle_root)


def test_verify_rejects_wrong_root(make_session, tmp_path, capsys):
    s = make_session()
    out = tmp_path / "out"
    commit_session(s, out, ByFieldSegmenter("step_id"))
    m0 = StepManifest.read(out / "manifests" / "executor" / "0.json")
    m1 = StepManifest.read(out / "manifests" / "executor" / "1.json")
    assert prove_cli.main(["--manifest", str(out / "manifests" / "executor" / "0.json"),
                           "--chunk-index", "0"]) == 0
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(capsys.readouterr().out)
    rc = verify_cli.main(["--store", str(out / "store"), "--digest", m0.chunk_digests[0],
                          "--proof", str(proof_path), "--root", m1.merkle_root])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "INVALID"


def test_real_log_shapes_roles_and_fingerprints(tmp_path):
    """Synthetic session shaped like the WatchDog_V1 recordings (formats, not contents)."""
    s = tmp_path / "sessions" / "20990101T000000Z"
    (s / "bag").mkdir(parents=True)
    (s / "bag" / "metadata.yaml").write_text("rosbag2_bagfile_information: {}\n")
    (s / "manifest.json").write_text('{"session_id": "20990101T000000Z"}\n')
    (s / "mcp_calls_executor.jsonl").write_text(
        '{"wall_time_iso": "2099-01-01T00:00:01.000000+00:00", "server": "scene", "tool": "begin_step", '
        '"arguments": {"step_id": "pick_u", "object_ids": ["u"]}, "pid": 1, "elapsed_sec": 0.1, "ok": true}\n'
        '{"wall_time_iso": "2099-01-01T00:00:02.000000+00:00", "server": "gripper", "tool": "grasp", '
        '"arguments": {"object_id": "u"}, "pid": 2, "elapsed_sec": 1.0, "ok": true}\n'
    )
    (s / "events_gripper.jsonl").write_text(
        '{"event_id":"e1","event_type":"skill_start","timestamp_ns":5,"wall_time_iso":"2099-01-01T00:00:02.000100+00:00",'
        '"payload":{"skill_name":"grasp_skill"},"subscriber_count":1,"seq":1}\n'
    )
    (s / "events_motion.jsonl").write_bytes(b"")  # empty logs exist in the real data
    out = tmp_path / "out"
    index = commit_session(s, out, ByWindowSegmenter(5))

    assert set(index["roles"]) == {"executor", "backend"}
    assert index["roles"]["executor"][0]["n_chunks"] == 2
    assert index["roles"]["backend"][0]["n_chunks"] == 1
    backend = StepManifest.read(out / "manifests" / "backend" / "w000000.json")
    assert {src.file for src in backend.chunk_sources} == {"events_gripper.jsonl"}
    assert {f["file"]: f["role"] for f in index["source_files"]}["events_motion.jsonl"] == "backend"
    assert [f["file"] for f in index["other_files"]] == ["manifest.json"]
    assert index["not_committed"] == ["bag/"]

    # by_field on the real step marker: only begin/end_step calls carry arguments.step_id
    with pytest.raises(ChunkingError):
        commit_session(s, tmp_path / "out2", ByFieldSegmenter("arguments.step_id"))
    idx = commit_session(s, tmp_path / "out3", ByFieldSegmenter("arguments.step_id", missing="unassigned"))
    assert {e["step_id"] for e in idx["roles"]["executor"]} == {"pick_u", "_unassigned"}

    # keeping a skill server as its own role is one alias away
    idx = commit_session(s, tmp_path / "out4", ByWindowSegmenter(5),
                         SessionLayout(role_aliases={"motion": "backend"}))
    assert set(idx["roles"]) == {"executor", "gripper", "backend"}


def test_commit_cli(make_session, tmp_path, capsys):
    s = make_session(with_frames=True)
    out = tmp_path / "out"
    rc = commit_cli.main(["--session-dir", str(s), "--out", str(out),
                          "--segment", "by_window", "--window-s", "5", "--frames-role", "watchdog"])
    assert rc == 0
    index = json.loads((out / "session_index.json").read_text())
    assert index["segmentation"]["strategy"] == "by_window"
    assert index["frames"] == {"dir": "frames", "role": "watchdog", "count": 3}
    assert "[executor]" in capsys.readouterr().out
