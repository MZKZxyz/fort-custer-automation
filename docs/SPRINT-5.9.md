# Sprint 5.9 — guarded GitHub publication

This sprint implements a manual publisher; its tests make no live Codex calls or
server writes. The successful execution `d808dca82ca74d65ba0b7ba9ab7197de` and its
stored evidence must remain unchanged. No scheduler, production policy, earlier
publisher, canary gate, merge or deployment capability is enabled.

## Boundaries and manual prerequisites

The runner approval uses separate `/dev/tty` input/output handles, requires both
handles to be terminals, and fails closed without a controlling terminal. There
is no stdin, `--yes`, or argument-token fallback. Publication requires a separate
`PUBLISH <complete binding>` terminal challenge; coding approval is insufficient.
The authenticated principal is the operator account controlling the terminal and
protected ledger, as in Sprint 5.8. This is not a remote identity/approval service.

Use a trusted, credential-free coding host. Run the dedicated publisher process
(`python3 -m src.local_publication`) only after all coding and QA processes have
terminated. Provision credentials under a separate publisher OS identity/host,
with filesystem controls denying the coding identity access. Transfer or grant
read access to the preserved ledger, policy and trusted source snapshot through
operator-controlled infrastructure. The publisher needs write access to its same
publication ledger. Do not run concurrent copies of the state or coding workers
while publisher credentials are accessible. These host/account controls are manual
prerequisites: separate Python processes running as the same user are not security
isolation. The runner never reads publisher credential files or inherits GitHub
keys in the model environment. Publisher reconstruction executes Git, not candidate
JavaScript, dependency installers, hooks, or Codex.

Provision a GitHub App installed **only** on `MZKZxyz/fort-custer-server`, with
Contents read/write, Pull requests read/write, and implicit Metadata read access.
No Actions, Workflows, Administration, deployment, merge or approval permissions
are needed. Have an operator/security reviewer explicitly select that identity
and obtain a short-lived installation token outside this tool. Alternatively,
review a fine-grained PAT restricted to that repository and those permissions.
GitHub Contents write is broader than this publisher's API surface: enforce main
branch protection separately. No token is created, installed, discovered through
`gh`, read from the environment, or copied from an operator's broad CLI login.
The configuration declares reviewed scope; the program cannot attest the actual
server-side scope. Verify it in GitHub before selection.

Provide a private regular JSON file (mode 0600, outside scratch and any worker
access) with the following schema. Do not commit it or paste a real token into
logs. This example is documentation, not installed credentials:

```json
{
  "repository": "MZKZxyz/fort-custer-server",
  "security_reviewed": true,
  "operator_selected_identity": "REVIEWED_APP_INSTALLATION_ID",
  "permissions": {"contents": "write", "pull_requests": "write"},
  "token": "OPERATOR_PROVIDED_SHORT_LIVED_INSTALLATION_TOKEN"
}
```

Revoke by revoking the token or suspending/removing the App installation; for a
PAT, revoke it in GitHub settings. Set the persistent STOP switch first. Do not
place credentials on a host accessible to Codex. No credentials were provisioned
as part of this sprint.

## Artifact integrity and provenance

The original temporary workspace is unnecessary. Reconstruction reads the
validated SQLite record's full binary patch, loads the exact base commit from a
trusted local Git source, exports its safe blobs into a fresh directory and
applies the patch with a fresh Git index. It checks input/candidate SHA-256
manifests, candidate Git tree, exactly the two authorized changed files, fixed
Issue #3 task and commands, original task approval history, usage, six successful
QA entries and fourteen recorded analyzer passes. Original task approval expiry
is historical; it does not expire a validated artifact. The current policy must
still match its original digest. No test results are invented or tests rerun.
Missing source objects, patch, QA output, or original policy block publication.
Node TAP and current Unicode summary counts are understood.

The first publication is pinned in code to the supplied run, base, candidate
hash, candidate tree and validated local revision. Its deterministic publication
commit has the validated tree and the original source commit as its sole parent.
It intentionally differs from the original QA revision: Sprint 5.8 created that
revision on a synthetic local Input commit and did not retain its commit metadata
or original parent history. The new commit identity, original revision, tree,
patch/evidence identity, complete PR body/action and expiration are bound to the
publication challenge. Only Git object creation, **new** branch ref creation and
a draft PR POST exist in this transport. There is no update-ref or push operation.
The remote commit, tree, parent, branch and exact PR identity are checked.

**Trust limitation:** the existing SQLite record and colocated hashes are ordinary
operator-owned files, not signatures. They cannot prove original QA provenance
against privileged local tampering. The compiled experiment allowlist independently
pins the supplied candidate content and tree, but cannot authenticate rewritten
QA logs. An attacker able to rewrite controller code/ledger or impersonate the
operator can forge approvals. Preserve the original ledger and an independently
reviewed offline backup; use separately administered signing/approval infrastructure
if protection against that attacker is required. This sprint does not manufacture
a signature or retroactively claim one for the existing run.

Requests are immutable through the application interface. Approval is single use,
stored in SQLite, and consumed by a durable publication claim before writes.
A unique run prevents a second publication request or branch after restart.
The artifact digest binds the entire original run including its recorded history.
Read-only preparation does not modify that run or regenerate the candidate.

## First authorized publication commands

These commands are for a later separately authorized operator session. They were
not executed against the real experiment in this sprint. Replace `/operator/...`
with the existing policy/state and a trusted source path in that unchanged policy.
Run from the reviewed automation checkout. Do not change its policy to enable
publication, renew task approval, execute the coding task again, or reset state.

