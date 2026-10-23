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

### Final code checkpoint

At code tree `6bd53ab937fa712c24ba86e1441a8f7939c9bd5a` (draft PR code commit
`d994119964d9ec496493d8aaad3de66b64d7f86f`), the final targeted normal suite
passes **23/23**, zero skips, **3.748 seconds**. The full socket-enabled optimized
suite passes **512 tests**, zero failures/errors, **2 expected skips**,
**130.224 seconds**. Final local `git write-tree` matches the uploaded code tree
exactly. Documentation-only follow-up evidence does not change the tested code.

## Hosted Linux and macOS verification

At `d994119964d9ec496493d8aaad3de66b64d7f86f`, the complete
[broker workflow run 39926312477](https://github.com/MZKZxyz/fort-custer-automation/actions/runs/39926312477)
passed on both platforms. Decoded job logs establish:

| Check | Ubuntu job 120323451294 | macOS job 120323450907 |
| --- | --- | --- |
| New API suite, normal | 23 pass, 6.299 s | 23 pass, 39.487 s |
| New API suite, optimized | 23 pass, 4.580 s | 23 pass, 32.603 s |
| Existing broker/transport | 31 pass, 6.636 s | 31 pass, 51.276 s |
| Existing activation | 19 pass, 4.175 s | 19 pass, 37.032 s |
| Existing activation optimized | 19 pass, 4.188 s | 19 pass, 26.942 s |
| Official executor diagnostics | 6 pass, 0.358 s | 6 pass, 1.707 s |
| Synthetic subprocess source/QA transfer | pass | pass |
| Full regression | 512 tests, pass, 2 expected skips, 145.953 s | intentionally Linux-only |

All targeted suites have zero skips. The official diagnostic still reports no
inference and no live readiness. Its Mac filesystem positive controls and five
sentinel denials pass; its Linux sandbox positive controls fail and are reported
as unavailable, never credited as OS isolation. This is unchanged scoped
Sprint 6.11 evidence, not proof of complete API tool mediation or target deployment.
All six workflows passed at this tested code checkpoint: Synthetic grant broker
and local peer transport, Execution simulation, Verify planner dry run, Trusted
canary offline rehearsal, Offline activation contracts and Offline infrastructure
security (including normal/optimized regressions and its isolated rehearsal).
The final follow-up commits change evidence documentation only; GitHub reruns
checks on those commits as usual.

## Linux executor CI correction after the documentation follow-up

[Run 39927040701](https://github.com/MZKZxyz/fort-custer-automation/actions/runs/39927040701)
failed on Ubuntu in `test_real_transport_same_uid_auth_counterexample_and_unknown_rpc`.
The report had `same_uid_auth_readable=true`, but its single process/read sample
had `same_uid_process_auth_readable=false`; bubblewrap's independent filesystem
sandbox positive control failed with `RTM_NEWADDR: Operation not permitted`.
The successful earlier run remains historical evidence, not a guarantee that
this subsequent run or environment supported the same operations.

The diagnostic now separates three observations:

- A same-UID local `/bin/cat` subprocess reads a nonsecret baseline positive
  control and then the private synthetic authentication marker, without invoking
  a sandbox helper. The direct executor filesystem counterexample and omitted
  policy/controller sentinel check remain required.
- Official executor process RPCs get their own positive control. Output is
  collected with sequence cursors through terminal status (five bounded reads),
  rather than equating the first output sample with completed execution. Failed
  startup/helper control or missing terminal evidence reports `unavailable` and
  null credential-access evidence. A helper failure after a successful control
  also remains unavailable, not an observed access denial. An actual observed
  denial requires a successful control and explicit terminal denial evidence;
  the real-executor test still rejects that result as the expected counterexample.
- Filesystem sandbox verification requires successful permitted read/write
  controls, all five explicit read denials and the unapproved write denial.
  Failed setup returns null denial evidence. A genuine failed denial now reports
  `failed-denial`, never `verified`, and fails the existing real security test.

Every outcome still has `live_ready=false` and `inference=false`. The macOS
read/write and all five sentinel assertions, unknown RPC rejection, source-only
synthetic fixtures, strict `FC_REQUIRE_CODEX_SANDBOX=1` behavior and all admission
assertions remain intact. There are no changes to real credential handling,
API accounting, budget limits, grants or live gates.

Nine deterministic regression tests cover split/delayed process output,
missing terminal evidence, Linux bubblewrap network-namespace failure before
and after a successful control, positive-control requirements, explicit observed
denial classification, preserved successful Mac controls and missing write or
failed denial evidence. Local real official executor results: **16/16 pass**,
zero skips, normal **0.390 s**, optimized **0.837 s**. The local filesystem
sandbox is explicitly unavailable and is not credited as isolation. Lint and
compile checks pass. Hosted rerun results are reported with the PR fix outcome.
