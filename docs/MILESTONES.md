# Milestones

Status values: **DONE** (built and verified) · **IN PROGRESS** · **NEXT** · **PLANNED**.
Acceptance checks are things Mohammad can run and observe. Updated 2026-11-22.

| ID | Milestone | Status |
|---|---|---|
| M1-A | Evidence commitment | **DONE** |
| M1-B | On-chain anchoring | **IN PROGRESS** |
| M2-A | Job contract | NEXT |
| M2-B | Claims and challenges | PLANNED |
| M2-C | Judge agent | PLANNED |
| M2-D | Consultation logging | PLANNED |
| M3-A | Reputation | PLANNED |
| M3-B | WatchDog variants and selection | PLANNED |
| M4-A | Part passport | PLANNED |
| M4-B | Experiments | PLANNED |
| M4-C | Consortium deployment | PLANNED |

---

## Phase 1 — Evidence anchoring

### M1-A Evidence commitment — DONE

**Goal.** Turn a recorded WatchDog session into per-role, per-step Merkle commitments that a
contract can later verify, with no blockchain dependency.

**Deliverables.** Imported sessions (`data/transcripts/sessions/`, 117 sessions) and the
inventory; `wdchain.evidence` (canonical JSON, chunker with two segmenters, Merkle tree, content
store, manifests, commit); CLIs `wdchain-commit-session`, `wdchain-prove`, `wdchain-verify`;
pytest suite on synthetic data.

**Acceptance checks.**
- `pytest -q` passes (canonical JSON, Merkle 1/2/3/7/8 leaves, tamper, role separation,
  determinism, write-once store, wall-clock ordering).
- Committing a real session twice gives byte-identical manifests and roots.
- Executor and WatchDog chunks never appear in each other's manifests.
- Flipping one byte in a stored chunk makes its proof fail and changes the recomputed root.

---

### M1-B On-chain anchoring — IN PROGRESS

**Goal.** Every committed session leaves a tamper-evident, attributable trace on a local chain,
and a proof generated in Python verifies inside a Solidity contract.

**Deliverables.** `foundry.toml`; `contracts/EvidenceRegistry.sol` (write-once per
`(session, role, step)`, `commit`/`commitBatch`, `verifyChunk`, `computeStepKey`);
`contracts/test/EvidenceRegistry.t.sol`; `contracts/script/DeployEvidenceRegistry.s.sol`;
`wdchain.chain` (config, registry client); CLIs `wdchain-anchor-session`,
`wdchain-verify-onchain`; `scripts/make_merkle_fixture.py`; `tests/test_chain_offline.py`;
`.env.example`.

**Written but not yet run.** Everything above exists in the repo; none of it has been executed.
The acceptance checks below are what turns this to DONE.

**Acceptance checks.**
1. `forge test -vv` passes, including `test_PythonFixtureVerifiesOnChain` (a Python-built tree
   verifying inside the contract) and the tampered-digest / tampered-proof cases.
2. `pytest -q` passes, including the offline chain tests (ABI vector, config errors).
3. One real session anchored on anvil, with executor and WatchDog commits coming from
   **different addresses** (visible in `anchor_log.csv` and in the `Committed` events).
4. `wdchain-verify-onchain` prints VALID for a real chunk, and INVALID after one byte of a
   stored chunk is flipped.
5. `anchor_log.csv` contains gas numbers; `forge test -vv` prints gas for 1/10/100-step batches.

**Known limits carried into M2.** No access control (anyone may commit for any role); only
`Executor` and `WatchDog` have on-chain roles, so wdchain's `backend` and `executor_monitor`
evidence stays off-chain; `contract_version` is `null` in every manifest.

---

## Phase 2 — Job contract, disputes, judge

### M2-A Job contract — NEXT

**Goal.** Bind one executor, one WatchDog and one judge into a crew per job, and close M1-B's
access-control TODO.

**Deliverables.** `contracts/JobContract.sol`: `jobId`, executor/watchdog/judge addresses,
customer and operator signatures, `specVersion`, the registry in use, challenge window and
retention period; `EvidenceRegistry` gains a check that the caller is the assigned agent for
that role; Python helper to create and read jobs.

**Acceptance checks.**
- A job can be created only with both the customer's and the operator's signature.
- A commit from an address that is not the job's assigned agent for that role reverts.
- The assigned executor cannot commit WatchDog evidence, and vice versa.
- An existing M1-B session can be re-anchored under a job without changing its roots.

**Design questions to settle first.** Challenge window length and raw-data retention period
(both are job-contract fields). How the spec/STL version is hashed into `specVersion`. Whether
`backend` and `executor_monitor` evidence gets on-chain roles.

### M2-B Claims and challenges — PLANNED

**Goal.** Per-step claims and verdicts on-chain, with a window in which anyone entitled can
dispute them.

**Deliverables.** `contracts/ClaimRegistry.sol`: executor posts a claim (step outcome +
evidence root), WatchDog posts a verdict; `challenge(stepKey, reason)` within the window;
`Challenged` event; a step becomes final when the window closes unchallenged.

**Acceptance checks.**
- A claim and a verdict for the same step coexist and are separately attributable.
- A challenge inside the window emits `Challenged`; one after it reverts.
- An unchallenged step reads as final after the window.
- Challenging reveals nothing by itself; chunks are revealed with proofs afterwards.

