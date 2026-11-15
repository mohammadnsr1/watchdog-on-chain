# WatchDog_V1 import inventory

- **Origin:** WatchDog_V1 (`/home/mohammadnsr1/watchdog/WatchDog_V1`), treated as read-only.
- **How the data arrived:** the repository owner copied it into this repository by hand on or
  before 2026-11-15. Nothing here was copied by a script, and nothing in WatchDog_V1 was modified.
- **Exact source paths:** for `data/paper_results/` the presumed source is
  `WatchDog_V1/paper_results/`, which exists. For `data/transcripts/sessions/` the source
  path is **not yet recorded** (there is no `WatchDog_V1/transcripts/` directory).
- **Layout difference from the original plan:** sessions live at
  `data/transcripts/sessions/<session_id>/`, not `data/sessions/`. The internal structure and
  file names are exactly as the owner copied them.
- **Inventory taken:** 2026-11-15, from a file listing of `data/` (sizes in bytes). SHA-256
  values are not recorded yet. Run `scripts/import_binaries.py` for the paper_results check below.

## Known gap: sessions without logs

A complete session has the WatchDog event logs (`events_gripper/motion/scene.jsonl`), the
executor tool-call report (`mcp_calls_executor.jsonl`), `manifest.json` and a rosbag (not
needed). Six sessions have their logs. **47 sessions in this copy have only `bag/` and
`manifest.json`, with no JSONL logs** (see the "Committable" column below). Those logs have to
be re-copied from wherever the runs wrote them, if they exist.

## Summary

| Area | Files | Size | Notes |
|---|---|---|---|
| `data/transcripts/sessions/` | 190 files in 54 sessions | ~1.3 GB (almost all `bag/bag_0.mcap`) | 7 sessions have JSONL evidence logs; 47 have only a bag + `manifest.json` |
| `data/paper_results/` | 7 files (3 are empty `.gitkeep`) | ~8 KB | README, scaffolding for batch `20261005_smoke`; **no scored results yet** (`raw/`, `summary/`, `tables/` are empty) |

## What each session file is and why it is kept

| File | Why it is needed |
|---|---|
| `mcp_calls_executor.jsonl` | Executor witness: every MCP tool call (`wall_time_iso`, `server`, `tool`, `arguments`, `ok`, `error`). Contains the task-step markers `scene.begin_step` / `scene.end_step` (`arguments.step_id`, `claimed_outcome`). Committed as role `executor`. |
| `mcp_calls_watchdog.jsonl` | WatchDog witness: the WatchDog agent's tool calls. Committed as role `watchdog`. |
| `events_watchdog.jsonl` | WatchDog verdicts and monitor events. Committed as role `watchdog`. |
| `events_gripper.jsonl`, `events_motion.jsonl`, `events_scene.jsonl` | WatchDog event logs (`skill_start` / `skill_end`, `event_id`, `seq`, `wall_time_iso`), published on `/watchdog/events`. Committed as role `watchdog`. |
| `manifest.json` | The recorder's session manifest: model registry, `registry_sha256`, clock notes, recorded topics, `git_commit`, mesh provenance. Fingerprinted in the session index, not chunked. |
| `agent_config_watchdog.json` | WatchDog agent configuration (scenario, model, effort). Fingerprinted, not chunked. |
| `orchestrator/*.jsonl` | Orchestrator log (`wall_ns`, no `wall_time_iso`). Sub-directory, so not committed yet. |
| `bag/bag_0.mcap`, `bag/metadata.yaml` | rosbag2 recording (`/joint_states`, `/tf`, `/tf_static`, `/watchdog/events`). Not committed by wdchain yet. `.mcap` is git-ignored. |

## Sessions

JSONL sizes in bytes. "—" means the file is absent.