1. Inspect the durable validated execution:

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state inspect d808dca82ca74d65ba0b7ba9ab7197de
```

2. Reconstruct and review the exact patch, six QA entries, destination, title,
   deterministic commit, tree, branch, artifact identity and ten-minute request:

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state publish-prepare d808dca82ca74d65ba0b7ba9ab7197de
```

Record the returned `id` as `PUBLICATION_ID`. This offline stage explicitly cannot
establish remote absence. It cannot be approved until the dedicated publisher's
read-only remote preflight has succeeded. Complete preparation using the reviewed
publisher credential; this checks repository identity, unchanged main, and absence
of both the proposed branch and any PR (including closed PRs):

```sh
python3 -m src.local_publication --policy /operator/local-policy.json --state /operator/local-state --credential /operator/publisher-credential.json prepare d808dca82ca74d65ba0b7ba9ab7197de
```

3. Review the complete proposed branch and draft PR body, then explicitly approve
   through the controlling terminal within ten minutes:

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state publish-inspect PUBLICATION_ID
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state publish-approve PUBLICATION_ID
```

Type exactly `PUBLISH ` followed by the complete displayed binding. No token is
accepted on the command line. This is separate from any earlier `APPROVE` response.

4. Execute in the dedicated publisher process and verify remote state:

```sh
python3 -m src.local_publication --policy /operator/local-policy.json --state /operator/local-state --credential /operator/publisher-credential.json execute PUBLICATION_ID
python3 -m src.local_publication --policy /operator/local-policy.json --state /operator/local-state --credential /operator/publisher-credential.json inspect PUBLICATION_ID
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state publish-inspect PUBLICATION_ID
```

5. Open the resulting GitHub draft URL, inspect the diff, provenance and QA, and
   review/merge manually only if separately appropriate. The title is exactly
   `Fix inherited-property maze direction lookup`. The body references Issue #3
   without a closing keyword. The broader maze-generation investigation remains
   open. This tool never merges, approves, deploys, or marks the draft ready.

## Cancellation, failure and recovery

Cancel one publication or activate the existing sticky global kill switch:

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state publish-cancel PUBLICATION_ID
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state cancel
```

Cancellation cannot retract an already accepted API operation; inspect GitHub
and revoke access if necessary. The process checks cancellation before mutations;
network calls have bounded timeouts. Never delete/reset the ledger or STOP file,
force-push, overwrite a branch, or switch to a fresh state directory to bypass a
hold. A per-state file lock serializes the publisher; SQLite persists its claim.
There is no unattended retry or automatic expiry extension.

- `prepared` requires remote preflight and terminal approval; `approved` can be
  claimed once. `publishing` reconciles exact branch and commit identities after
  a crash. Branch creation is atomic at the final candidate commit: no empty
  base branch/push window exists. Git object uploads are content-addressed and
  safe to repeat; matching remote refs are retained, never overwritten.
- `pr-requested` is committed **before** the PR POST. After a lost response or
  restart, execute may adopt only the single exact matching draft. An empty PR
  listing after an ambiguous POST does not prove failure; no second POST is
  issued. Preserve the hold and ask the operator to reconcile with GitHub.
- `completed` repeats verify the same result; they do not create another PR.
  Modified/missing branches, conflicting/closed/non-draft PRs, changed main,
  missing permissions, rate limits and network errors stop. No main writes occur.
- Expiry also blocks unfinished recovery. Read-only manual GitHub inspection
  remains possible outside this tool. This first-experiment interface deliberately
  provides no automatic reauthorization, hold release, cancellation undo or new
  request for an expired run. Such recovery requires a separately reviewed
  operator reconciliation/migration retaining the original request and audit
  history; do not rewrite its expiry or reuse the approval.

All inspect, reconstruction, preparation, approval, upload and verification steps
consume **no ChatGPT usage**. Remote steps use only GitHub APIs. Only the earlier
coding execution used ChatGPT. Given the preserved valid ledger, original policy
and base Git objects, this candidate can be published **without another Codex
execution**. Those operator artifacts are not present in this checkout, so the
real run's publishability has not been verified here. Missing durable evidence
is a blocker; do not recreate or fabricate it.

## Offline validation and protocol review

Run `python3 -m unittest discover -s tests -v` and `make lint`. Integration tests
use generated fake CLI output, disposable Git input, synthetic QA artifacts and
a fake GitHub service. No production/server checkout or saved execution state
is used. They cover valid drafts, independent approval, preflight, expiry,
forgery/reuse, input/artifact/QA alterations, tree mismatch, wrong destination or
base, branch/PR response loss, recovery, cancellation and restricted transport.

Upstream review on 2026-10-22: `openai/codex`'s
[`codex-rs/exec/src/exec_events.rs`](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs),
blob `06565c097b28d3bf2ad592943cc30c776b45e236`, includes
`cache_write_input_tokens` and `reasoning_output_tokens` in addition to the three
required counters. It also includes tool/error item types outside this runner's
reviewed contract. The compatibility fix accepts extra nonnegative integer
counters, retains the three required measured counters, and invents no defaults.
Missing/negative/float/bool/null required counters and malformed extra counters
fail closed. Version/binary pinning, event sequencing, unknown-item rejection,
auth/quota failure handling and no-retry/no-provider-fallback remain unchanged.
New tool types have not been enabled by a telemetry compatibility adjustment.
