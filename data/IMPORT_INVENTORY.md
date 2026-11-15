# WatchDog_V1 import inventory

- **Origin:** WatchDog_V1 sessions and paper results, treated as read-only. Nothing in WatchDog_V1
  was modified.
- **How the data arrived:** the repository owner copied it into this repository by hand. The
  final session copy was made on 2026-11-15, without rosbags. It replaced an earlier copy of 54
  September sessions, most of which had no logs.
- **Location:** sessions are at `data/transcripts/sessions/<session_id>/`, with internal
  structure and file names as copied. Paper results are at `data/paper_results/`.
- **Git:** all of `data/` is git-ignored except this file.
- **Inventory taken:** 2026-11-15, from a listing of `data/` plus a scan of the log files.
  SHA-256 values are not recorded here. `session_index.json` records a keccak256 of every
  session file that wdchain reads.

## Summary

| Area | Contents | Size |
|---|---|---|
| `data/transcripts/sessions/` | 117 sessions, 2026-10-07 to 2026-11-03; no rosbags (`bag/`, `.mcap` and `.db3` are all absent) | ~415 MB (345 MB of it is `transcript_*.jsonl.gz`) |
| `data/paper_results/` | README, `.gitignore`, batch `20261005_smoke` (`batch.yaml` with `TBD` values, `CORRECTIONS.md` with an example row only), empty `raw/`, `summary/`, `tables/` | ~8 KB |

### Sessions by scenario

The scenario comes from `agent_config_watchdog.json`. Guarded means WatchDog logs are present.

| Scenario | Sessions | WatchDog logs |
|---|---|---|
| S1 | 25 | yes |
| S2 | 24 | yes |
| S3 | 37 | yes |
| guarded, no `agent_config_watchdog.json` | 2 | yes |
| S4 (`agent_config_executor.json` scenario `s4`) | 29 | no; these have `events_executor_monitor.jsonl` instead |
| **Total** | **117** | 88 guarded / 29 unguarded |

Unguarded (S4) sessions: 20261021T212024Z 20261021T213725Z 20261021T220205Z 20261021T222426Z
20261021T224444Z 20261021T233649Z 20261021T235455Z 20261022T000306Z 20261022T192812Z
20261022T195619Z 20261022T203509Z 20261022T231310Z 20261023T002520Z 20261023T004020Z
20261023T010936Z 20261023T015428Z 20261023T021542Z 20261023T022457Z 20261023T204228Z
20261023T210814Z 20261023T215632Z 20261023T221447Z 20261023T223052Z 20261026T221922Z
20261026T231007Z 20261026T233132Z 20261027T192136Z 20261027T200520Z 20261103T001459Z.
All other sessions are guarded.

Sessions per day: 10-07 8, 10-08 8, 10-09 2, 10-10 6, 10-15 13, 10-16 10, 10-17 1, 10-19 7,
10-20 10, 10-21 12, 10-22 5, 10-23 11, 10-25 6, 10-26 11, 10-27 2, 11-02 4, 11-03 1.

## Session files: what they are and how wdchain uses them

"N" is the number of sessions that contain the file.

