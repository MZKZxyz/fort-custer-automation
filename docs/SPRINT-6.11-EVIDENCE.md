# Sprint 6.11 evidence

Observed October 23, 2026, Pacific time. No real Codex inference, login,
credential inspection/copying, API billing enrollment, application publication,
live canary, merge or deployment occurred. All new executable probes use fresh
temporary synthetic data. This document records the technical-blocker outcome;
it is not a deployment attestation.

## Baseline and official protocol

Connected GitHub confirmed latest automation main
`4adff7e2f850f5d18dde9e51ad10a1764e194101`, merged Sprint 6.10 PR #19.
The initial local checkout was Sprint 6.9 `f78728c`. Shell fetch failed because
the configured proxy was unavailable. All 19 changed files were retrieved from
the exact main SHA through GitHub, and the reconstructed local Git tree matched
remote tree **`7d1df49dc61dabc9175782a615040f50a72ef76c`** exactly. The PR is
parented to actual main, not to a locally fabricated upstream history.

Installed CLI version: `codex-cli 0.163.0`. Inspected `exec --help`,
`login --help`, `exec-server --help`, `app-server --help`, and generated both
stable and experimental app-server schemas. Official source was inspected at
`rust-v0.163.0` (tree `83086188ae0614bd882818ff1aa23f3194962012`).
The official latest-release query returned 0.164.0; it was not installed or
assumed compatible. See [protocol hashes](evidence/sprint-6.11/protocol-hashes.json)
and [architecture/source references](CODEX-AUTHENTICATION-ARCHITECTURE.md).
No auth-status query, cache read or undocumented OAuth endpoint was used.

## Real executor and OS probe

Command (the environment grants local socket/process permissions separately):

```sh
python3 -m src.codex_boundary_probe --codex /opt/codex/bin/codex
FC_CODEX_PROBE_BINARY=/opt/codex/bin/codex python3 -m unittest discover -s tests -p test_codex_boundary.py -v
```

The diagnostic exits 1 by design. It launches the actual official exec-server,
performs initialize/initialized, validates the server version and uses real
filesystem/process RPCs over stdio. The final targeted suite runs **6 tests: all pass**, testing both exposure and
the explicit blocked result when platform sandbox controls fail. No OS denial
is credited in that case. `FC_REQUIRE_CODEX_SANDBOX=1` remains the strict operator
check and fails here; diagnostic regression success does not waive it. The version-rejection/admission tests are policy tests;
the executor tests are actual processes, not mocked transport classes.

[Retained Linux probe](evidence/sprint-6.11/linux-executor-probe.json):

| Attempt | Observation | What this establishes |
| --- | --- | --- |
| Read synthetic 0600 auth through `/bin/cat` | Readable | Same-UID dedicated login fails the confidentiality assumption |
| Read synthetic auth with `fs/readFile`, no sandbox | Readable | Filesystem API is another executable capability |
| Read synthetic controller policy, omit sandbox | Readable | Executor is not an immutable broker policy boundary |
| Unknown RPC | Real server rejects | Protocol validation only |
| Read five denied sentinels under explicit sandbox | Helper setup fails | No OS denial guarantee; results deliberately null |
| Read/write permitted workspace file under sandbox | Positive controls fail | Prevents setup failure from being counted as safe isolation |
| Write unapproved file under sandbox | Not credited | Requires successful positive controls first |

The helper reports `app-server socket directory must be a user-owned directory
with mode 0700`. This cloud masks that directory; no permission changes or
attempts to access the real daemon socket were made. The legacy Landlock probe
also explicitly refuses filesystem-restricted execution without bubblewrap;
it is not used as a fallback. No VM, cross-user denial, full network/resource
isolation or hostile-descendant termination was demonstrated here.

## Broker and adversarial scope

| Requested attack | Available evidence / remaining limit |
| --- | --- |
| Controller policy/approval ledger/publisher credential reads | Synthetic sentinel denial attempts; OS enforcement unavailable, no real ledger/secret read |
| Escape workspace | Synthetic protected read without sandbox succeeds; Linux enforcement unverified; scoped hosted Mac denials verified below |
| Unknown executable tool / configuration override / auth mode | Worker hard gate rejects before subprocess or claim; real server rejects unknown RPC |
| Modify unapproved files | Existing artifact allowlist checks plus attempted actual helper write; no OS success claimed |
| Reuse execution grants | Existing atomic race, restart/replay and generation-fence tests; synthetic broker only |
| Forge completion | Existing request/token/generation/source/candidate checks and independent reconstruction tests; no trusted worker QA |
| Start another worker | Broker one-slot tests and new live-refusal-before-startup test; no live receiver exists |
| Continue after STOP/cancellation | Existing durable holds, deadline/STOP and no-retry tests; whole-VM external termination still missing |

The new broker-refusal test verifies its DB bytes remain unchanged and no
process starts. It does not invent a live grant. Independent QA and publication
authorization remain separate. The [machine-readable readiness result](evidence/sprint-6.11/architecture-readiness.json)
states zero live capacity, one future worker ceiling and each missing component.

## Regression and environment limitations

Linux Python 3.12.14 / Node v24.19.0:

- Full suite with default command sandbox: 485 baseline tests, 9 errors,
  1 skip; local AF_UNIX bind was prohibited by the outer sandbox.
