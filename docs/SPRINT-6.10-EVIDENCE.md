# Sprint 6.10 evidence

Observed October 22, 2026, Pacific time, in Linux with Python 3.12.14 and
Node v24.19.0. No Mac was provisioned. No real Codex task, personal account
authentication, application publication, merge or deployment was performed.

## Base and source provenance

Connected GitHub independently verified main including merged #18 at
`f78728cfd7f2649f27a172c5e3ab4a4978fbc81b`, tree
`81ce54cf03787645646892ffb52b9470a2107878`.
The supplied checkout initially stopped at #17 and origin/main was older still.
Shell fetch failed because its inherited proxy was unreachable. The GitHub
connector supplied the 13 #18 files pinned to the merged commit. The resulting
local Git tree was checked against the exact remote tree; the signed merge
commit was reconstructed from GitHub's verification payload/signature and its
Git object hash matched the remote commit exactly. Work therefore starts from
the actual reviewed main, not from a patch approximating it.

Canary main was refreshed through connected GitHub and remained
`d82c272b47486161bf9f37508b69fe3240678655`. All 33 regular blobs were downloaded
at that revision to a disposable directory outside the automation checkout and
each was checked against its pinned Git blob SHA. No application repository
branch/file was changed. Complete export: 290,013 bytes, source manifest
`1b76b0476f0cee84cefa72d93fccd4dc94f7304d85f3520beb97ee8b0dbe561a`.

| Source | SHA-256 |
| --- | --- |
| tools/maze-analyzer/solver.js | 2e7d95f2852998ba2a278fb3019d5571ec44f31b336ca267334de23f979b98f5 |
| test/analyzer.test.js | d9071610dd4e40e3ea7f67c4ac0c679c352738ab3e8603e63a4a8052d66bfcd3 |

The exact two-file writable allowlist is those two paths. The review-only task
definition is `freeze-direction-vectors-s610`; it intentionally has no matching
issue or independent approval yet. No Issue #3 coding authorization was reused.

## Commands and observed results

| Command | Observed result |
| --- | --- |
| `python3 -m unittest discover -s tests -q` | 483 tests in 124.949s, OK, skipped=1 |
| `python3 -m unittest discover -s tests -p test_grant_broker.py -q` | 30 tests in 6.302s, OK |
| `python3 -O -m unittest discover -s tests -p test_activation_readiness.py -q` | 18 tests in 6.304s, OK |
| Final preparation suite after external-QA STOP/guard test | 19 tests in 3.878s, OK |
| Final optimized preparation suite | 19 tests in 3.744s, OK |
| `python3 src/infrastructure.py lint` | Pinned image inputs and live gate validated |
| `python3 -m compileall -q src infra tests` | Exit 0 |
| `git diff --check` | Exit 0 |
| Pinned source: `node --test test/analyzer.test.js` | File passed, 5.596s; Node summarized one test file |
| Pinned source: `node test/analyzer.test.js` | All 14 individual tests passed, 10.133s |
| Pinned source: direction mutation probe in runbook | before=1, after=null, outerFrozen=true, nestedFrozen=false |
| Trusted direction-vector oracle against vulnerable baseline | Rejected, as expected: nested vector is not frozen |
| `python3 -m src.integration_control --policy /nonexistent` | Exit 1, all eight prerequisites blocked/unknown, no activation |

The one full-suite skip is the existing encrypted backup/restore test because
`age` is unavailable; actual encrypted restore remains unverified. The default
sandbox denied local AF_UNIX bind (EPERM), causing nine socket-related errors
in the initial broker run. The approved broader execution profile passed the
broker suite and full regression using only temporary synthetic Unix sockets.
No public listener or privileged service was created.

An initial new gate test failed because its imported historical fixture patches
the live gate to allow synthetic setup. The test now explicitly restores the
saved real gate before asserting refusal; production gating was not relaxed.
The final complete regression above includes that correction and durable
usage/exhaustion additions.

## Coverage and limits

Existing full-suite tests cover process-raced single claims, legacy/coordinator
duplicates, expired/replayed approvals, lost replies, wrong kernel peers,
descriptor/environment sentinels, malicious output, STOP before/during lifecycle,
abrupt startup death, supervised child cleanup, immutable source/check evidence,
publication separation and held recovery. New tests exercise full-source
preparation, drift, extra fields/files/paths/modes, candidate/QA receipt tampering,
controller-side no-execution, missing identity separation, inventory immutability,
all eight blocked readiness categories, structured usage exhaustion and durable
restart holds, unknown telemetry, and publication rejection of broker claims.

The tests use synthetic approved tasks, same-UID processes and fabricated
telemetry/QA receipts where applicable. No fixture result proves actual
cross-user filesystem denial, macOS isolation, real Codex authentication,
subscription availability, an externally isolated QA service or VM termination.
The production adapter remains blocked. The external QA receipt validator needs
authenticated transport and a trusted installed service; hashes alone are not
proof. Receiver-side durable fencing and production broker QA finalization are
not implemented. The oracle has a negative baseline check; no live candidate
was generated or accepted.

## Readiness and remaining barriers

| Category | Actual disposition |
| --- | --- |
| Software integration complete | Blocked: live relay, QA receiver/finalization and publisher intake missing |
| Broker migration verified | Blocked: historical writers/stores not reconciled; no fresh same-ledger live approval protocol |
| External worker isolation verified | Unknown: no actual Mac principals/VM probes |
| Codex authentication safely provisioned | Blocked: personal-account files not proven inaccessible to generated code |
| Independent QA isolation verified | Unknown: no real QA guest/service; immutable oracle integration still required |
| Publisher separation verified | Unknown: no production separate-identity intake or credential verification |
| Resource enforcement verified | Unknown: no external hard CPU/RAM/disk/egress/whole-guest watchdog deployment |
| Live activation approved | Blocked: separately reviewed versioned activation mechanism absent |

Original operational ledgers were not available in this workspace, so no real
historical grant was declared reconciled. Inventory completeness is explicitly
unknown. No database timing/dual-write atomicity is claimed. Legacy approvals
remain historical and cannot become live broker grants automatically.

Direct CLI personal-account authentication is unsupported under the proposed
generated-code principal. No credentials were inspected, copied, forwarded or
provisioned. No supported subscription-compatible credential-isolating relay
was established. Dedicated identity/API alternatives require a separate reviewed
consent, exposure model and billing plan; no fallback or paid refill is enabled.
Telemetry does not enforce a monetary cap. Process-group termination cannot
guarantee removal of malicious setsid descendants; external guest termination
and absence evidence are mandatory.

## CI

Linux/macOS matrix includes broker/transport tests, new preparation tests and
optimized safety checks. Remote results will be recorded after the requested
draft PR is created. Local Linux success is not a macOS result or operator
activation evidence.
