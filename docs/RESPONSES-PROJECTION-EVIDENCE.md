# Projection validation evidence — 2026-10-23

Baseline: merged main `0d456493eebcded61e91e768804e122511185f28`, whose
tree is identical to the published PR #25 source already in the workspace.
Only the projection compatibility changes, tests and documentation are published;
local snapshot commits, private files and previous patch history are excluded.

| Offline command | Result |
| --- | --- |
| `python3 -m unittest discover -s tests -p 'test_api*.py' -q` | 80 tests, 4.426 s, passed |
| `python3 -O -m unittest discover -s tests -p 'test_api*.py' -q` | 80 tests, 5.626 s, passed |
| `make lint` | Passed infrastructure policy and compilation |
| `git diff --check` | Passed |
| `python3 -m unittest discover -s tests -q` | 578 tests, 138.652 s, passed, 2 skips |

The full optimized suite also runs. Its final timing and the six PR-triggered
GitHub Actions outcomes are recorded in the draft PR validation section. Local
test results are distinct from CI results. The local skips are the pinned Codex
binary probe (binary not configured) and encrypted restore (`age` unavailable).
Local Unix socket permission is used for offline peer-transport regression tests.

PR #25's evidence-derived incomplete fixture is reused. Synthetic metadata
includes nulls, numbers, strings, nested objects, arrays, instructions, dummy
credentials and tool-like objects. Exact receipts match with/without metadata
for zero and nonzero usage. Tests check request/model/guard preservation, no
tool execution, no logs, no receipt/audit/database leakage, failure diagnostics
without unknown labels, and retained holds for malformed authoritative fields.

The former tests that expected rejection merely for unfamiliar top-level fields
were updated to the projection contract. Regressions continue rejecting known
security violations and unknown nested usage/output dimensions. Global size,
duplicate-key and nonfinite JSON restrictions remain tested.

All tests use mocked API transports, synthetic input, dummy credential files
and disposable ledgers. No live inference, operator key, private ledger, raw
response or existing reservation is accessed. The dispatch-only daily planner
is not triggered. Passing these tests is not live connectivity validation or
provider billing evidence. See [the runbook](RESPONSES-PROJECTION.md) for the
security boundary and remaining assumptions.
