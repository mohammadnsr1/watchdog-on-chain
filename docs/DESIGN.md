# WatchDog on Chain — design

Status: working design, 2026-11-22. Code state is described in "Known gaps" at the end.

## 1. Problem and thesis

Agentic manufacturing lets an LLM-driven executor plan and run robotic assembly. The executor
also reports whether each step succeeded. That report is worthless as evidence: the actor and
the verifier are the same agent, with the same model, prompt, tools and incentives. A mistaken or
dishonest executor produces a confident, wrong claim and nothing in the loop contradicts it.

WatchDog (V1) answered this with an independent supervisory monitor: a separate LLM agent with
its own observation channel (scene, motion, gripper event streams, camera looks) that arms
monitors from the spec, watches the executor's steps and issues verdicts. Independence of the
observation channel is what makes its verdicts meaningful.

WatchDog on Chain keeps that thesis and adds three properties the single-run system lacks:

| Property | Meaning | Mechanism |
|---|---|---|
| Tamper-evident | nobody can rewrite what was observed after the fact | per-step Merkle roots anchored on a blockchain; raw chunks in a content-addressed store |
| Attributable | every claim and every verdict is bound to a known agent and organization | signed transactions from per-role keys; job contract binds keys to roles |
| Disputable | a claim can be challenged and settled by a party that neither side controls | challenge window, judge agent, random human audit, reputation |

The blockchain makes WatchDog's testimony permanent and attributable. The judge, audits and
reputation keep that testimony honest. WatchDog becomes an independent oracle for physical truth.

## 2. Roles

| Party | Agent / role | Interest | What it signs |
|---|---|---|---|
| Cell operator | **Executor** agent | finish jobs, get paid, keep a good record | step claims, executor evidence roots, job contract |
| Customer | chooses the WatchDog, owns the spec | receive parts that meet the spec | job contract, spec version, challenges |
| Inspection provider | **WatchDog** agents (several models, specialties, reputations) | be selected again; reputation | verdicts, WatchDog evidence roots, advice hashes |
| Neutral arbiter | **Judge** agent | be trusted by the consortium | rulings with evidence hashes |
| Auditor | humans | catch bad rulings | audit results |

Rule: executors never choose their inspector; customers/operators do. The crew never chooses
its judge; the consortium appoints the arbiter.

## 3. Work cell crew and job contract

Per job, one executor, one WatchDog and one judge are bound into a crew by an on-chain
**job contract**:

```
JobContract
  jobId
  executor      (address, operator org)
  watchdog      (address, inspection provider org)
  judge         (address, arbiter org)
  customer      (address)   signs
  operator      (address)   signs
  specVersion   (bytes32)   hash of the assembly spec / contract text
  registry      (address)   EvidenceRegistry used for roots
  challengeWindow, retentionPeriod   (open decisions)
```

The crew cooperates (the WatchDog can warn the executor in real time) but no party controls
another: only the assigned executor key may commit executor roots, only the assigned WatchDog
key may commit WatchDog roots, and only the assigned judge may rule. In Phase 1 the registry
has no access control; the job contract (M2-A) adds it.

## 4. Data tiers

```
Tier 0  raw streams           off-chain, content-addressed store     store/<keccak256(chunk)>
Tier 1  monitor events        off-chain, JSONL per role              events_watchdog.jsonl, ...
Tier 2  per-step commitment   ON-CHAIN                               (claim/verdict, specVersion, root)
```

Raw data never goes on-chain. What goes on-chain per step and per role is one 32-byte Merkle
root plus a few words of metadata. Raw data must stay available (Tier 0 and 1 retained) at
least until the challenge window closes.

### Merkle commitments in one paragraph

Every chunk (one canonical JSONL record, or one raw frame) is hashed:
`digest = keccak256(chunk)`. The leaf is `keccak256(digest)`; the extra hash stops a leaf from
being confused with an internal node. Leaves are paired and hashed upward,
`node = keccak256(min(a,b) ‖ max(a,b))`, an odd node is carried up unchanged, until one root
remains. The root commits to every chunk and their order. To prove that one chunk belongs to a
committed step, one reveals the chunk plus its **proof**: the sibling hash at each level, bottom
to top. Anyone can recompute the path to the root; the contract does exactly that with
OpenZeppelin `MerkleProof.verify`. Nothing else about the step is revealed. Scheme id:
`keccak256-oz-sorted-v1`.

```
                 root
               /      \
            h01        h23'
           /   \      /    \
         L0    L1   h23    L4        <- odd leaf carried up
                   /   \
                 L2    L3
proof(L2) = [L3, L4, h01]
```

## 5. Per-step flow

