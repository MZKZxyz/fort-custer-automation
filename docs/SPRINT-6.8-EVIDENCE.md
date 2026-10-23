# Sprint 6.8 — offline evidence and remaining blockers

Review date: 2026-10-22 (America/Los_Angeles).
Base: latest main `06db90683386be286de2536a28dbea81999cd990`,
including merged Sprint 6.7 PR #16.

Shell Git could not connect to the configured proxy. Connected GitHub reads
provided changes #14–16; every retrieved file was checked against its Git blob
SHA. The reconstructed baseline exactly matches upstream tree
`63c855e7b018efec8f75d7e31c55307ba6656d86`. The signed base commit was
reconstructed from GitHub's verification payload/signature, reproducing the exact
base SHA. The delivery is based on that real commit, not on a synthetic history.
No proxy bypass or alternative credential discovery was used.

## Validation

- Initial full suite: 434 tests in 138.462 s, OK, one existing `age` skip.
- New targeted suite: 12 tests in 4.435 s, all passed.
- Final full suite: **435 tests in 149.283 s; 434 passed, one existing skip**
  (`age` unavailable). Run with umask 0022.
- `make lint`: pinned image/live-gate validation and Python compilation passed.
- `python3 examples/supervised_integration.py`: complete promoted-task chain passed.
- `python3 examples/three_worker_coordination.py`: three synthetic workers completed,
  independent QA receipts, 9 input / 3 cached input / 12 output tokens, 384 artifact
  bytes, zero live workers.
- Health CLI missing-evidence check: structured unknown/blocked report, exit 1;
  valid synthetic policy check: one approved task, zero active holds, valid source/
  ledger, but live readiness still false and all isolation prerequisites unverified.
- CLI help and whitespace checks passed.

Execution platform: Linux, Python 3.11+ and installed Node; no macOS executor was
available. No macOS adversarial isolation or platform-specific resource enforcement
is claimed tested. No Docker build or live environment provisioning was performed.

## Continuous synthetic demonstration

The single rehearsal uses one proposal, promoted catalog entry `new-task`,
execution and publication throughout. Fake read-only issue discovery supplies a
proposal; real promotion prepare/review/export/import code installs that exact
reviewed entry into a temporary policy. A separate controller approval precedes
synthetic coding. Wire artifact ingestion supplies the candidate; the real
controller independently reconstructs and runs pinned Node QA. Publication then
requires its own prepare/preflight/terminal approval and independently reconstructs
again. A mock GitHub stores a draft result, and the real read-only orchestration
reconciler saves a final `awaiting-human-merge` observation.

Recorded receipt from `examples/supervised_integration.py`:

| Field | Value |
| --- | --- |
| Proposal | `afe0553d0f0d0910d1dd361ae2177712adead7ece079d16824be6f0f94ec8217` |
| Promotion | `637b789197b741f89ce5910db7702c47` |
| Execution | `6866478b562d41468d3d220cc27c4222` |
| Source | `bf644863e44c736d1bcb44702a02cbde406abbd8` |
| Candidate | `781d034bd4675e9719896d7de46fcd281557116ebb178c04920012c53c736a74` |
| QA digest | `39990849d6fc16a3c747c4d5601e7e43c7ec692d0c49949cb721093381754c0b` |
| Request digest | `e488433434d3bed02059ee3aab0f45a1d3cf6674d11200f238783a16983bf99c` |
| Response digest | `bb56a6b7d74a70b86bd9a3e7e7e4fd2f8741fa0faa30f887ca47f9eb8a230e73` |
| Publication | `2294339fe7464f9e4b8e58024211702ab779ca819e88808a189b32a56a023137` |

The printed application PR URL is a **mock string**, not an actual publication.
Fixture timestamps, IDs, Git commits and digests vary per run. Temporary ledgers
are deleted after the demo; these are historical receipts, not usable grants.
Operational credentials: false. Live workers: 0. Real publication: false.

Terminal responses and the migration gate are mocked only inside temporary
offline fixtures. The generated fake CLI and fixed fixture worker are trusted
test programs. Independent QA actually executes against synthetic source, but
under the controller UID: this verifies reconstruction, not hostile-code isolation.
The production gate has no mock/config/environment override. The fresh-process
regression uses the real gate, not the historical fixture's mock.

## Security regression coverage

| Requirement | Evidence |
| --- | --- |
| Legacy/coordinator double use | New `test_legacy_and_coordinator_cannot_dispatch_same_live_grant`: both production runner entry points reject, coordinator refuses live adapter, approval ledger unchanged |
| Separate controller bypass | New fresh-interpreter subprocess test rejects before claiming, with original approval still approved |
| Missing isolation | Unconditional production migration gate; health never reports live-ready, even with valid policy and a Node binary |
| Immutable narrow request | New bytes/request test checks omission of controller paths and exact response transfer |
| Fencing, forged output, source/policy change | New token/generation/request/schema/digest/deadline mutation tests; prior coordinator validates current source/policy/history at claim/start/completion |
| Missing/modified artifacts, interrupted transfer | New malformed/truncated/changed wire tests, protected/extra path tests, size ceiling; prior candidate reconstruction/missing-file regression |
| Protected path access | Wire path rejection only; no real OS isolation established or claimed |
| Replay/conflicts/restart | Existing coordinator thread/process races, unique task/execution, repository collision, persistent held claim and terminal recovery tests |
| STOP startup/execution/QA | Existing coordinator broken-symlink, worker/QA cancellation and termination uncertainty tests; live startup blocked entirely |
| Incomplete QA/failed persistence | Existing coordinator and publisher incomplete-QA, artifact corruption, termination and disk failure tests |
| Interrupted publication | Existing catalog publication uncertainty and orchestration ambiguous-publication tests; no automatic retry introduced |
| Full integration | New `test_continuous_promoted_task`; publication shortcut before coding rejected |
| Historical compatibility | Full previous regression retained; fixture gate mock added to preserve protocol tests; original schemas/hashes untouched |
| Read-only health | New byte-preservation, missing/contradictory evidence and never-green tests |

## Preserved evidence

| File | SHA-256 |
| --- | --- |
| `state/automation.db` | `53991a6539c1ada5fbf23c8ff89523c253b801b8e5ca834e003fb88304e62fc6` |
| `docs/SPRINT-5.9.md` | `22fa4544657cfcd6b8353ef84ae0633a72318ed370b9377a599a0cbdf4f9cc6a` |
| `docs/SPRINT-5.9-EVIDENCE.md` | `2c643e8f50c7e5807387cee183f014bd32df98db7af65a12171b55db21c49f1b` |

No operational ledger, application source, account login, production connection,
model subscription or paid API was used. The requested draft implementation PR
to the automation repository is separate from application publication.

## Readiness conclusion

This is the permitted **fail-closed migration outcome**, not completed live
broker/isolation deployment. This version has no independently usable live
legacy or coordinator path. An already running old controller/checkout still
requires administrative revocation; this code cannot fence independent obsolete
credentials. Never use old software to evade the boundary.

Required before a second real canary: shared atomic authority, fresh grants,
supported credential-free model transport, externally verified worker and QA
boundaries, isolated publisher, lifecycle/watchdog and resource verification,
full pinned application QA baseline, current repository/credential review and
separate activation approval. Hard scratch/CPU/memory/network limits and
subscription dollar caps remain unsupported here. $10/day is an operator goal.
See [design/recovery](SPRINT-6.8.md) and [Mac canary preparation](LIVE-CANARY-RUNBOOK.md).
