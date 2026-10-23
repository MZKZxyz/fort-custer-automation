# Sprint 6.4 — controlled discovery promotion

Issue review is evidence assessment. It does not authorize code execution.
Discovery proposals remain untrusted even with valid snapshot hashes. Promotion
only authorizes adding a particular reviewed task to a particular catalog.
The runner still requires its own fresh `APPROVE` operation; publication retains
its separate protocol and authorization. No runner, publisher, scheduler, model,
Codex process, deployment or service is started by promotion or import.

## Trust boundary and manual transfer

This implementation uses the allowed **manual export-and-import fallback**.
`apply` consumes a promotion approval and writes a new export, never the live
policy. `import` is a separately invoked operator operation with a second terminal
challenge. It does not open the discovery database or perform network reads.
The operator reviews the entire export before installation. There is no automatic
watcher, direct discovery-to-policy mutation, or noninteractive authorization.

Use protected operator directories outside Git sources, disposable worker scratch
and the controller checkout. Promotion does not establish OS privilege separation.
Discovery must have no write access to live policy, promotion ledger, exports,
controller code, STOP files or credentials. Transfer discovery evidence read-only
into the trusted operator review environment. Keep the promotion ledger and live
policy in the operator environment, away from the discovery identity. If that
separation is unavailable, retain exports for review and do not run import in the
shared discovery environment. A terminal prompt is a human-intent gate, not an OS
sandbox. The controller remains manually operated after import.

Policy, reviewed-entry, export and promotion ledger files must be owned by the
current operator, mode 0600 (or stricter), single-link regular files. Parent
components cannot be symlinks or writable by group/others. The filesystem root
owner (including its mapped UID in containers) and current operator are trusted
ancestor owners. A sticky shared temporary directory is accepted only above the
private immediate parent. ACLs, mounts, root compromise and other processes under
the operator identity are not proven safe by these checks. Protect them externally.

## Operator workflow

Use `python3 -m src.catalog_promotion` (the promotion interface). For example,
using a shell array to preserve the exact arguments:

```bash
umask 077
promotion=(python3 -m src.catalog_promotion
  --ledger /operator/promotion/promotion.sqlite
  --policy /operator/controller/policy.json
  --discovery /operator/evidence/discovery.sqlite
  --stop /operator/discovery/STOP
  --stop /operator/controller/STOP)
"${promotion[@]}" init
python3 -m src.issue_discovery --state /operator/evidence/discovery.sqlite inspect PROPOSAL_ID
"${promotion[@]}" prepare PROPOSAL_ID --task-id isolated-fix \
  --reviewed-entry /operator/promotion/reviewed-entry.json --risk low
"${promotion[@]}" inspect PROMOTION_ID
"${promotion[@]}" approve PROMOTION_ID
"${promotion[@]}" apply PROMOTION_ID --export /operator/promotion/isolated-fix.json
```

`init` exclusively creates a separate ledger; it cannot migrate or overwrite any
existing discovery/execution/publication database. `attempts` lists every event
and rejected attempt ID; `inspect ID` displays its full history. Inspection works
under STOP and does not create a missing database.

Create `reviewed-entry.json` independently, with **every** Sprint 6.1 entry field:
`repo`, `repository`, `source`, `input_hash`, `issue`, `issue_snapshot`, `allowed`,
`instructions`, `checks`, `limits`, `mode`, `approval`. Use the exact schema and
controller-selected checks described in [Sprint 6.1](SPRINT-6.1.md). No executable
field defaults to proposal content. Operator input must select the exact approved
source commit and full repository manifest, repository identity, exact allowed
files, bounded instructions, Node QA argument arrays, timeout/resource policy,
and issue provenance. The issue snapshot must exactly match the original evidence;
it remains data and is never interpolated into instructions. Allowed files are
also checked against the existing repository ceiling and protected-path rules.
No policy repository/issue allowlist is expanded by promotion. If necessary, a
separate controller policy review must occur first, followed by fresh preparation.

The source SHA must equal both discovery's observed commit and the source approved
in policy. Changed source requires a new discovery revision, never a silent rebase.
The manifest is independently computed/verified from local Git objects by the
existing resolver. This reads local Git with hooks disabled; it does not run
repository code or contact remotes. Suggested QA/paths/text cannot set task fields.

For an explicitly requested current public issue check, add `--network` to
`prepare`. This enables only anonymous GET of the exact issue through Sprint 6.3's
allowlisted transport. It compares the full projected issue, rejecting closure or
any metadata/content changes. Approval and export repeat that check when selected.
Without the flag, no network occurs and the displayed binding explicitly says
`offline-historical-only`. Offline review cannot prove current GitHub state.
Import performs no network operation; short-lived checks still cannot eliminate
changes on GitHub after review or detect a comment edit with unchanged issue data.

