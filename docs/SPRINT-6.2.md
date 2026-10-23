# Sprint 6.2 — human-authorized catalog draft publication

`python3 -m src.catalog_publication` publishes validated `local-catalog-v1`
executions using the new, explicit `catalog-draft-v1` request protocol. The
Sprint 5.9 module, pins, commands and historical Issue #3 interpretation remain
unchanged. Neither publisher accepts the other's execution protocol. Unknown
versions fail closed; there is no fallback, migration, automatic renewal,
scheduling, PR approval, merge, release or deployment operation.

## Operator workflow

Complete coding and independent QA under the Sprint 6.1 credential-free host
requirements. No new Codex execution is needed to publish an existing validated
artifact. Stop all workers before making publisher credentials accessible.
Transfer the intact operator-owned policy, ledger and exact trusted source Git
objects through separately administered infrastructure. Preserve their paths as
specified in the original policy; changing policy changes its digest. Missing
objects or evidence block publication. Do not retrofit the historical Issue #3
state or create another ledger to bypass a hold.

Use a separately administered publisher OS identity/host, with OS permissions
denying the coding identity access to credentials and publication state. Prepare,
preflight, approve and execute under the same publisher OS identity: its UID is
bound to the request and audited. A separate Python process under the same macOS
user is **not meaningful security isolation**. This separation is an external
prerequisite, not an OS boundary established by Python.

The following commands are an operator runbook, not instructions to publish a
live candidate during development. Use the complete publication ID returned by
`prepare`. All paths refer to the protected, original artifacts.

```sh
python3 -m src.catalog_publication --policy /operator/catalog-policy.json --state /operator/catalog-state prepare EXECUTION_ID
python3 -m src.catalog_publication --policy /operator/catalog-policy.json --state /operator/catalog-state inspect PUBLICATION_ID
python3 -m src.catalog_publication --policy /operator/catalog-policy.json --state /operator/catalog-state --credential /operator/publisher.json preflight PUBLICATION_ID
python3 -m src.catalog_publication --policy /operator/catalog-policy.json --state /operator/catalog-state approve PUBLICATION_ID
python3 -m src.catalog_publication --policy /operator/catalog-policy.json --state /operator/catalog-state --credential /operator/publisher.json execute PUBLICATION_ID
python3 -m src.catalog_publication --policy /operator/catalog-policy.json --state /operator/catalog-state --credential /operator/publisher.json verify PUBLICATION_ID
```

Review the complete specification, patch, QA evidence, repository, exact source
and destination branch, file set, Git tree, deterministic publication commit,
new branch, title, body, expiry and binding. `approve` prints the request and
requires exactly `PUBLISH <complete binding>` through separate `/dev/tty` handles
that must both be terminals. There is no stdin, flag, environment, issue-body,
model-message or unattended approval path. The trusted Python controller API
accepts the response for the terminal adapter and offline tests; importing it is
not a security boundary against a local attacker. Coding authorization cannot
substitute for publication authorization.

Requests expire ten minutes after preparation; remote preflight and separate
approval must occur within this interval. The durable single-use approval is
consumed before any write. The complete PR body contains the controller's stored
QA command results; oversized evidence (body over 60,000 UTF-8 bytes) is unsupported
and fails closed. Titles use the reviewed catalog ID, without interpolating
untrusted issue titles. Source branch names use a deliberately conservative
literal grammar; unsupported Git ref names fail closed. Publication supports
existing-file edits, as does catalog v1; it does not extend coding permissions.

`inspect` is local evidence inspection. `verify` requires a completed request and
performs only remote reads. Repeated completed `execute` also only verifies the
exact existing result. Local inspection remains available after expiry or STOP;
remote operations remain blocked by STOP. A completed result can be verified
after authorization expiry because no further remote write is permitted.

## Credentials and transport

Select a GitHub App installation or fine-grained PAT restricted to the exact
catalog repository (`MZKZxyz/fort-custer-server` or
`MZKZxyz/fort-custer-client`), Contents read/write, Pull requests read/write and
implicit Metadata read. Review actual server-side installation scope separately.
The publisher checks the declared scope and selected identity, but cannot prove
the token's effective permissions. Separate narrowly restricted credentials are
required for different repositories. No credential is generated, acquired,
renewed, discovered through `gh`, or read from environment variables.

Provide a private regular JSON file with no group/other access, outside coding
access. This placeholder example is not an installed credential:

```json
{
  "repository": "MZKZxyz/fort-custer-client",
  "security_reviewed": true,
  "operator_selected_identity": "OPERATOR_REVIEWED_INSTALLATION",
  "permissions": {"contents": "write", "pull_requests": "write"},
  "token": "OPERATOR_PROVIDED_SHORT_LIVED_TOKEN"
}
```