```
execute step
   |
   v
executor commits   ---- separate ----   WatchDog commits
 root_E (signed E)                       root_W (signed W)
   |                                        |
   +----------------- on-chain -------------+
                       |
             claim (executor) + verdict (WatchDog)
                       |
                challenge window
               /                 \
       no challenge           challenge (customer, operator, WatchDog, ...)
            |                           |
          FINAL                  judge investigates:
                                   pulls Merkle-proofed chunks,
                                   physical-event history, raw streams
                                        |
                                     ruling + evidence hash
                                        |
                                 reputation update
                                        |
                              random human audit of the ruling
```

Properties:

- Executor and WatchDog evidence are two independent witnesses: separate manifests, separate
  roots, separate keys, separate transactions. The same `(session, step)` has two distinct
  on-chain keys because the role is part of the key.
- Disputed chunks are revealed only on challenge, with proofs. Undisputed steps reveal nothing.
- The judge acts only on challenge. It is told that its rulings are randomly audited by humans.

## 6. Consultation and shared responsibility

During a step the WatchDog may consult with the executor: risk warnings ("the clamp effort is
near the limit"), advice ("re-grasp before lifting"). This happens off-chain, in real time. The
exchange is logged, its hash is committed with the step evidence (M2-D), and the WatchDog is
scored on two things: detection (did it catch what went wrong) and the quality of its advice
(did following it help). This gives the WatchDog a stake in the outcome without letting it act.

## 7. Reputation and inspector selection

Each agent (executor, WatchDog, judge) has an on-chain history: steps, challenges, rulings,
audit outcomes. A placeholder score is derived from that history (M3-A); the real scoring rule
is deferred. Customers and operators pick a WatchDog by reputation and specialty (M3-B).
WatchDog variants used in experiments: honest, lazy (skips looks), strict (over-fires),
colluding (sides with the executor). The system should separate them by reputation over time.
Reputation also applies to other machine-controlling agents.

## 8. Part passport

Each physical part gets a record: the crew that built it, the job contract, every step's
verdict, any disputes and rulings, and the evidence roots. The passport is an on-chain
pointer set plus off-chain retrievable evidence; a downstream customer can verify any step of
the part's history with a proof (M4-A).

## 9. Network plan

| Stage | Chain | Purpose |
|---|---|---|
| now | `anvil` (local EVM) | development, Foundry tests, gas numbers |
| next | Hyperledger Besu, QBFT consensus, 4 validator organizations (operator, customer, inspection provider, arbiter); 4 validators tolerate 1 dishonest party | consortium deployment of the same contracts |
| + | non-validating full node for the auditor | independent read access to the full history |
| optional | periodic anchoring of the consortium chain's block hash to a public chain | external timestamping |

Contracts are plain EVM Solidity `^0.8.20` so they run unchanged on both.

## 10. Build plan

See `docs/MILESTONES.md`. Phase 1: evidence anchoring (A done, B in progress). Phase 2: job
contract, claims/challenges, judge agent, consultation logging. Phase 3: reputation, WatchDog
variants and selection. Phase 4: part passport, Isaac Sim experiments, consortium deployment,
paper results.

## 11. Open decisions

- Step granularity for commits: per primitive, per subtask, or per task. The real logs have no
  per-record step id; task steps appear only as `begin_step`/`end_step` markers. Both
  segmenters stay configurable; a marker-based segmenter is a candidate.
- Challenge window length and raw-data retention period.
- Models backing the WatchDog variants and the judge.
- How STL specs enter the system (spec version hash today; STL text later).
- Which roles are anchored on-chain. The registry has `Executor` and `WatchDog`; the
  skill-server event streams (`backend`) and the S4 executor monitor are not anchored.

## 12. Known gaps between this design and the current code

| Design | Code today |
|---|---|
| Job contract binds keys to roles | `EvidenceRegistry` has no access control; anyone can commit for any role (TODO in the contract) |
| Claims and verdicts on-chain | only Merkle roots are anchored; verdicts live in `events_watchdog.jsonl` chunks |
| Challenge window, judge, audits, reputation, passport | not started |
| Consultation hashes | not logged; WatchDog→executor advice is not a separate stream in the data |
| Four witness roles in wdchain | contract enum has two; `anchor_session` skips `backend` and `executor_monitor` |
| Step ids as strings on-chain | wdchain step ids may be ints (`by_field`); they are stringified for the chain key |
| Spec version in the commit | `contract_version` is `null` in every manifest |
| Separate processes and keys per witness | one Python process signs both roles with two keys from env; fine for anvil, not for production |
| Retention guarantees | nothing enforces that `store/` is kept |
