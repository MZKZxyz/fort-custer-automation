# Sprint 6.6 — offline implementation evidence

Base: verified latest `main` commit
`97183627480051f660b0188b770520c753a1ba83`, including merged Sprint 6.5 PR #14.
The workspace's stale `origin/main` was not treated as authoritative. Shell Git's
configured proxy was unavailable; the connected GitHub read tools supplied the
merged commit and eight changed files. The reconstructed local base commit and
source tree (`48fc687e320b2e098ea7828c888585d560e6a9ef`) match GitHub exactly.

## Scope and compatibility

New daily protocol/store: `daily-planning-v1`. Existing discovery, promotion,
reviewed catalog, execution, QA and publication protocols, source records,
approvals and evidence hashes are unchanged. Only the designated daily discovery
store accepts collection records; other subsystem SQLite handles are read-only.
Daily observations are embedded as bounded report summaries, not written into
the prior orchestration ledger. Existing catalog resolution defaults still use
the original privileged controller path; explicit `observation_only=True` uses
read-only local source validation without importing its worker or approval module.
Promotion retains its original helper names as compatibility imports.

The old Actions cron trigger was removed. Manual legacy workflow dispatch remains
available; its separate state-branch adapter is not used by this daily controller.
The example daily profile and launchd template are disabled. No installation or
activation command is part of imports, initialization, tests or PR delivery.

## Offline coverage

`tests/test_daily_planning.py` has 37 tests using fake clocks, synthetic public
issues, fake GET transport, temporary SQLite stores and real read-only subsystem
reconciliation. Existing synthetic fixtures create reviewed source manifests,
controller QA and draft publication evidence; mock workers/providers perform no
real inference or application publication.

| Boundary | Evidence |
| --- | --- |
| Complete daily cycle | Real catalog/discovery/promotion/execution reconciliation; JSON/text SHA-256 receipts; private output permissions; available coding/promotion reviews |
| Determinism/idempotency | Same date and reviewed config yield same ID; repeated launch performs no GET or report replacement; changed config or date yields distinct ID |
| Local schedule | Disabled default; manual execution; LA date boundary; DST fold suppression and gap catch-up; no backfill; backwards date/epoch refusal; in-cycle clock-jump failure |
| Claims and restart | Persistent flock exclusion; transactional unique claims; incomplete claim blocks new dates; explicit recovery reason visible in `inspect`; recovered identity never reruns |
| Public collection | Only approved client/server; GET method and no Authorization despite credential sentinel; fixed timeout; request limits; partial collection transaction rollback; rate-limit and network timeout recorded without retry |
| STOP/cancellation/time | Initial and mid-scan STOP including broken symlink; cancellation; monotonic duration; interval supervisor interrupts a blocked adapter; STOP during report write prevents success receipt |
| Evidence failure | Missing promotion, corrupt policy/execution, unknown cycle protocol; fresh source failure never falls back to prior successful report; invalid QA remains blocked |
| Real status reporting | Synthetic completed independent QA and recorded local draft PR shown with usage and unknown current GitHub state; no remote merge status invented |
| Output/storage | Altered report rejected; bounded report bytes; physical SQLite page cap and rollback; successful retention tombstones; failed deletion is non-successful; disk-full and interrupted second-file writes leave incomplete claims |
| Privilege separation | A fresh interpreter executes an entire synthetic cycle and verifies runner, promotion, publisher and Codex modules were never imported; action APIs remain unused; original source files/ledgers byte-identical |
| Inert installation | Explicit `init` only; disabled config/plist, no KeepAlive/RunAtLoad; no legacy cron trigger; CLI history/report/failure exits |

Existing discovery and security suites additionally cover pagination/response size,
forged identities, changed snapshots/comments, untrusted prompt-injection text,
immutable proposal revisions, source protocol compatibility and existing approval,
publisher, one-worker, budgeting and STOP constraints.

## Limitations retained explicitly

- Unattended credential/identity isolation is not provisioned. Same-UID modes do
  not protect credentials, policy or STOP from that UID; credential-free manual
  operation is the documented safe fallback. Validators currently require private
  files owned by the invoking identity, so cross-UID evidence provisioning needs
  an independently reviewed read-only export or mount arrangement.
- POSIX signal supervision bounds ordinary Python work and report finalization,
  not uninterruptible kernel I/O or hostile native extensions. Abrupt death or
  failed persistence leaves an incomplete claim requiring operator recovery.
- Independent source transactions and before/after hashes are not an atomic
  multi-ledger snapshot. No live PR observation adapter is shipped. Recorded
  draft PRs remain local evidence with current provider state unknown.
- Successful report pairs have bounded automatic retention. Failed/partial files,
  receipts, claims and discovery revisions are preserved and consume a hard
  configured capacity; reaching capacity stops work and requires reviewed archival.
- There is no backfill, automatic retry, stale-claim theft, automated approval,
  coding launch, automatic merge or deployment. Changing reviewed configuration
  creates a new identity; it does not grant any downstream action authority.
- Subscription cost remains unknown/unsupported as a hard $10/day billing cap.
  No inference is launched. Future independent cost enforcement must guard the
  dispatch/provider boundary; telemetry displayed by this report cannot enforce it.

No live GitHub issue/application write, Codex execution, scheduler installation,
merge or deployment was performed. The draft automation-repository implementation
PR is a separate user-requested delivery action. No operational database was
initialized or changed; all exercised cycle/store state was temporary test data.

## Reported validation results

Final source validation in the managed Linux workspace:

- `python3 -m unittest discover -s tests -q`: **391 tests in 121.124 s;
  390 passed, one existing skip** (`age` unavailable).
- New daily suite: **37 tests passed** in 15.005 s.
- `make lint`: passed (infrastructure live-gate/pinned-input checks and Python compilation).
- `python3 -m src.daily_planning --help`: passed.
- `git diff --check`: passed.

An earlier full run exposed a compatibility regression in the extracted catalog
read path. The default controller/publisher resolver was restored; observer
callers explicitly opt into the import-isolated read path. The targeted publisher
suite (32 tests) and the final full suite pass with that correction. The final
source also covers STOP activation during report persistence, which prevents a
success receipt and leaves the claim incomplete.