The repository is independently derived from the freshly resolved reviewed
catalog and compared with this file and the remote identity. Credential JSON
cannot select a different destination. The API transport permits repository,
base, feature-ref, commit and all-state PR reads; blob/tree/commit object creation;
new feature-ref creation; and draft PR creation with maintainer edits disabled.
Write payloads and endpoint/method combinations are restricted. There are no
ref-update/delete, push, ready-for-review, approval, merge, release or deployment
capabilities. No candidate command, test, hook, installer or Codex is invoked by
the publisher. Git runs with isolated configuration, disabled hooks and fsmonitor,
no replace objects, and credential-free environment; candidate code is only data.
GitHub write credentials themselves remain broader than this application's
surface: enforce branch protection and credential revocation externally.

## Artifact verification and trust assumptions

Reconstruction starts from SQLite and exact trusted source Git objects, never
the original worker root. It re-resolves the entire catalog entry and policy,
checks original authorization and validated history, controller usage counters,
exact QA names/argv and successful exit/reason records, patch size and content,
source manifest and Git tree, candidate manifest and Git tree, and exact changed
files within the reviewed allowlist. A fresh Git index applies the stored binary
patch and compares its canonical full-index diff. Source modes and content are
preserved. No QA is rerun; a model saying tests passed supplies no evidence.
Original coding approval expiration is historical, not a new publication limit.

The immutable request binds the entire execution record's digest, full resolved
specification, original approval and QA digests, exact source/base, repository,
file set, manifests, tree, original QA revision, deterministic publication commit,
fixed author/committer, message, branch, full PR action, publisher UID and expiry.
The publication commit uses the candidate tree and exact trusted source as its
sole parent. It differs from QA's synthetic local commit. SHA-1 is Git's existing
object identity format; SHA-256 binds canonical request/evidence data.

**External trust limits:** SQLite and its colocated hashes are not signatures.
This general protocol has no independently compiled candidate pin like the legacy
Issue #3 experiment. An attacker who can rewrite policy, ledger, controller or
operator identity can forge evidence and approvals, including QA logs. The
original synthetic QA revision metadata was not retained by the runner: its
revision is format-checked and content-bound, but cannot be independently
recomputed from a patch. Content/tree reconstruction is independently checked;
historical QA provenance depends on the protected controller ledger. Preserve
independently reviewed backups or use separately administered signing/approval
infrastructure if that attacker is in scope. The publisher does not manufacture
retroactive signatures or claim that ordinary hashes authenticate privileged
local edits. Operator source provenance and QA's disposable, credential-free host
requirements from Sprint 6.1 still apply.

## Conflicts, cancellation and recovery

A state-directory file lock serializes publication. SQLite transactions retain
requests, UID/time audit events and durable claims. One request per execution
prevents a replacement branch or renewed approval after failure, expiry or
cancellation. No historical run is rewritten by publication.

The state sequence is `prepared` → `approved` → `publishing` →
`branch-requested` → `pr-requested` → `completed`. Read-only remote preflight
requires exact repository identity and base commit, no feature branch, and no
open **or closed** PR for that head. Execution repeats these checks before object
writes. Unexpected branches/PRs are rejected before uploading objects. A matching
branch can be adopted only after a durable branch claim; an exact draft can be
adopted only after the durable PR claim. Every API write checks evidence, expiry,
STOP/cancellation, base and remote conflicts again. Object responses must match
local Git blob/tree/commit identities; resulting commit parent, metadata, feature
ref, and complete draft PR metadata are read back and compared.

Content-addressed object creation can repeat after an interruption. New ref
creation is atomic and never updates an existing ref. A lost branch response can
adopt the exact matching ref; if no ref exists it may retry creation. Before the
PR POST, `pr-requested` is committed. After any interruption in that state, only
the single exact matching existing draft is accepted. An empty list does not
prove the POST failed: there is no second POST, automatic hold release or expiry
extension. Expired unfinished recovery is blocked; use read-only GitHub inspection
and separately reviewed operator reconciliation outside this tool. Do not delete
or reset the request, audit history, ledger or STOP file.

```sh
python3 -m src.catalog_publication --policy /operator/catalog-policy.json --state /operator/catalog-state cancel PUBLICATION_ID
python3 -m src.local_runner --policy /operator/catalog-policy.json --state /operator/catalog-state cancel
```

Cancellation cannot retract an already accepted request. GitHub does not offer
an atomic transaction spanning base checks, object writes, branch and PR creation;
a base/ref can change between a check and an API call. Rechecks and final
verification detect observed changes and retain the hold; they cannot roll back
accepted operations. Network calls have 30-second timeouts. Repository identity
is checked by its exact allowlisted full name; numeric repository IDs are not
currently catalog fields. Repository ownership/rename protections, server-side
branch protection, token scope and host filesystem isolation remain externally
enforced assumptions. There is no unattended recovery or cleanup mutation.