| File | N | What it is | wdchain |
|---|---|---|---|
| `mcp_calls_executor.jsonl` | 117 | executor tool-call report | **chunked**, role `executor` |
| `mcp_calls_watchdog.jsonl` | 88 | WatchDog tool-call report | **chunked**, role `watchdog` |
| `events_watchdog.jsonl` | 88 | WatchDog events: `monitor_armed/disarmed/fire`, `verdict`, `run_verdict`, `look`, `observation`, ... | **chunked**, role `watchdog` |
| `events_executor_monitor.jsonl` | 29 | executor-side monitor events (S4) | **chunked**, role `executor_monitor` |
| `events_gripper.jsonl`, `events_motion.jsonl`, `events_scene.jsonl` | 117 each | skill events (`skill_start` / `skill_end`) from the robot-side MCP servers | **chunked**, role `backend` |
| `transcript_executor.jsonl.gz` / `transcript_watchdog.jsonl.gz` | 117 / 86 | agent conversation transcripts | fingerprinted |
| `score.json`, `score_s4.json`, `observation_score.json` | 81, 28, 110 | per-session scorer output (paper results) | fingerprinted |
| `ground_truth_injections.jsonl`, `gt_<...>.yaml` | 103, 109 | ground truth: injected intruders and faults | fingerprinted |
| `intruder_leak_audit.json` | 98 | leak audit read by the observation scorer | fingerprinted |
| `agent_config_executor.json` / `agent_config_watchdog.json` | 117 / 86 | role, scenario, model, effort, CLI version | fingerprinted |
| `executor.settings.json`, `watchdog.settings.json` | 48 each | agent settings | fingerprinted |
| `registry_provenance_executor.json` | 12 | model-registry provenance | fingerprinted |
| `operator_acm_override.jsonl`, `operator_faults.jsonl` | 5, 1 | operator interventions and faults | fingerprinted |
| `reference_watchdog_log.jsonl` | 2 | reference WatchDog log | fingerprinted |
| `claude_cli_version.txt` | 51 | CLI version | fingerprinted |
| `orchestrator/orchestrator_<...>.jsonl` | 117 | orchestrator log (`type`, `wall_ns`) | not committed (sub-directory) |
| `authored_monitors/*.py` | 1282 files | monitor code authored during the run | not committed (sub-directory) |

"Chunked" means every record is a Merkle-committed chunk. "Fingerprinted" means the file's
keccak256 and size are recorded in `session_index.json` under `other_files`.

### Log quality (checked 2026-11-15)

- Every non-blank line of every `events_*.jsonl` and `mcp_calls_*.jsonl` file has `wall_time_iso`.
- No chunked log is empty, has CRLF line endings, or lacks a final newline.

## Paper results

| Destination | Size | Why it is needed |
|---|---|---|
| `data/paper_results/README.md` | 5541 | rules for scorer output (raw/ append-only, corrected/ + CORRECTIONS.md, provenance) |
| `data/paper_results/.gitignore` | 275 | keeps session artifacts out of paper_results |
| `data/paper_results/batches/20261005_smoke/batch.yaml` | 1523 | batch provenance template (smoke batch, values `TBD`) |
| `data/paper_results/batches/20261005_smoke/corrected/CORRECTIONS.md` | 735 | corrections log (example row only) |
| `.gitkeep` files in `raw/`, `summary/`, `tables/` | 0 | empty placeholders |

No scored batch CSVs or tables are present. Per-session scorer output lives in the sessions
(`score.json`, `score_s4.json`, `observation_score.json`).

## Byte-for-byte check against WatchDog_V1

`scripts/import_binaries.py` hashes the source and destination of each row below and prints
MATCH / MISMATCH. Destinations already exist, so it never copies or overwrites anything.

<!-- BEGIN TEXT_COPIES -->
| Source path | Destination path | Size (bytes) | Why it is needed |
|---|---|---|---|
| `/home/mohammadnsr1/watchdog/WatchDog_V1/paper_results/README.md` | `data/paper_results/README.md` | 5541 | paper results rules |
| `/home/mohammadnsr1/watchdog/WatchDog_V1/paper_results/.gitignore` | `data/paper_results/.gitignore` | 275 | paper results rules |
| `/home/mohammadnsr1/watchdog/WatchDog_V1/paper_results/batches/20261005_smoke/batch.yaml` | `data/paper_results/batches/20261005_smoke/batch.yaml` | 1523 | batch provenance |
| `/home/mohammadnsr1/watchdog/WatchDog_V1/paper_results/batches/20261005_smoke/corrected/CORRECTIONS.md` | `data/paper_results/batches/20261005_smoke/corrected/CORRECTIONS.md` | 735 | corrections log |
<!-- END TEXT_COPIES -->

<!-- BEGIN BINARY_IMPORTS -->
| Source path | Destination path | Size (bytes) | Why it is needed |
|---|---|---|---|
<!-- END BINARY_IMPORTS -->

## Not imported

Rosbags (not needed), code, virtualenvs, caches, build artifacts, and ROS/Isaac install files.
No contracts, requirements, or scenario configs were provided separately, so
`data/contracts/` and `data/configs/` do not exist. The per-session `gt_*.yaml` files and agent
configs carry the per-run settings.
