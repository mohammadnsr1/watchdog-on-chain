# watchdog-on-chain

Evidence commitment for WatchDog sessions. This first module (`wdchain`) turns a recorded
session directory into:

- a **content-addressed chunk store** (`store/<keccak256 hex>`, write-once),
- one **manifest per role per step**, holding the chunk digests, their sources, and a Merkle root,
- a **session index** listing every step root per role,
- **Merkle proofs** for individual chunks, plus a verifier.

Phase 1 Part B adds the chain: `contracts/EvidenceRegistry.sol` anchors one Merkle root per
`(session, role, step)`, and a proof generated in Python verifies inside the contract with
OpenZeppelin `MerkleProof.verify`. See "Phase 1 Part B" below.

Executor and WatchDog are **independent witnesses**. Their evidence is committed separately,
with separate manifests and separate roots, signed by different keys, and is never merged.

Design: [`docs/DESIGN.md`](docs/DESIGN.md) · Milestones: [`docs/MILESTONES.md`](docs/MILESTONES.md)
· Standing rules for Claude Code: [`CLAUDE.md`](CLAUDE.md)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

Dependencies: `eth-hash[pycryptodome]`. Dev: `pytest`.

## Hashing scheme: `keccak256-oz-sorted-v1`

| Item | Definition |
|---|---|
| hash | keccak256 (Ethereum Keccak, **not** NIST SHA3-256), via `eth_hash.auto.keccak` |
| chunk bytes | JSONL record → canonical JSON bytes; frame → raw file bytes |
| `chunk_digest` | `keccak256(chunk_bytes)`; also the file name in the store |
| `leaf` | `keccak256(chunk_digest)` (double hash, prevents second-preimage attacks) |
| internal node | `keccak256(min(a,b) ‖ max(a,b))` (sorted pair, commutative, byte-wise comparison) |
| odd node | carried up to the next level unchanged |
| empty step | no root; `EmptyStepError` is raised |
| proof | list of sibling hashes, bottom to top (levels where the node was carried up add nothing) |

The on-chain check later will be:

```solidity
bytes32 leaf = keccak256(abi.encodePacked(chunkDigest)); // chunkDigest: bytes32
require(MerkleProof.verify(proof, root, leaf));
```

The verifier is compatible with OpenZeppelin `MerkleProof`. The tree layout is **not**
OpenZeppelin's JS `StandardMerkleTree`.

### Canonical JSON

Each JSONL line is parsed strictly and re-serialized with sorted keys, compact separators
(`,` `:`), UTF-8 output (no `\uXXXX` escapes), and no whitespace. NaN/Infinity and duplicate
keys are rejected. Key order and whitespace in the original line therefore don't change the
hash. Because canonicalization works on the parsed value, `1.10` and `1.1` hash the same
while `1` and `1.0` do not. The raw log files are also fingerprinted (keccak256 of their
exact bytes) in `session_index.json`.

## Chunking and steps

- Chunk = one non-blank JSONL record (canonicalized) or one frame file (raw bytes).
- Within a step, chunks are sorted by `(wall_time_iso, source path, line number)`.
  `wall_time_iso` is the only cross-process clock. `timestamp_ns` is per-process monotonic and
  is **never** used.
- A role comes from the log file name: `--log-pattern` (default
  `^(?:events|mcp_calls)_(?P<role>.+)\.jsonl$`), mapped through `--role-alias`:

  | File | Role |
  |---|---|
  | `mcp_calls_executor.jsonl` (executor tool-call report) | `executor` |
  | `events_watchdog.jsonl` (verdicts, monitor events), `mcp_calls_watchdog.jsonl` (WatchDog tool calls) | `watchdog` |
  | `events_executor_monitor.jsonl` (S4, unguarded runs) | `executor_monitor` |
  | `events_gripper.jsonl`, `events_motion.jsonl`, `events_scene.jsonl` (skill events from the robot-side MCP servers) | `backend` (default aliases `gripper=backend`, `motion=backend`, `scene=backend`) |

  The skill-server logs also exist in unguarded S4 sessions where no WatchDog ran, so they are
  committed as their own witness rather than as WatchDog evidence. Use `--role-alias` to
  change the mapping, e.g. `gripper=gripper` to commit each server separately.
