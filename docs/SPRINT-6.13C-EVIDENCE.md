# Sprint 6.13C verification

Base: `1142c37dc14ab38be668d5a6e6d1a30571380875`, merged Sprint 6.13B.
The shell Git proxy was unavailable, so the exact upstream GitHub blobs were
retrieved through the connected GitHub API. The reconstructed base tree is
`b5acddb8fc972b6c05cc9c4b87db4e35219d6187`. The scoped source/config/documentation
patch tree was verified to match the local Git tree byte for byte before push.
The published commit uses the actual latest-main commit as its parent; no local
snapshot commit is published.

## Focused local checks

- `python3 -m unittest discover -s tests -p test_catalog_activation.py -q`:
  8 tests passed (final run 6.635s).
- Optimized version of that command: 8 tests passed (final run 6.912s).
- `test_live_observation.py`: 24 tests passed (20.253s).
- `test_local_catalog.py`: 12 tests passed (9.928s).
- `test_grant_broker.py`, with local Unix-domain socket binding permitted:
  31 tests passed (10.389s).
- `make lint`: infrastructure lint and compileall passed.
- `git diff --check`: passed.
- The completed example task is 866 canonical JSON bytes; its observation prompt
  is 1,276 bytes. Both fit the production 1,024/2,048-byte ceilings and the exact
  production request validator accepts the observation profile offline.

The activation tests seed four opaque historical records (pending, failed,
failed, validated) in a legacy installation without a catalog. They assert byte
preservation of the legacy policy and ledger, refuse all historical IDs and a
new pending ID at observation review, require a fresh terminal challenge through
the existing runner CLI, and pass the new approval through the unchanged v2
observation review and a separate fake observation authorization/response.
Sockets, credential helper, worker execution and publication are fenced. No live
request, coding agent or application change is performed.

The read-only preflight test compares all temporary file bytes before/after and
denies Runner construction. Failure tests cover STOP in either installation,
omitted legacy STOP coverage, existing state, path overlap/symlinks, absent/changed
binary pins, stale source HEAD, unsupported broker schema, oversized tasks and
unresolved budget reservations. A separate fence confirms credential contents are
never read. No legacy approval record is interpreted by the helper.

## Full regression and hosted CI

Final full-suite reruns with temporary local Unix-domain socket binding allowed:

- `make test`: 625 tests in 251.616s, OK (skipped=2).
- `python3 -O -m unittest discover -s tests -q`: 625 tests in 252.080s,
  OK (skipped=2).

The initial sandboxed normal and optimized full suites each ran 625 tests with
nine errors and two skips. Every error was an existing broker fixture denied a
temporary Unix-domain socket bind (`PermissionError: Operation not permitted`).
The affected 31-test broker suite passed once that local permission was allowed;
no production guard or test was weakened.

The two local skips are the missing `age` executable and opt-in real Codex OS
boundary probes (`FC_CODEX_PROBE_BINARY`). Hosted workflows retain their existing
dependency setup. The broker workflow now runs activation tests normally and
under optimized Python on Linux and macOS; full-suite PR workflows discover them
automatically. No workflow is manually triggered or monitored for this task.
Hosted CI results are left to the separate reviewer, per the completion policy.

## Operator boundary

Follow [CATALOG-ACTIVATION.md](CATALOG-ACTIVATION.md) after separate review/merge.
Independently author and review a new policy, run its no-initialization preflight,
prepare exactly one new task, inspect its entire specification and authorize it
on the controlling terminal. Initialize the separate observation broker once and
stop at successful Sprint 6.13B read-only observation review. A later live canary
requires its own separate authorization; no inference is part of installation.
Historical state is preserved, and the existing API budget is reused.