| Session | executor calls | watchdog calls / events | gripper / motion / scene events | other | `manifest.json` | `bag_0.mcap` / `metadata.yaml` | Committable |
|---|---|---|---|---|---|---|---|
| 20260901T204152Z | 22668 | — | 3871 / 17062 / 16852 | | 15078 | 26421717 / 4921 | yes: executor + watchdog |
| 20260901T205317Z | 37965 | — | 7157 / 28730 / 24957 | | 15432 | 40656283 / 4921 | yes: executor + watchdog |
| 20260901T213347Z | — | — | — | | 15432 | 36725423 / 3712 | no JSONL |
| 20260901T214142Z | — | — | — | | 15432 | 11025044 / 3238 | no JSONL |
| 20260901T214542Z | — | — | — | | 15432 | 30030186 / 4177 | no JSONL |
| 20260901T215344Z | — | — | — | | 15432 | 648102 / 3693 | no JSONL |
| 20260901T215704Z | — | — | — | | 15432 | 20048116 / 3232 | no JSONL |
| 20260901T220953Z | — | — | — | | 15432 | 8760521 / 3701 | no JSONL |
| 20260901T221221Z | — | — | — | | 15432 | 2901210 / 2762 | no JSONL |
| 20260901T221342Z | — | — | — | | 15432 | 1938668 / 3698 | no JSONL |
| 20260901T221453Z | — | — | — | | 15432 | 18104467 / 4175 | no JSONL |
| 20260901T221929Z | — | — | — | | 15432 | 2925753 / 2762 | no JSONL |
| 20260901T222048Z | — | — | — | | 15432 | 26674592 / 3712 | no JSONL |
| 20260901T222725Z | — | — | — | | 15432 | 12845853 / 3710 | no JSONL |
| 20260901T223157Z | — | — | — | | 15432 | 14077938 / 3231 | no JSONL |
| 20260901T223629Z | — | — | — | | 15432 | 13622207 / 2766 | no JSONL |
| 20260901T223939Z | — | — | — | | 15432 | 6290331 / 3699 | no JSONL |
| 20260901T224239Z | — | — | — | | 15432 | 5034091 / 4173 | no JSONL |
| 20260901T224440Z | — | — | — | | 15432 | 5019641 / 4173 | no JSONL |
| 20260901T224703Z | — | — | — | | 15432 | 9863129 / 2764 | no JSONL |
| 20260901T224932Z | — | — | — | | 15432 | 6681058 / 4173 | no JSONL |
| 20260901T225128Z | — | — | — | | 15432 | 4634023 / 3234 | no JSONL |
| 20260901T225253Z | — | — | — | | 15432 | 16712206 / 2766 | no JSONL |
| 20260901T225916Z | — | — | — | | 15432 | 14302094 / 4175 | no JSONL |
| 20260901T230219Z | — | — | — | | 15432 | 11416047 / 3231 | no JSONL |
| 20260901T230536Z | 57254 | — | 9415 / 37631 / 43030 | | 15432 | 65520161 / 3512 | yes: executor + watchdog |
| 20260901T232109Z | 29344 | — | 5499 / 20885 / 21479 | | 15432 | 44056493 / 4921 | yes: executor + watchdog |
| 20260901T233248Z | 45217 | — | 7207 / 29612 / 35697 | | 15432 | 42220446 / 3512 | yes: executor + watchdog |
| 20260915T013946Z | — | — | — | | 27076 | 21204131 / 3703 | no JSONL |
| 20260915T022034Z | — | — | — | | 27076 | 20716023 / 3710 | no JSONL |
| 20260915T024748Z | — | — | — | | 27076 | 34453188 / 3712 | no JSONL |
| 20260915T025852Z | — | — | — | | 27076 | 87426777 / 3240 | no JSONL |
| 20260915T032008Z | — | — | — | | 27076 | 111272638 / 3705 | no JSONL |
| 20260916T012841Z | — | — | — | | 27076 | 41234403 / 3240 | no JSONL |
| 20260916T013515Z | — | — | — | | 27076 | 25708571 / 3704 | no JSONL |
| 20260916T014001Z | — | — | — | | 27076 | 36280722 / 3705 | no JSONL |
| 20260916T014713Z | — | — | — | | 27076 | 12631 / 2940 | no JSONL |
| 20260916T014734Z | — | — | — | | 27076 | 19855056 / 3703 | no JSONL |
| 20260916T015326Z | — | — | — | | 27076 | 36555576 / 2768 | no JSONL |
| 20260916T020310Z | — | — | — | | 27076 | 43571105 / 3712 | no JSONL |
| 20260916T021137Z | — | — | — | | 27076 | 19488743 / 3703 | no JSONL |
| 20260916T021954Z | 304 | — | 0 / 0 / 0 | | 27076 | 13914997 / 4441 | yes, but 1 record (a failed `get_rendered_task`) |
| 20260916T022921Z | — | — | — | | 27076 | 20110383 / 3710 | no JSONL |
| 20260916T023635Z | — | — | — | | 27076 | 11951603 / 2762 | no JSONL |
| 20260916T023857Z | — | — | — | | 27076 | 48669894 / 3712 | no JSONL |
| 20260916T025435Z | — | — | — | | 27076 | 104880842 / 2768 | no JSONL |
| 20260916T030958Z | — | — | — | | 27076 | 10592899 / 2762 | no JSONL |
| 20260916T031850Z | — | — | — | | 27076 | 58978374 / 3712 | no JSONL |
| 20260916T032659Z | — | — | — | | 27076 | 30419341 / 2767 | no JSONL |
| 20260916T033056Z | — | — | — | | 27076 | 15251491 / 3710 | no JSONL |
| 20260916T033308Z | — | — | — | | 27076 | 260326 / 3691 | no JSONL |
| 20260916T033331Z | — | — | — | | 27076 | 5053105 / 3706 | no JSONL |
| 20260930T205546Z | — | — | — | | 28196 | 4545566 / 3234 | no JSONL |
| 20261006T000526Z | — | 1026 / 0 | — | `agent_config_watchdog.json` 223, `orchestrator/orchestrator_20261006T000527Z_36ed334c.jsonl` 115 | 28196 | 7798856 / 3976 | yes: watchdog, 2 records (both failed `get_rendered_task`) |