- Full suite with local socket permissions and the new tests at that point:
  **490 tests, 3 failures, 2 errors, 2 skips**, 185.719 seconds. All five
  failures/errors arise from `Untrusted endpoint owner` at the ancestor check:
  `/` is UID 65534 here; `/tmp` is also UID 65534. This is correct fail-closed
  behavior, not an auth-boundary regression. A protected workspace TMPDIR did
  not fix the untrusted `/` ancestor. No owner check was weakened or patched.
- Final targeted boundary suite: 6 tests pass, zero skips. The unavailable
  platform is validated as blocked; strict activation still fails. No inference
  was invoked.
- Infrastructure lint, compileall and diff whitespace validation passed.

The workflow installs the official pinned CLI on Ubuntu and macOS, tests real
executor observations and the blocked state when positive controls fail, and
runs the full regression suite. The strict operator requirement is unchanged;
CI does not authorize deployment. Local failures above remain recorded.

### Hosted verification of code commit cd441310

[Ubuntu job 120299896523](https://github.com/MZKZxyz/fort-custer-automation/actions/runs/39919153248/job/120299896523)
completed successfully for code SHA
`cd441310fd5fc579a87e2fc8aca712767e49412f`:

| Check | Exact result |
| --- | --- |
| Broker and kernel transport | 31 tests, pass, 6.320 seconds |
| Activation preparation | 19 tests, pass, 4.218 seconds |
| Optimized activation preparation | 19 tests, pass, 3.918 seconds |
| Actual executor diagnostic | 6 tests, pass, zero skips, 0.353 seconds |
| Full regression | 489 tests, pass, 2 expected skips, 135.217 seconds |

The full suite's optional real-executor class is not enabled in that step; its
two methods run in the separate six-test diagnostic above. The other skip is
the existing encrypted-restore test because `age` is not installed. No OS enforcement success should be
inferred from the diagnostic's pass: the [retained hosted observation](evidence/sprint-6.11/hosted-linux-executor-probe.json)
explicitly says unavailable and records helper loopback setup denial followed
by a panic inspecting `allowed.txt/.aws` (`Not a directory`). An earlier strict
run correctly failed that same control. The final regression checks the blocked
outcome instead of waiving deployment requirements.

All five other workflows at this code SHA passed: Execution simulation, Verify
planner dry run, Trusted canary offline rehearsal, Offline infrastructure
security (including its normal/optimized regressions and isolated rehearsal),
and Offline activation contracts. macOS targeted broker, activation, optimized
activation, actual executor diagnostic and synthetic QA transfer steps passed;
an additional broad macOS full-suite run was still pending when this section
was prepared and no passing result is claimed for it. The maintained workflow
runs the full suite on Linux and the requested targeted tests on both platforms.
Hosted CI is not evidence about an operator's actual Mac or VM.

### Hosted macOS: actual OS denial controls pass

The final [macOS job 120303342433](https://github.com/MZKZxyz/fort-custer-automation/actions/runs/39920209096/job/120303342433)
at `a15de1ec85da7d529311b07976081a78f9df15b3` passed: broker **31 tests**
(41.682 seconds), activation **19 tests** (35.046 seconds), optimized activation
**19 tests** (33.421 seconds), real executor diagnostic **6 tests**, zero skips
(1.782 seconds), and synthetic source/QA transfer. The maintained Ubuntu job
in that same run also completed successfully: full regressions **489 tests**,
**2 expected skips**, **136.371 seconds**.

[Retained macOS probe](evidence/sprint-6.11/hosted-macos-executor-probe.json)
reports `platform_sandbox_state=verified`: permitted reads and writes succeed,
all **five** denied sentinel reads fail, and unapproved file writes fail with
the file unchanged. These are actual official executor/platform sandbox calls,
not mocks. Both filesystem and subprocess auth reads still succeed **without**
the sandbox, and omitting the policy reads the protected controller sentinel.

This provides scoped OS enforcement evidence on a hosted Mac. It does not
establish complete model-tool routing, cross-user/VM deployment, MCP/network
denial, resource enforcement, broker authorization or whole-guest termination.
The operator's actual deployment remains unverified and live capacity remains
zero. The earlier cloud/Ubuntu failure observations remain valid for those
environments and are not generalized to macOS.

## Canary source refresh

GitHub main is still `d82c272b47486161bf9f37508b69fe3240678655`, tree
`2148e1f387d8eff643c1672762fae3b3c3924c76`. All **33 blobs** were retrieved
at that SHA and independently verified using Git's SHA-1 blob framing.
The full source manifest remains
`1b76b0476f0cee84cefa72d93fccd4dc94f7304d85f3520beb97ee8b0dbe561a`.
See [retained source observation](evidence/sprint-6.11/canary-source.json).

`node --test test/analyzer.test.js` passed its file-level run.
`node test/analyzer.test.js` passed **14/14** analyzer tests, zero skips/failures.
A deterministic module probe confirmed right movement initially succeeds,
`Object.isFrozen(directions.right)` is false, and changing its second element
to 99 makes that movement return null. Mutation was memory-only; no source
file was changed. No live coding task was approved or launched.

## Unfulfilled activation criteria

Live broker migration, a complete supported credential/tool boundary, deployed
worker/QA receivers, publisher intake, target Mac denial/resource/watchdog
evidence and one actual supervised invocation remain blocked. This PR delivers
the allowed technical-blocker outcome and concrete diagnostic evidence; it
does not claim all nine live-architecture acceptance criteria are satisfied.
See the [Mac runbook](LIVE-CANARY-RUNBOOK.md) for exact supported diagnostic
commands and the mandatory stop before unsupported authentication/dispatch.
