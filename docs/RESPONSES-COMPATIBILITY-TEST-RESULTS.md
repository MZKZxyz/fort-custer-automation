# Offline validation results — 2026-10-23

Baseline: GitHub main `6725775873a22feb0a93a14f29aad0359d980136`.
The existing local patch was continued, not reimplemented. The operator's exact
zero-valued `tool_usage` object is now in `observed-incomplete.json` and passes
the production validator without content or metadata persistence.

| Command | Result |
| --- | --- |
| `make lint` | Passed: infrastructure policy and compilation |
| `python3 -m unittest discover -s tests -p 'test_api*.py' -q` | 76 tests, 4.656 s, passed |
| `python3 -O -m unittest discover -s tests -p 'test_api*.py' -q` | 76 tests, 6.105 s, passed |
| `python3 -m unittest discover -s tests -q` with local socket permission | 574 tests, 142.785 s, passed, 2 skipped |
| `git diff --check` | Passed |

The full optimized suite is also run; its final result and the GitHub Actions
results for the published commit are recorded in the draft PR validation record.
CI results are distinct from these local results. Six workflows trigger on PRs;
the seventh, daily planner, is dispatch-only and must not be invoked for this task.

The local skips are the real Codex probe (no explicitly configured pinned binary)
and encrypted restore (`age` is not installed). CI provisions these dependencies.
Local Unix socket permission is needed for the offline grant transport tests;
the initial development attempt in a socket-restricting sandbox had nine bind
errors. The full rerun above passes without weakening transport checks.

No model API calls or real model credentials are used. API transport tests mock
HTTPS and use dummy private credential files; accounting tests use new temporary
ledgers. No operator response or deployed ledger was accessed or reconciled.
No inference or credential provisioning was added to CI. Passing synthetic tests
is not provider billing evidence or validation of live API connectivity.

The published tree must contain only the reviewed compatibility code, synthetic
fixture, regression tests and documentation. The local upstream snapshot commit,
credentials, real ciphertext, raw provider IDs, ledgers and other private files
must not be uploaded.
