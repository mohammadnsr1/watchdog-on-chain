# CLAUDE.md — standing instructions for watchdog-on-chain

## Project

WatchDog on Chain extends WatchDog (an independent LLM supervisory monitor for agentic robotic
assembly) onto a blockchain, for tamper-evident, attributable, disputable inspection in agentic
manufacturing. The thesis carries over: an executor agent cannot reliably verify itself, because
actor and verifier share a root of trust; an independent WatchDog with its own observation channel
can. The blockchain makes WatchDog's testimony permanent and attributable. The judge, random human
audits and reputation keep that testimony honest. WatchDog acts as an independent oracle for
physical truth. Full design: `docs/DESIGN.md`. Milestones: `docs/MILESTONES.md`.

## Work cell crew (core concept)

Per job, an executor, a WatchDog and a judge are bound as one unit by an on-chain job contract.
It records the assigned agents and the spec/contract version and is signed by the customer and
the operator. They cooperate, but no party controls another.

| Party | Agent / role |
|---|---|
| Cell operator | runs the robot cell; its agent is the **Executor** |
| Customer | owns the spec and chooses the WatchDog; signs the job contract |
| Inspection provider | offers **WatchDogs** (different models, specialties, reputations) |
| Neutral arbiter | appointed by the consortium; its agent is the **Judge** |
| Auditor | humans who randomly check the judge's rulings |

## Non-negotiable rules

1. Executors never choose their inspector; customers/operators do. The crew never chooses its judge.
2. Executor and WatchDog evidence is committed and signed **separately**: two independent
   witnesses, never merged into one manifest or root.
3. Raw data never goes on-chain. Tier 0 = raw streams (off-chain content-addressed store).
   Tier 1 = monitor events (off-chain). Tier 2 = per-step claim/verdict + contract version + one
   Merkle root (on-chain).
4. Disputed chunks are revealed only on challenge, with Merkle proofs.
5. The judge acts only when a claim is challenged. It may pull its own evidence from the
   physical-event history and the raw streams. It is told its rulings are randomly audited by humans.
6. Real-time consultation and risk warnings between WatchDog and executor happen off-chain; their
   hashes are committed with the step evidence.
7. Raw data must stay available at least until the challenge window closes.
8. Hash scheme: keccak256 with OpenZeppelin-compatible sorted-pair Merkle trees
   (id `keccak256-oz-sorted-v1`); leaf = keccak256(keccak256(chunk)). Never change it silently;
   any new scheme gets a new id.
9. Cross-process ordering uses `wall_time_iso` only, never `timestamp_ns`.
10. WatchDog_V1 (`/home/mohammadnsr1/watchdog/WatchDog_V1`) and the imported sessions
    (`data/transcripts/sessions/`; the whole `data/` tree) are read-only inputs. Never modify
    imported data. `data/` is git-ignored except `data/IMPORT_INVENTORY.md`.
11. Never touch any repository other than this one.
12. Private keys are never hard-coded or committed. They come from environment variables or a
    git-ignored `.env`; only anvil's publicly known test keys may appear, and only in
    `.env.example` with a clear "local test only" warning.

## Working rules for Claude Code

- Never run commands, scripts, tests, installs, chains (anvil/Besu), ROS or Isaac Sim. Only
  create and edit files, then tell Mohammad exactly what to run, in order.
- Mohammad is new to blockchain programming. In Solidity and web3 code, add short comments
  explaining blockchain concepts where they first appear (gas, events, revert, `msg.sender`,
  ABI, view functions, nonces, receipts, etc.).
- Prefer small incremental changes with clear file and placement notes over rewrites.
- Contracts: Solidity `^0.8.20`, OpenZeppelin for `MerkleProof`, EVM-portable (anvil now,
  Hyperledger Besu QBFT later). No chain-specific precompiles.
- Python: keep `wdchain` importable without a chain. Anything that needs a live chain is
  behind `@pytest.mark.chain` (skipped by default).
- After each milestone, update `docs/MILESTONES.md` status and "Build plan and status" below.
- When the code and this file disagree, say so and fix the one that is wrong; do not paper over it.

## Stack

Python package `wdchain` (`eth-hash`, `eth-account`, `web3`); Solidity contracts in `contracts/`,
compiled and tested with Foundry (`forge`); local chain `anvil`; later a Besu QBFT network with
one node per organization (4 validators tolerate 1 dishonest party); the auditor runs a
non-validating full node.

Repo map: `wdchain/evidence/` (canonical JSON, chunker, merkle, store, manifest, commit),
`wdchain/chain/` (config, registry client), `wdchain/cli/` (commit_session, prove, verify,
anchor_session, verify_onchain), `contracts/` (`EvidenceRegistry.sol`, `test/`, `script/`),
`scripts/` (fixture generator, import checker), `fixtures/`, `deployments/`, `docs/`, `tests/`.

## Build plan and status

- **Phase 1, evidence anchoring.** Part A **DONE** (data import; chunking, Merkle roots, proofs,
  CLIs). Part B **IN PROGRESS**: `EvidenceRegistry.sol`, Foundry tests with a Python-generated
  fixture, deploy script, `wdchain.chain`, `anchor_session`, `verify_onchain` are written and
  not yet run (see `docs/MILESTONES.md`, M1-B acceptance checks).
- **Phase 2:** job contract, claims and challenges contract, judge agent.
- **Phase 3:** reputation; WatchDog variants (honest, lazy, strict, colluding); selection by
  customer/operator; reputation also for other machine-controlling agents.
- **Phase 4:** agent-certified part passport; fault-injection experiments in Isaac Sim; paper results.
- **Deferred:** formal math (scoring rules, cost/risk formulation, reputation dynamics, audit
  weighting) until the system works. Use only simple placeholders unless asked.

## Open decisions (flag these; never decide silently)

- Step granularity for evidence commits (per primitive, subtask or task); both segmenters
  (`by_field`, `by_window`) stay configurable. The real logs have no per-record step field;
  a begin/end-marker segmenter is a candidate.
- Challenge window length and raw-data retention period.
- Models backing the WatchDog variants and the judge.
- How STL (signal temporal logic) specs enter the system.
- On-chain role set: the registry's `Role` enum has only `Executor` and `WatchDog`; wdchain also
  produces `backend` and `executor_monitor` roles, which are not anchored yet.

## Facts about the data (do not rediscover)

- 117 sessions in `data/transcripts/sessions/` (88 guarded S1–S3, 29 unguarded S4), no rosbags.
- Every `events_*.jsonl` / `mcp_calls_*.jsonl` record has `wall_time_iso`; no CRLF, no partial lines.
- Step markers: executor `scene.begin_step` / `scene.end_step` with `arguments.step_id`;
  WatchDog events carry `payload.step_id` (often `null`).
- Role mapping: `mcp_calls_executor` → executor; `events_watchdog`, `mcp_calls_watchdog` →
  watchdog; `events_executor_monitor` → executor_monitor; `events_{gripper,motion,scene}` → backend.