- Other top-level files (the recorder's `manifest.json`, `agent_config_*.json`) are
  fingerprinted in the index (`other_files`) but not chunked. Sub-directories (`bag/`,
  `orchestrator/`) are listed under `not_committed`.
- Frames (`--frames-dir`, default `frames/`) must be attributed to one role with
  `--frames-role`. The tool refuses to guess. Frame time is taken from the file name via
  `--frame-time-regex` (named group `ts`: ISO-8601 or epoch s/ms/µs/ns, sanity-checked
  to 2000–2100).
- The step boundary is configurable (the granularity isn't fixed yet) through the
  `StepSegmenter` interface:
  - **`by_field`**: group by a step-id field (`--step-field`, dotted paths allowed). Records
    without it cause an error by default; `--missing-step unassigned` puts them into step
    `_unassigned` instead. A frame joins the step whose time span contains it.
  - **`by_window`**: fixed windows of `--window-s` seconds over `wall_time_iso`. The origin
    is the earliest chunk across all roles, so window `w000003` covers the same interval for
    every role. Only the clock is shared; evidence is still committed per role.
- Invariants are enforced at build time: no step mixes roles, no chunk is dropped or
  duplicated, and no step is empty.

### Log field names (found in the imported sessions)

Checked on 2026-11-15 against all 117 sessions in `data/transcripts/sessions/`.

| Log | Fields found |
|---|---|
| `mcp_calls_<role>.jsonl` | `wall_time_iso`, `server`, `tool`, `arguments`, `pid`, `elapsed_sec`, `ok`, `error`, `result` |
| `events_watchdog.jsonl` | `event_id`, `event_type`, `timestamp_ns`, `wall_time_iso`, `payload` (with `step_id`, `phase`, `monitor_id`, ...), `subscriber_count`, `seq`. Event types: `monitor_armed`, `watchdog_ready`, `monitor_disarmed`, `monitor_fire`, `look`, `verdict`, `observation`, `run_verdict`, `frames_captured` |
| `events_executor_monitor.jsonl`, `events_<server>.jsonl` | same envelope as above; server logs carry `skill_start` / `skill_end` |
| `orchestrator/*.jsonl` | `type`, `wall_ns` (no `wall_time_iso`; not committed yet) |

- **Every non-blank line** of every `events_*.jsonl` / `mcp_calls_*.jsonl` file has
  `wall_time_iso` (`+00:00` offset). No file has CRLF line endings or a partial last line.
  `timestamp_ns` is the per-process monotonic clock and is ignored.
- **There is no common per-record step field.** Task steps appear as executor calls
  `scene.begin_step` / `scene.end_step` (`arguments.step_id`, e.g. `pick_u_orange`, with
  `claimed_outcome` on `end_step`). WatchDog events carry `payload.step_id`, which is often
  `null` at run scope. As a result:
  - the default segmentation is **`by_window`** (`--window-s 5`);
  - `by_field` defaults to `--step-field arguments.step_id`, but only the begin/end calls
    carry it, so it needs `--missing-step unassigned`, and everything else lands in `_unassigned`;
  - segmenting by the begin/end markers (every chunk between `begin_step(X)` and `end_step(X)`
    belongs to step X) would match the task structure best. It is not implemented yet.

| Purpose | Default | Flag |
|---|---|---|
| wall-clock time (UTC ISO-8601) | `wall_time_iso` | `--time-field` |
| segmentation | `by_window`, 5 s | `--segment`, `--window-s` |
| step id (`by_field`) | `arguments.step_id` | `--step-field` |
| log files / role | `^(?:events\|mcp_calls)_(?P<role>.+)\.jsonl$` | `--log-pattern` |
| role aliases | `gripper=backend`, `motion=backend`, `scene=backend` | `--role-alias NAME=ROLE` |
| frames directory | `frames` (no session has one; `images_recorded: false`) | `--frames-dir` / `--no-frames` |

## Output layout

```
<out>/
  store/<hexdigest>                     chunk bytes, write-once, read-only (0444)
  manifests/<role>/<step_id>.json       one per role per step
  session_index.json                    all step roots per role, segmentation, source fingerprints
```

Manifest:

```json
{
  "session_id": "...", "role": "executor", "step_id": 3,
  "t_start": "...", "t_end": "...",
  "contract_version": null,
  "hash_scheme": "keccak256-oz-sorted-v1",
  "chunk_digests": ["0x..."],
  "chunk_sources": [{"file": "mcp_calls_executor.jsonl", "line_or_frame": 12}],
  "merkle_root": "0x..."
}
```

`line_or_frame` is the 1-based line number for JSONL records, or the frame path relative to
the frames directory (with `file` = the frames directory). Output is deterministic: committing
the same session with the same flags gives byte-identical manifests and index. Existing
outputs are never overwritten. Committing again with different results fails before anything
new is written.

## CLIs

Each command is installed as a console script and also runs as `python -m wdchain.cli.<name>`.

```bash
# commit (session dir is read-only; --out must be outside it)
S=20261007T205057Z   # a guarded S1 session
wdchain-commit-session --session-dir data/transcripts/sessions/$S --out commitments/$S \
    --segment by_window --window-s 5
wdchain-commit-session --session-dir data/transcripts/sessions/$S --out commitments/${S}_steps \
    --segment by_field --step-field arguments.step_id --missing-step unassigned

# proof for chunk N of one step manifest (printed as JSON)
ls commitments/$S/manifests/*/          # step ids per role (windows with no records have no file)
wdchain-prove --manifest commitments/$S/manifests/watchdog/w000000.json --chunk-index 0 > proof.json

# verify: chunk bytes must hash to --digest, and the proof must lead to --root
wdchain-verify --store commitments/$S/store --digest 0x<chunk_digest> \
    --proof proof.json --root 0x<merkle_root>          # prints VALID / INVALID, exit 0 / 1
```

## Tests

`pytest -q` runs on synthetic sessions only (generated in `tests/conftest.py`). The tests cover
canonical JSON, Merkle trees with 1/2/3/7/8 leaves, tamper detection, role separation,
determinism, write-once storage, wall-clock ordering, and the offline chain layer (step-key ABI
encoding, fixture determinism, configuration errors). Tests that need a live chain are marked
`chain` and skipped by default; run them with `pytest -m chain`.

## Phase 1 Part B — anchoring evidence on a chain

**What it does.** `EvidenceRegistry.sol` stores one `Commit { root, committer, time, hashScheme }`
per step key, where `stepKey = keccak256(abi.encode(sessionId, role, stepId))` and `role` is
`Executor` or `WatchDog`. Because the role is part of the key, the two witnesses can never
overwrite each other. Commits are **write-once**: a second commit to the same key reverts, so an
anchored root cannot be revised. `verifyChunk(stepKey, chunkDigest, proof)` recomputes
`leaf = keccak256(chunkDigest)` and folds the proof, exactly as `wdchain` does off-chain.

Raw data never goes on-chain: one 32-byte root per step and per role, nothing else.

> No access control yet. Any address may commit for any role; `msg.sender` is recorded but not
> restricted. Phase 2's job contract binds the assigned agent per role (see `docs/MILESTONES.md`,
> M2-A).

### Run order

```bash
# 1. Install OpenZeppelin and forge-std into lib/ (lib/ is git-ignored, so --no-git
#    keeps them out of the index; drop it if you prefer submodules).
forge install foundry-rs/forge-std --no-git
forge install OpenZeppelin/openzeppelin-contracts --no-git
forge build

# 2. Python side
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 3. Secrets: copy the example and keep .env out of git (it already is).
cp .env.example .env        # anvil's public test keys — LOCAL TEST ONLY
set -a; source .env; set +a

# 4. Start a local chain in another terminal, and leave it running
anvil

# 5. Deploy; writes deployments/anvil.json for the Python client
forge script contracts/script/DeployEvidenceRegistry.s.sol:DeployEvidenceRegistry \
    --rpc-url "$WDCHAIN_RPC_URL" --private-key "$WDCHAIN_EXECUTOR_KEY" --broadcast

# 6. Generate the Python→Solidity fixture, then run both test suites
python3 scripts/make_merkle_fixture.py
forge test -vv            # -vv prints the gas numbers
pytest -q

# 7. Commit and anchor one real session
S=20261007T205057Z
wdchain-commit-session --session-dir data/transcripts/sessions/$S --out commitments/$S \
    --segment by_window --window-s 5
wdchain-anchor-session --out commitments/$S --batch-size 25 --dry-run   # look first
wdchain-anchor-session --out commitments/$S --batch-size 25
cat commitments/$S/anchor_log.csv        # tx hashes, blocks, gas

# 8. Verify one chunk off-chain and on-chain
wdchain-verify-onchain --manifest commitments/$S/manifests/watchdog/w000000.json \
    --store commitments/$S/store --chunk-index 0        # expect VALID / VALID

# 9. Tamper test: flip one byte of a stored chunk and watch verification fail
D=$(python3 -c "import json,sys; print(json.load(open('commitments/$S/manifests/watchdog/w000000.json'))['chunk_digests'][0][2:])")
chmod u+w commitments/$S/store/$D
printf 'x' | dd of=commitments/$S/store/$D bs=1 seek=5 conv=notrunc 2>/dev/null
wdchain-verify-onchain --manifest commitments/$S/manifests/watchdog/w000000.json \
    --store commitments/$S/store --chunk-index 0        # expect INVALID, exit 1
```

Step 9 edits a file under `commitments/`, which is generated output, never the read-only session
data. Delete that commitment directory and re-run step 7 to get a clean store back.

### Environment variables

| Variable | Meaning |
|---|---|
| `WDCHAIN_RPC_URL` | JSON-RPC endpoint (anvil: `http://127.0.0.1:8545`) |
| `WDCHAIN_EXECUTOR_KEY` | signs executor evidence commits |
| `WDCHAIN_WATCHDOG_KEY` | signs WatchDog evidence commits (a **different** key) |
| `WDCHAIN_REGISTRY_ADDRESS` | optional; overrides `deployments/anvil.json` |
| `WDCHAIN_DEPLOYMENT`, `WDCHAIN_ABI_PATH` | optional path overrides |

`.env` is git-ignored. Only anvil's publicly known test keys belong in `.env.example`.

### On-chain roles

The registry's `Role` enum has `Executor` and `WatchDog` only. `wdchain` also produces `backend`
(skill-server events) and `executor_monitor` (S4) roles; `wdchain-anchor-session` reports those
as off-chain and skips them. Giving them on-chain roles is an open decision in `CLAUDE.md`.

## Data provenance

- Data in `data/` comes from **WatchDog_V1** (`/home/mohammadnsr1/watchdog/WatchDog_V1`),
  treated as **read-only**. Nothing in the source was modified, moved, renamed, or deleted.
- **The whole `data/` folder is git-ignored** (local only). The one exception is
  `data/IMPORT_INVENTORY.md`, which is tracked.
- **Copied on or before 2026-11-15** by the repository owner, by hand:
  - `data/transcripts/sessions/` holds 117 recorded sessions (2026-10-07 to 2026-11-03, ~415 MB)
    without rosbags, which wdchain does not need. (An earlier copy of 54 September sessions,
    most of them missing their logs, was replaced.)
  - `data/paper_results/` holds the paper results scaffolding (batch `20261005_smoke`; no scored
    output yet).
- **Record:** [`data/IMPORT_INVENTORY.md`](data/IMPORT_INVENTORY.md) lists every file with its
  size and why it is needed.
- `scripts/import_binaries.py` checks the paper_results copies byte-for-byte against
  WatchDog_V1 (SHA-256, MATCH/MISMATCH). It never overwrites anything. It can also do future
  imports of large files. The sessions' exact source path in WatchDog_V1 is not recorded yet.