**Design questions to settle first.** Challenge window length. Who may challenge (customer,
operator, WatchDog, any consortium member). Whether a challenge requires a stake or bond.
Step granularity, since it decides what a claim is about.

### M2-C Judge agent — PLANNED

**Goal.** An off-chain agent that settles challenges using evidence it pulls itself.

**Deliverables.** `wdchain/agents/judge.py`: wakes on `Challenged`, requests Merkle-proofed
chunks from both witnesses, may read raw streams and the physical-event history, posts a ruling
with its evidence hash; on-chain random sampling of rulings for human audit.

**Acceptance checks.**
- A seeded dispute produces a ruling that cites specific chunks, each with a verifying proof.
- The judge rules only on challenged steps; it ignores unchallenged ones.
- A sampled ruling appears in the audit queue, and an auditor verdict is recorded on-chain.
- The judge's prompt states that its rulings are randomly audited.

**Design questions to settle first.** Which model backs the judge. Audit sampling rate and who
the auditors are. What evidence the judge may pull beyond the two witnesses' chunks. Ruling
format (binary, graded, or with a confidence).

### M2-D Consultation logging — PLANNED

**Goal.** Record that the WatchDog warned or advised the executor, without putting the exchange
on-chain.

**Deliverables.** A consultation log per step; its hash committed with the step evidence;
scoring that credits useful advice.

**Acceptance checks.**
- A consultation's hash appears in the step's commitment and can be proved later.
- Replaying a run shows advice given before the step that it concerns.
- A step with no consultation is distinguishable from one whose log was lost.

**Design questions to settle first.** Whether consultation is a separate chunk stream or part
of the WatchDog's evidence. How advice quality is scored (deferred formal math). Whether advice
that the executor ignored changes responsibility.

---

## Phase 3 — Reputation and inspector market

### M3-A Reputation — PLANNED

**Goal.** Per-agent on-chain history and a placeholder score.

**Deliverables.** `contracts/Reputation.sol`: history of steps, challenges, rulings and audit
outcomes per agent; simple placeholder score updates from rulings and audits.

**Acceptance checks.**
- A ruling against an agent changes its score; an audit that overturns a ruling changes it back.
- History is append-only and attributable.
- The score function is isolated in one place, so the real scoring rule can replace it later.

**Design questions to settle first.** The scoring rule itself (deferred). How audits are
weighted against rulings. Whether reputation decays. Whether executors and judges share the
WatchDog's scale.

### M3-B WatchDog variants and selection — PLANNED

**Goal.** Show that reputation separates good inspectors from bad ones.

**Deliverables.** Honest, lazy (skips looks), strict (over-fires) and colluding (sides with the
executor) WatchDog variants; selection by the customer/operator on reputation and specialty.

**Acceptance checks.**
- Each variant is reproducible from a config, and its behavior is visible in its event log.
- Over a run of jobs, the honest variant's reputation separates from the other three.
- Selection uses only the customer's/operator's choice; no executor input (rule 1).

**Design questions to settle first.** Which models back which variants. How many jobs are
needed for separation. Whether colluding variants coordinate off-chain in the simulation.

---

## Phase 4 — Passport, experiments, consortium

### M4-A Part passport — PLANNED

**Goal.** A per-part record a downstream customer can verify.

**Deliverables.** Per-part: the crew, the job contract, every step's verdict, disputes and
rulings, and the evidence roots; a verification CLI.

**Acceptance checks.**
- Any step in a part's history can be verified with a proof against an anchored root.
- The passport names the crew and the spec version.
- A part whose evidence is no longer retrievable is reported as unverifiable, not as valid.

**Design questions to settle first.** Retention beyond the challenge window. Part identity
(serial, TF frame name, or job + step). What a passport reveals to a third party.

### M4-B Experiments — PLANNED

**Goal.** The paper's numbers.

**Deliverables.** Fault-injection runs in Isaac Sim (Classes 1–4); metrics: detection,
dispute outcomes, reputation separation, gas and bytes on-chain per step, and data volume
Tier 0 vs Tier 2.

**Acceptance checks.**
- Each class has runs with and without a WatchDog, scored by the existing scorers.
- Gas and bytes per step are measured, not estimated.
- Tier 0 vs Tier 2 volume is reported per session.
- Results land in `data/paper_results/` under the batch rules in its README.

**Design questions to settle first.** Step granularity (it sets the gas-per-step number).
Which sessions are re-run versus re-used from the 117 already recorded. Scored-batch
provenance (`batch.yaml` currently has `TBD` values).

### M4-C Consortium deployment — PLANNED

**Goal.** The same contracts on a realistic consortium network.

**Deliverables.** Besu QBFT network, 4 validator organizations (operator, customer, inspection
provider, arbiter), plus a non-validating full node for the auditor; deployment and genesis config.

**Acceptance checks.**
- The same contracts deploy unchanged from anvil to Besu.
- The network produces blocks with one validator offline (4 validators tolerate 1 fault).
- The auditor's non-validating node serves the full history.
- An anchored session verifies identically on both chains.

**Design questions to settle first.** Whether to anchor the consortium chain's block hashes to
a public chain periodically. Key management per organization. Gas pricing (free gas or metered).
