# Sprint 6.7 — offline implementation evidence

Base: latest GitHub main `f7f825c226d4021567d7284ce75640dcc34ace6f`,
including merged Sprint 6.6 PR #15. Shell Git could not connect to its configured
proxy. Connected GitHub tools supplied merged changes #14 and #15; applying them
to the supplied checkout produced the exact main tree
`4a6d643e723c945139cf8e3743b7919e4e63799a`. A local synthetic base commit preserves
that verified tree; the delivery commit is parented to the real GitHub main SHA.
Historical evidence, source ledgers and approval protocols are unchanged.

## New coverage

`tests/test_concurrency_coordinator.py`: 31 offline tests, with private temporary
ledgers, synthetic Git repositories, fake clocks, existing controller
prepare/approve fixtures, real independent Node QA, threads and independent
coordinator processes. No live model invocation or operational approval occurs.

| Boundary | Verified behavior |
| --- | --- |
| Three workers | Barrier proves simultaneous independent checkouts, distinct slots/tokens/generations, no shared writable Git worktree, three independent QA receipts |
| Claim races | Thread and process races for one task; competing processes for one slot; exactly one successful owner |
| Repository collisions | Two distinct approved tasks for one identity remain queued until the first completes |
| Authority | Missing/pending/expired grants, advisory identity, forged approval binding, changed task/policy, stale source HEAD rejected |
| Startup | Controller state and authorization rechecked before synthetic startup; exact adapter type rejects live/fake/subclass workers |
| Restart/fencing | Claims persist across coordinator reconstruction; expired claims held; no reassignment; altered generation/token rejected; recovered identity permanently consumed |
| STOP/cancel | Broken symlink STOP, initial STOP, STOP during worker and QA; queued cancellation; active cancellation retains unconfirmed termination hold |
| Failure | Worker crash/partial write, outside allowlist, deadline, invalid candidate despite worker passed report, incomplete QA, termination exception, failed final SQLite write |
| Evidence | Append-only triggers; controller source/delta reconstruction; overwritten artifact rejected even with SQLite structural integrity; exact candidate/QA binding |
| Resource | Token aggregation; candidate size rejection; available failure metrics; CPU/peak memory explicitly unavailable; unsafe capacity/mode/config changes rejected |
| Compatibility | Original controller ledgers/policies byte-identical after completed synthetic execution; existing catalog/runner/publication protocols and Issue #3 evidence unchanged |
| Operator view | Read-only slots/active/queue/completed/failed/resources CLI; versioned optional orchestration adapter; terminal-only reconciliation |

Existing security/regression suites additionally exercise worker minimal environments,
fixed QA command grammar, prohibited paths/symlinks, process-group deadline and
cancellation, controller-death guardian, independent publication reconstruction,
original one-worker running holds, and separate approval/publication boundaries.

## Recorded three-worker demo

Command: `python3 examples/three_worker_coordination.py`.
All temporary approvals were created through the existing controller implementation
in test fixtures. Three fake identities exist only inside the test process; the
production two-repository allowlist is unchanged. The original LocalCLI adapter is
patched to raise if called. This is a synthetic concurrency demonstration, not live
security isolation or authorization to activate concurrency.

| Task | Slot | Fencing token | State |
| --- | --- | --- | --- |
| task-0 | slot-1 | `3206d4d169ac4fefb9bf14b4fc40a97d` | completed |
| task-1 | slot-2 | `303c7ab291f940188d3c54d1e5d02af2` | completed |
| task-2 | slot-3 | `abfaa5138f344ef9badaf4a9ccd8e01e` | completed |

Each worker had its own token-prefixed directory under the demonstration's private
temporary scratch parent. No checkout contained `.git`. All three candidate
manifests were independently captured; identical fixture edits correctly have the
same candidate hash (`58d2eba6672f8a28a9469d933543d1317e9bbd0bdbf5becbcf6df136270258c8`). Each QA receipt
has a distinct digest because it binds the independent task, execution and token.

Aggregate observed usage: **9 input tokens, 3 cached input tokens, 12 output
tokens, 384 candidate bytes**. Execution duration sum: **0.3532040869999946 s**;
QA duration sum: **2.2092822380000143 s**. These are sums across
parallel tasks, not elapsed wall time. Synthetic exit statuses: all 0. Peak memory
and CPU seconds: null/unavailable. **Real Codex workers launched: 0.**
Temporary fixture directories are removed at the end; printed identities above
are a historical demonstration receipt, not reusable grants or recovery handles.
The separate same-repository test demonstrates queueing and subsequent admission.

## Security and operational limitations

- The new module has no live dispatch method or CLI. The exact fixed synthetic
  class is trusted in-process code; it has no separate OS identity/environment.
  Directory separation and Python type checks are not a hostile-worker sandbox.
- Future live integration must atomically consume original controller approval,
  coordinate every legacy runner path, and provision an independently reviewed
  external worker/QA sandbox. This separate readiness ledger alone cannot exclude
  a legacy runner started against an operational controller ledger.
- One macOS UID cannot isolate credentials, policy, approvals or mutable state.
  Sandbox mounts/identity, restricted environment/argv, network denial, process-tree
  termination, output ingestion and hard resource quotas remain external work.
- Controller store is trusted, private local SQLite. Append-only triggers and
  receipts reject ordinary overwrites/inconsistency; they are not signatures or
  protection against a privileged attacker rewriting every ledger artifact.
- STOP/cancellation polling needs a running controller or explicit `sweep`; this
  module is not a daemon. Process death is never inferred from expiry. Ambiguous
  claims retain repository and slot until a terminal-reviewed operator confirms
  termination and records recovery. No retry, lease theft or side-effect replay.
- Physical SQLite pages and ingestion payloads are bounded. Hard aggregate scratch
  disk, CPU, memory and network quotas are unsupported. CPU/peak memory metrics and
  subscription monetary limits are unavailable; partial usage is labelled.
- Source policy, Git and controller reads are not a cross-store atomic snapshot.
  Current grants are rechecked at enqueue, claim, startup and completion; this is
  sufficient for the trusted synthetic experiment, not an atomic live handoff.
- Existing approval/catalog/publication protocols and historical ledgers remain
  unchanged. No application GitHub write, scheduler activation, real Codex launch,
  merge, deployment or publication was performed. The requested draft implementation
  PR in the automation repository is the sole remote delivery action.

See [operator guide](SPRINT-6.7.md) for the state machine, explicit recovery,
rollback and external activation prerequisites.

## Exact validation results

- `python3 -m unittest discover -s tests -q`: **422 tests in 159.366 s;
  421 passed, one existing skip** (`age not installed; encrypted restore not verified`).
- New targeted suite: **31 tests passed in 31.690 s**.
- `make lint`: passed (pinned image/live-gate checks and Python compilation).
- `python3 examples/three_worker_coordination.py`: passed, three completed workers,
  independent receipts, no live adapter invocation; recorded usage above.
- `python3 -m src.concurrency_coordinator --help`: passed.
- Disabled example configuration validation and fresh-interpreter read-only import
  check (no runner, Codex adapter or publisher imported): passed.
- `git diff --check` and staged whitespace check: passed.

An earlier full regression run also passed: 415 tests in 154.364 s, one existing
skip, before the final seven boundary tests were added. The final 422-test result
includes all 31 new coordinator tests. All test state was temporary; no operational
database was initialized or altered.
