# Sprint 5.9 validation evidence

- Full offline suite: `python3 -m unittest discover -s tests -q` — 181 tests,
  180 passed, one optional encrypted-restore test skipped (`age` unavailable).
  Recorded run duration: 31.749 seconds.
- `make lint` — pinned image inputs/live gate validation and Python compilation
  passed. No container build or live execution occurred.
- `git diff --check` — passed.
- `python3 src/readiness.py check --mode chatgpt_subscription` and the corresponding
  `--mode api_billing` check both returned nonzero and `ready:false`, as required.
- 22 added offline tests cover terminal and telemetry compatibility, durable
  reconstruction and publication approval, remote identity, lost responses,
  restart recovery, cancellation, credentials/API redaction, object identities,
  new-branch-only writes and exact draft PR verification.

Tests use disposable fake Git repositories, generated fake CLI code, synthetic
QA evidence and mock GitHub services. The fourteen-test evidence in publication
fixtures is explicitly synthetic; it is not a claim that the real candidate was
executed here. The six QA passes and fourteen analyzer passes for the preserved
experiment are operator-supplied facts, not newly generated evidence.

The checkout initially contained Sprint 5.6. The five files from merged PR #7
were recovered through the GitHub connector and their complete Git tree verified
as `52be43af2f3bf6f99be2ae5fc490206173c95902`, matching PR #7's recorded tree.
Remote main was confirmed as `784367b33a0b61a89deceb2e96fd0b46e0c5d513` before
preparing the Sprint 5.9 review branch. The automation PR uses that remote main
commit as its parent; the recovered baseline is not included as a separate change.

No real Codex invocation, server write/PR, credential provisioning, persistent
execution reset, merge, deployment or unattended scheduling occurred. Only the
requested automation review branch and draft PR are published.

The existing run can be reconstructed without another Codex execution if its
original ledger, policy and trusted base Git objects remain intact. They were
not provided in this environment, so real-run verification remains an operator
step. Review [the runbook](SPRINT-5.9.md) for exact commands, narrow permissions,
expiry/ambiguous-response holds and the ordinary-ledger authenticity limitation.