`approve` prints the full bound document, escaping terminal control characters,
and requires typing `PROMOTE FULL_BINDING` through `/dev/tty`. Preparation expires
after 300 seconds. The resulting approval expires after another 300 seconds,
is single-use, and cannot be renewed. No `--yes`, stdin answer, environment grant,
callback or CLI bypass exists. Model output and coding approval are not accepted.
If review takes longer, create a new attempt; prior attempts remain preserved.

After manually transferring/reviewing the export in the protected controller
operator context, invoke the separate import with its explicit destination:

```bash
python3 -m src.catalog_promotion \
  --ledger /operator/promotion/promotion.sqlite \
  --policy /operator/controller/policy.json \
  --stop /operator/discovery/STOP --stop /operator/controller/STOP \
  import --export /operator/promotion/isolated-fix.json
```

Import requires typing `IMPORT FULL_EXPORT_DIGEST` at a controlling terminal. It
checks the ledger's exact authorized export, expiry, destination, STOP locations,
complete task/proposal binding and exact prior policy bytes. Import does not
accept an export on its own as authorization. Keep the protected ledger available
to the operator import context; never place it under discovery control. Promotion
and import changes do not prepare, approve, execute or publish a coding run.

## Validation and risk rules

Intake opens discovery state read-only and verifies schema, deterministic proposal
ID, snapshot digest, repository, issue identity/state/chronology, full projected
issue/comments and references, source SHA, supported analysis version, reproducible
analysis fields and ordered discovered/proposed audit. The original discovery
configuration digest remains an attestation in the proposal identity; the original
configuration bytes are not stored by Sprint 6.3 and cannot be independently
recovered here. Hashes are integrity checks, not signatures of trustworthy intent.
Any related closed/unavailable observation conservatively blocks the proposal,
even if a later observation reopened it. Preserve it and rediscover/review manually.

Risk must be explicitly selected as `low` (isolated change), `medium` (application
change), or `high` (manual escalation). High operator/discovery risk, security
labels, and conservative security/authentication/database/financial/deployment
terms in evidence, instructions or paths block promotion. Instructions requesting
controller/approval/policy/secret/publication authority and protected controller
paths are rejected. These checks are deliberately conservative and can produce
false positives. They are not semantic proof of low risk: the operator must
identify obfuscated/domain-specific risks. High risk has no override in this
interface; handle it through a separate manual engineering/security review.
Risk can never expand repository, issue, path, command or resource allowlists.

## Atomicity, audit and recovery

The separate SQLite ledger uses immediate transactions and append-only triggers.
It records original proposal/snapshot and full review evidence, task, source
manifest, risk, destination, raw policy revision and semantic/result digests,
domain-specific authorization binding, timestamps, state transitions, rejections,
filesystem intents, completion and uncertain failures. It never updates discovery
or historical execution/publication state. Same-user SQLite is not tamper-proof.

Export commits its intent **before** publishing a complete 0600 file with an
atomic no-clobber link. Import locks a persistent destination-specific lock file
(shared across ledgers), validates every resulting task through the unchanged
catalog resolver, fsyncs a 0600 temporary file, rechecks policy bytes and STOP,
atomically replaces policy, then fsyncs the directory. Existing task IDs cannot
collide; unrelated definitions and schema 1 remain unchanged. Raw-byte policy
changes, including whitespace, invalidate prepared promotions. Concurrent imports
serialize; the losing stale revision fails closed. All other operator policy
editors must honor `POLICY.promotion-lock`. Uncooperative same-user/root edits can
race the final check/rename; ordinary filesystems offer no compare-and-swap for
arbitrary editors. STOP also has a final-check race; no execution is initiated.

On `export-intent`/`import-intent` without completion, or `import-uncertain`, never
replay the old grant. Read the ledger and destination without modifying history.
Compare the current policy's semantic SHA-256 with the recorded resulting digest
and its raw SHA-256 with the recorded prior revision. An error after replacement
may mean the complete new policy landed; an error before it leaves the old policy.
Reconcile and retain an external incident record. If the old policy remains,
prepare a fresh attempt after resolving the failure. If the new task is present,
treat the catalog as installed and retain uncertainty evidence. Do not delete lock
files during recovery, remove STOP automatically, edit old ledger rows, or reuse
an approval. Abrupt process death may leave a private temporary file; inspect and
remove only that orphan manually after reconciliation. There is no automatic retry,
renewal, migration, retention deletion or grant recovery.

No production activation is included. See [offline evidence](SPRINT-6.4-EVIDENCE.md).