`20261006T000526Z` uses a newer layout: `mcp_calls_watchdog.jsonl`, `events_watchdog.jsonl`,
`agent_config_watchdog.json` and `orchestrator/`, with no executor log.

## Paper results

| Destination | Size | Why it is needed |
|---|---|---|
| `data/paper_results/README.md` | 5541 | Rules for scorer output (raw/ append-only, corrected/ + CORRECTIONS.md, provenance via `registry_sha256`) |
| `data/paper_results/.gitignore` | 275 | Keeps session artifacts out of paper_results |
| `data/paper_results/batches/20261005_smoke/batch.yaml` | 1523 | Batch provenance template (smoke batch, values still `TBD`) |
| `data/paper_results/batches/20261005_smoke/corrected/CORRECTIONS.md` | 735 | Corrections log (example row only) |
| `data/paper_results/batches/20261005_smoke/{raw,summary}/.gitkeep`, `data/paper_results/tables/.gitkeep` | 0 | Empty placeholders |

## Byte-for-byte check against WatchDog_V1

`scripts/import_binaries.py` hashes the source and destination of each row below and prints
MATCH / MISMATCH. Destinations already exist, so it never copies or overwrites anything.
Session rows can be added once their source path in WatchDog_V1 is known.

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

Code, virtualenvs, caches, build artifacts, and ROS/Isaac install files. No contracts,
requirements, or scenario configs (S1–S4) were provided, so `data/contracts/` and
`data/configs/` do not exist yet. Each recorder `manifest.json` embeds the model registry
that was used, with its `registry_sha256`.
