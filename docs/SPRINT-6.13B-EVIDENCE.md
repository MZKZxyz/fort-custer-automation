# Sprint 6.13B verification

Base: `12df11d00f43f8852996deaf948455840488409b` (latest main at fetch,
including merged PR #27). No live inference, operational key reads, application
repository changes, merge or deployment occurred. All Responses bytes in tests
are synthetic, and the production transport/helper and sockets are fenced.

## Local results

- `make lint test`: infrastructure lint and compileall passed; 617 tests in
  186.927s, OK (skipped=2).
- Final focused normal suite: 24 tests in 10.470s, OK.
- `python3 -O -m unittest discover -s tests -q`: 617 tests in
  175.584s, OK (skipped=2).
- Final focused optimized suite: 24 tests in 11.081s, OK.
- `git diff --check`: clean.

Full suites run with local Unix-domain sockets permitted. The first sandboxed
attempt could not bind the existing broker fixture sockets and also caught a
malicious-task fixture accidentally preparing an existing task twice. The fixture
now creates a distinct temporary approved task. The corrected normal full suite
passes; no production safety check was relaxed. Local skips are the absent `age`
binary and the opt-in pinned Codex OS probes (`FC_CODEX_PROBE_BINARY`); the existing
hosted workflows separately install/exercise these dependencies.

The 24 focused tests cover interactive approval and missing-terminal rejection,
claim/authorization digests, exact task/source/prompt/pricing/cost/principal
bindings, coding-grant denial, default disablement, STOP and revocation before and
after response, expiry before and after response, changed manifests/revisions,
malicious task input and approval/command output, unfamiliar metadata, unexpected
tools, absent visible text, settlement on invalid classification, ambiguous
transport with persistent hold, exhausted budgets, duplicate dispatch, crash
before reservation and restart, old-ledger rejection, production request-profile
bounds, credential isolation, repository byte preservation, publication/execution
denial fences and an end-to-end CLI flow. The 15 existing observation tests retain
all four schema pairs and the complete adversarial classification corpus.

## Hosted CI

The broker workflow now explicitly runs `test_live_observation.py` in normal and
optimized Python on Linux/macOS. Existing full-suite workflows discover these
tests automatically. Exact hosted run URLs and outcomes are recorded in the draft
PR description after push; local results do not imply a hosted workflow passed.
No workflow is dispatched manually and no operational canary is run in CI.

## Remaining limits

See [the Mac runbook](LIVE-OBSERVATION.md) for the concrete one-request procedure.
The existing protected local controller account is the trust boundary. There is
no remote worker or execution service. A committed dispatch intent can consume a
grant before a reservation or network request; there is no retry/replay recovery.
Unknown/invalid provider envelopes retain full holds instead of inventing usage.
Decisions are in memory and cannot be recovered after restart. The 512-token
profile has not been tested against a real task; incomplete/refused/empty or
invalid classifications remain billable when usage is validated. STOP can block
subsequent delivery but cannot cancel a request already sent.

The operator must select an existing independently approved execution from the
Mac's private records; this checkout cannot verify its current availability.
Examples marked as reviews are not operational approvals. No grant or private
file is supplied or synthesized for the canary in this change.
