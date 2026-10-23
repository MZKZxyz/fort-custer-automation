# Sprint 6.12 evidence

Observed October 23, 2026, Pacific time. No real service key was requested,
inspected, copied, exported or used. No chargeable inference/connectivity call,
live coding, application edit, approval, merge or deployment occurred. HTTPS tests
use a clearly synthetic marker and mocked connections only.

## Baseline and supported contract

GitHub confirmed latest automation main `c21776c0ad46661efd3ac318a4d9236f4d8c204a`,
merged Sprint 6.11 PR #20. The supplied checkout was Sprint 6.9 `f78728c`.
Shell fetch failed because the configured proxy was unreachable. Thirty changed
files were fetched through connected GitHub at the exact main SHA. Local
`git write-tree` then matched remote tree
`24d7f4002f3ecdf1ba9cb974bf241b1fead6424d` exactly. The draft PR is parented to
actual remote main; the local reconstruction commit is not an upstream parent.

Official model documentation was checked for supported Responses endpoint,
400,000-token context, `gpt-5-nano-2025-08-07` snapshot and standard USD rates.
The deprecated GPT-4.1 nano snapshot is deliberately excluded. Official
`openai/openai-python` generated REST types were inspected: request blob
`90154795ba355792269f9b51d860b7058d55cd68`, response blob
`3ec1fd01f5230d7770db34ecdb442a5a70f5d6f4`. The implementation uses Python 3.12+
stdlib HTTPS, so no SDK installation or undocumented endpoint is required.
See [official source links and pricing limitations](API-CONTROLLER.md).

## Deterministic new tests

Command: `python3 -m unittest discover -s tests -p test_api_controller.py -v`.
Initial complete 23-test run: **23 pass, zero skips, 3.745 seconds**.
After reservation provenance/audit receipt additions: **23 pass, zero skips,
4.567 seconds**. Optimized run at the preceding checkpoint: **23 pass, zero
skips, 5.163 seconds**. Final validation/hosted results are recorded below.

| Area | Exercised evidence |
| --- | --- |
| Successful usage | Actual input/cached/output/reasoning reconciliation, incomplete billed outcomes, no double-counting reasoning |
| Retry/duplicate | Completed replay returns one receipt, changed prompt conflict, ambiguous duplicate refuses second dispatch |
| Durable state | Real spawned process exits 23 after committed reservation; restart retains it; reinitialization refused |
| Concurrency | Eight attempts from four spawned processes admit exactly one reservation |
| Budgets | Exact $10 daily exhaustion, lifetime exhaustion across midnight, policy mismatch and clock rollback refusal |
| Calendar | Los Angeles midnight after DST transition; unresolved hold carries forward, explicit evidence reconciliation |
| Grant security | Actual existing Broker fixture; principal/fence/deadline/STOP/source-commit change checks, no request before approval |
| STOP during inference | Usage still billed, delivery refused |
| Untrusted output | Unknown fields/model/status, hosted/function tools, invalid JSON/duplicate keys, malformed usage, oversize response refuse and retain hold |
| Tools | Unknown shell/controller/grant tools, absolute/traversal/unlisted paths, extra/invalid arguments, duplicate JSON rejected |
| Isolation | All executable receiver calls refuse, including fake verified receipts; synthetic proposals execute nothing |
| Credential boundary | Synthetic private-file checks, exact HTTPS endpoint/header placement, credential echoes/exception strings suppressed |
| HTTP errors | Mock 401/403/429/500/302 and network failures; no error-body exposure or automatic retry |
| Time bound | Mock stalled helper exercises wall deadline, terminate/kill and bounded cleanup |
| Read-only | Status/audit leave ledger bytes unchanged, missing ledgers never initialized |
| Live gates | Real transport rejected by task integration before access; connectivity defaults blocked; readiness reports zero live workers |

No mocked transport result establishes actual provider availability, billing
correctness, deployed OS isolation or whole-guest termination. New tests run in
normal and optimized Python on Linux/macOS in the existing broker workflow.

## Local full regression and environment

Python 3.12.14 / Node v24.19.0, Linux:

- Infrastructure lint and compileall pass; diff whitespace validation passes.
- Default sandbox full regression: **512 tests, 9 errors, 2 skips, 130.957
  seconds**. Every error is `PermissionError: Operation not permitted` binding
  AF_UNIX sockets in existing synthetic broker transport tests. No new API test
  fails. The skips are optional real-executor probes and unavailable `age`.
- A rerun with local socket permissions was requested; results follow below.

The permission restriction is not weakened or counted as passing isolation.
Hosted Linux regression results are required before acceptance criterion 7 can
be claimed. Hosted macOS targeted tests are platform compatibility evidence,
not proof about the operator's actual Mac deployment.

## Canary revalidation without application edits

Connected GitHub main remains `d82c272b47486161bf9f37508b69fe3240678655`,
tree `2148e1f387d8eff643c1672762fae3b3c3924c76`. All **33 blobs** were
retrieved at that SHA into a disposable `/tmp` snapshot; every Git SHA-1 blob
hash was independently verified. No application repository was edited.
Both `node --check` commands pass. `node --test test/analyzer.test.js` passes its
file-level test (1/1, 7,784.008 ms). `node test/analyzer.test.js` passes **14/14**,
zero failures/skips (7,483.235 ms). A memory-only import probe confirms right
movement succeeds initially, `Object.isFrozen(directions.right)` is false, and
setting the second element to 99 makes right movement return null. Source bytes
remain unchanged. The trusted direction-vector oracle still requires the future
fix and must run outside candidate-writable storage in independent isolated QA.
The selected two-file canary review example remains unchanged and unapproved.

## Security assumptions and unresolved blockers

The implementation trusts controller code/configuration, protected OS storage,
reliable local SQLite/fsync, a correct OS clock and a current reviewed price table.
The provider token/context contract bounds the reservation; new pricing dimensions
are rejected. Accounting cannot cover charges made elsewhere in the API project.
No top-up, recharge, automatic budget reset, live grant minting or approval exists.

Live broker migration/admission, complete atomic API/tool dispatch integration,
verified credential-free tool receiver, isolated external QA, target-host
filesystem/network/resource/watchdog evidence and separately authorized draft
publisher intake remain incomplete. Synthetic broker checks preserve existing
fences, STOP, source freshness and recovery holds but do not establish live
readiness. No supplied isolation boolean or receipt changes that state.
The operator must review prices and perform the optional one-request connectivity
procedure manually; it was not run by Codex or CI. Live coding, autonomous
approvals, merging and deployment remain disabled.

### Socket-enabled regression result

The local socket-enabled full suite passes: **512 tests, zero failures/errors,
2 expected skips, 134.720 seconds**. No endpoint-owner checks were weakened.
The optional official-executor class and missing `age` retain their existing
skips. The new targeted suite also passes optimized: **23 tests**, zero skips,
**5.437 seconds**; infrastructure lint/compileall pass. This supersedes the
sandbox-restricted regression result for functional verification while retaining
that environment observation above.
