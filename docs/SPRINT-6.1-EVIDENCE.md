# Sprint 6.1 — offline implementation evidence

Review date: 2026-10-22 (America/Los_Angeles).
Base: `2231a9a31519dc00a9f5a5db002a62c4834cf8c5`, the merged Sprint 5.9 plus
macOS portability fix. The connected GitHub read API confirmed this was `main`
during this session. Shell Git fetch was unavailable because the workspace
proxy was unreachable; no alternate authentication or network bypass was used.

## Validation

- Baseline: `python3 -m unittest discover -s tests -q` — 181 tests, OK, one skip.
- Catalog suite: `python3 -m unittest discover -s tests -p test_local_catalog.py -q`
  — 12 tests, OK.
- Final regression: `python3 -m unittest discover -s tests -q` — 193 tests, OK,
  one skip (`age` is not installed; encrypted-restore validation remains skipped).
- `make lint` — pinned image inputs/live gate validation and Python compileall
  passed. No images were built or live gates enabled.
- `git diff --check` — passed.

All tests use temporary synthetic Git repositories, generated mock CLI binaries,
mock workers or fake GitHub services. The new CLI smoke test runs only
`task-list` and `task-prepare` against a temporary operator policy. It never
approves through stdin or invokes a live model. New timeout checks execute local
fixture JavaScript; the output-limit check executes a local Python flood fixture
through the same supervisor. Node 24 suppresses passing-test stdout, so the flood
fixture deliberately does not depend on Node reporter behavior.

## Security and acceptance coverage

| Requirement | Evidence |
| --- | --- |
| Distinct reviewed tasks | Two tasks with different issues, instructions, allowed files and checks prepare/approve/validate independently. A third fixture exercises a second configured repository containing only `demo.js`, with no analyzer paths, through the CLI and mock execution. |
| Repository/source/issue provenance | Reject unlisted repo, wrong exact identity, wrong local origin, unreviewed issue, unapproved SHA and wrong reviewed source manifest. |
| Content-bound approval | Reject changed paths, prompt, checks, limits and snapshot, including recomputed record digests; reject changed on-disk policy. Full controller resolution is compared again before approval/claim. |
| Untrusted issue and worker output | Malicious title/body/comments remain snapshot data and never enter the prompt or policy. Worker-returned check suggestions do not change executed QA argv. |
| Explicit command/path grammar | Reject shell, eval, substitution, glob, option injection, missing check file, protected/unsafe paths, unsupported mode/approval/budget, bool timeout and unknown protocol/schema. |
| Resource limits | A reviewed one-second QA timeout fails the task; supervisor flood output is bounded to its existing 8 MiB capture and returns `output_limit`. |
| Candidate boundary | Outside files, deletion and symlinks fail; existing legacy tests also cover ignored files, source links, binary/version pins, credential exclusion, CLI protocol failures, guardian termination and cancellation. |
| Repetition/conflicts | Single-use catalog IDs, exact one-time approval, expired tasks, persistent STOP, restart-held running claim and conflicting execution fail closed. All configured source roots participate in scratch separation checks. |
| Legacy compatibility | Existing local runner, terminal, telemetry and publication tests pass unchanged. The old no-protocol record shape and fixed Issue #3 QA remain supported. |
| Publication boundary | A newly validated catalog task is explicitly rejected before publisher reconstruction. Existing tests retain the single-candidate pins, terminal publication approval, evidence checks and fake-remote recovery cases. |

## Preserved artifacts

Pre-change and post-test SHA-256 hashes match:

| Checkout artifact | SHA-256 |
| --- | --- |
| `state/automation.db` | `53991a6539c1ada5fbf23c8ff89523c253b801b8e5ca834e003fb88304e62fc6` |
| `docs/SPRINT-5.9.md` | `22fa4544657cfcd6b8353ef84ae0633a72318ed370b9377a599a0cbdf4f9cc6a` |
| `docs/SPRINT-5.9-EVIDENCE.md` | `2c643e8f50c7e5807387cee183f014bd32df98db7af65a12171b55db21c49f1b` |

The publisher retains the exact original constants:

- Run: `d808dca82ca74d65ba0b7ba9ab7197de`
- Base: `c4f480abb309a7a4d141b20ab462552a868ef0e3`
- Candidate manifest: `1b76b0476f0cee84cefa72d93fccd4dc94f7304d85f3520beb97ee8b0dbe561a`
- Candidate tree: `2148e1f387d8eff643c1672762fae3b3c3924c76`
- Validated local revision: `4542a5735d67cc0eb5da0447c5ea81bbcbc5a19d`

No historical records were migrated, regenerated, deleted or reauthorized.
The original operator local-runner ledger, original local policy and trusted
server source objects for this real run are **not present in this checkout**.
Their external integrity/publishability therefore remains unverified; synthetic
compatibility tests are not substituted for original evidence.

## Limits and remaining work

See [Sprint 6.1](SPRINT-6.1.md) for the schema, workflow and proposed Sprint 6.2
interfaces. Only literal existing files and reviewed Node syntax/test argv are
supported. File creation/deletion, arbitrary executables, installers, repository
or issue discovery, automatic promotion, retry, scheduling and generalized
publication are unsupported and have no executable fallback.

The supported spending envelope is zero API spend with subscription-only login
and no paid refill/fallback. A CLI-enforced per-task subscription monetary/token
cap cannot safely be implemented with this existing adapter. CPU/RAM/kernel disk
quotas and isolation of arbitrary hostile QA JavaScript are also not provided.
QA retains the trusted, disposable, credential-free host prerequisite. Tests
must be reviewed for deterministic behavior; fixed command selection cannot make
arbitrary application tests deterministic. These are explicit unsupported
requirements, not claims of newly enforced hard limits.

The operator-owned policy/SQLite history and colocated digests are not signatures
against privileged host tampering. Source origin and issue review are operator
provenance assertions; this workflow does not authenticate them through a live
GitHub request. No real Codex execution, server-repository mutation, deployment,
production activation, merge or scheduler was performed. Creating the requested
automation-repository draft PR is the only delivery mutation outside the workspace.
