# Sprint 6.5 — manual operational orchestration

The orchestrator observes discovery, promotion, reviewed catalog, local controller
approvals/executions, independent controller QA and draft publication evidence.
It does not dispatch, approve, run Codex, publish application changes, merge,
deploy or schedule anything. `preview` is an ordered advisory backlog, not an
execution grant or a concurrent worker wave. The existing runner's one-worker
claim remains the authority. All production profiles remain disabled.

## Configuration and commands

Copy `config/orchestration.example.json` into a protected operator directory,
mode 0600. Use absolute paths to existing subsystem evidence. The execution file
must be exactly the configured policy state's `local.sqlite`. Explicit discovery
and promotion paths are required even if their valid ledgers are empty. A missing
ledger is an unresolved source, never an empty successful backlog. Do not
initialize missing source ledgers to conceal lost historical evidence.

Provision only the new orchestration ledger's parent directory (0700), separate
from all source ledgers, policy, worker scratch and repository source trees.
Files must be operator-owned private single-link regular files under protected
parents; symlinks are rejected. The observer reuses Sprint 6.4's path protections,
including its sticky temporary ancestor and mapped root-owner rules.

Operator-reviewed planning metadata belongs in the new configuration, never in
issue text or a modified catalog entry. For each existing catalog identifier,
add a `planning.tasks` entry with **exactly** these fields:

```json
{
  "reviewed-fix": {
    "entry_digest": "REPLACE_WITH_SHA256_OF_CANONICAL_REVIEWED_CATALOG_ENTRY",
    "priority": 10,
    "risk": "low",
    "depends_on": []
  }
}
```

The digest is `src.orchestration_evidence.digest(entry)` over the complete
operator-reviewed catalog entry. Priority is an integer from -100 through 100;
risk is `low`, `medium`, or `high`. Unknown/stale metadata blocks recommendations;
high risk requires manual escalation. No metadata supplies approval. Dependency
identifiers refer to catalog tasks. The current protocols do not attest that a
merged dependency is incorporated into another task's pinned source. Nonempty
dependencies, including missing/cyclic ones, therefore block recommendation until
an operator reviews new source/catalog evidence. Do not remove dependencies to
bypass this limitation. This sprint does not fabricate dependency completion from
successful QA or publication.

Run from the automation checkout:

```sh
python3 -m src.orchestrator init --config /operator/orchestration/config.json
python3 -m src.orchestrator sync --config /operator/orchestration/config.json
python3 -m src.orchestrator queue --config /operator/orchestration/config.json --offset 0 --limit 25
python3 -m src.orchestrator inspect reviewed-fix --config /operator/orchestration/config.json
python3 -m src.orchestrator status --config /operator/orchestration/config.json
python3 -m src.orchestrator report --config /operator/orchestration/config.json --format text
python3 -m src.orchestrator preview --config /operator/orchestration/config.json
```

`init` exclusively creates `task-orchestration-v1`, refusing existing files. It
validates the catalog and destination first. `sync` reads and reconciles sources,
then writes only this derived ledger. It never creates source records or grants.
`preview` reconciles current local evidence without writing even the derived
ledger. `queue`, `inspect`, `status`, and `report` open the derived ledger read-only
and show the last saved observation time with `historical_only: true`. Run `sync`
explicitly for a refreshed view. Nothing monitors or refreshes in the background.
The prior `src/orchestrator.py` dry-run flags remain available and unchanged;
operational subcommands do not use its old planning/reservation database.

JSON output can be redirected to an operator-selected local file. `--format text`
produces readable escaped key/value lines. Output never interprets issue text,
ANSI controls, shell substitution, instructions or agent status as executable
content. Queue pages are 1–100 entries, default 50; offsets must be nonnegative.
Reports aggregate usage/counters instead of dumping patches or subprocess logs.

## Evidence and lifecycle

| Evidence verified | Display and next independent operator step |
| --- | --- |
| Discovery proposal, original/related snapshots, deterministic analysis and discovered/proposed audit | `proposed`; inspect discovery, independently review a catalog entry |
| Bound promotion preparation and exact ordered promotion events | `awaiting-promotion-review`; separately approve/export/import through `src.catalog_promotion` |
| Completed import matching exact reviewed entry | `reviewed-catalog-task`; no coding grant |
| Complete reviewed catalog and no execution yet, or valid pending execution | `awaiting-coding-approval`; use `src.local_runner task-prepare`, inspect, and approve separately |
| Bound unexpired approval history | `approved-for-coding`; execution still requires the existing manual command |
| Authorized durable claim within its deadline | `running`; occupies the one-worker ceiling |
| Controller validation plus exact QA names, commands, successful codes/reasons, source/candidate bindings, patch and usage records | `awaiting-publication-review`; publisher must separately reconstruct and approve the exact candidate |
| Bound publication intent with incomplete branch/PR write sequence | `ambiguous-publication`; manual reconciliation, never retry automatically |
| Completed publication events, exact execution/QA hashes, commit identity and local draft result | `published-draft-recorded`; current GitHub state remains unknown |
| Above plus approved injected read-only GitHub observation matching repository, base/head, unique open draft PR, title/body and safety metadata | `awaiting-human-merge`; human review and merge remain manual |

No transient state is manufactured. The runner commits QA and validation together,
so there is no separate persisted `awaiting-independent-QA` stage in its current
protocol. Discovery's successful proposal already includes discovered evidence;
a standalone discovered stage is not fabricated. No local PR record proves that
a PR is still open, draft, unchanged or unmerged.

Adapters open SQLite with `mode=ro`, query-only transactions and exact known table
layouts/protocol checks. They never construct `Runner`, either publisher, a model
adapter or a GitHub write client. They reuse deterministic discovery intake with
network disabled and the established catalog resolver. That resolver reads only
local Git objects and origin metadata with fixed Git commands and disabled hooks;
it does not execute candidate code, QA, or model-selected argv.

The optional Python `reconcile(..., remote=callable)` integration is a read-only
observation capability: `(repository, branch, pr_number)` returns a projected
`{repository, base, head, prs}` snapshot. It has no write methods. This sprint's
CLI has **no network flag or live GitHub transport**, takes no tokens, and never
acquires publisher credentials. Tests inject mock reads. A future reviewed read
transport can use this capability; missing reads leave current provider state
unknown. Successful observations, including provider metadata, are retained as
immutable content-addressed references alongside local execution/publication
records. Failed reads block the associated task.

## Durable queue and recovery

Derived SQLite stores append-only `observations` and `snapshots`. Every task
references SHA-256-addressed documents with source names/identifiers. Original
ledgers and protocol versions are untouched. Consecutive identical syncs do not
append duplicate snapshots; returning to an older view after another observation
appends a fresh occurrence. Snapshots bind the full configuration digest. Reads
verify snapshot and referenced document digests, and clock regression is rejected.
History is never compacted, overwritten, migrated or auto-repaired.

Task IDs are catalog identifiers, `proposal:ID`, `promotion:ID`, or
`execution:ID`/`publication:ID` for unresolved evidence. Imported promotion and its
proposal collapse into the existing catalog task; processing does not create a
second active queue item. Distinct attempts/revisions retain their own evidence.
Ordering is priority descending, repository, issue string, then stable ID.
Pagination is stable within a snapshot; refresh may change ordering. Every item
includes repository/issue, state, priority/risk, evidence references, source IDs,
required action and blockers. Running tasks appear in reports, while the review
queue contains other tasks requiring operator attention, including approved tasks
awaiting a manual execution decision.

| Failure or uncertainty | Required recovery |
| --- | --- |
| Missing/unknown/corrupt source, changed source bytes during sync, schema mismatch | All recommendations blocked; inspect original protected evidence and sync manually after reconciliation |
| Changed policy, catalog/source, missing/forged approval or contradictory QA | Inspect `src.local_runner inspect RUN_ID` and pinned catalog/source; no automatic reauthorization |
| Expired coding approval/preparation | Existing single-use catalog ID remains consumed; review original evidence manually; no expiry extension/reset is added |
| Failed QA or controller cancellation | `rejected` or `cancelled`; inspect controller error/QA; a new task requires normal independent review |
| Running claim past deadline | `interrupted`; inspect process, watchdog, STOP and ledger; retain the hold until reviewed recovery |
| Promotion export/import intent without completion, failure, uncertain receipt | `src.catalog_promotion inspect ID`, compare exact export/destination evidence manually; never replay the grant |
| Publication expiration/cancellation | Existing publisher `inspect`; manual recovery under its original protocol |
| Interrupted publication, moved/deleted branch, changed/duplicate/closed/non-draft PR | Existing publisher `inspect`/`remote-inspect` and manual provider reconciliation; never repeat an ambiguous POST |
| STOP exists (including broken symlink) | All tasks blocked with STOP reason; no automatic clearing or worker operation |
| Unsupported legacy execution | Preserve the record/reference as blocked; inspect with its original Sprint 5.x policy and CLI |

Blockers preserve `last_supported_state` where available. Source disagreement
wins over any successful-looking status string. Any raw `running` record holds
planning capacity even if its authorization evidence is invalid. Two claims do
not become permission to launch more work. STOP checks include explicitly
configured locations and the policy-owned state STOP. Configure all subsystem
STOP locations; this observer cannot discover unconfigured authorities.

## Planning and security limits

`future_capacity` accepts 1–3; `max_active_workers` must be exactly integer 1.
The runner's existing transactional one-worker enforcement is unchanged.
Recommendations can include independent server/client candidates, ordered by
reviewed priority, with at most one candidate per repository and a bounded result
count. They are a **sequential advisory backlog**. Any active/interrupted or
unverifiable running claim, STOP, source failure, dependency uncertainty, consumed
failed/expired task, high/unknown risk or stale metadata blocks eligibility.
There is no auto-retry, timer, queue consumer or dispatch hook.

Reviewed wall-clock/subscription policy and controller usage are displayed when
available. CPU/RAM quotas, hard token limits and subscription dollar costs remain
unsupported/unknown. Subscription telemetry is not a hard API-dollar guarantee;
the old API-budget ledger is not repurposed as subscription accounting.

This is application-level read-only coordination, not an OS sandbox. Protect
controller code, source Git, source ledgers, planning metadata and the observer's
new ledger with OS ownership/ACLs and trusted backups. Hashes and SQLite triggers
are integrity aids, not signatures or resistance to a same-user/root attacker.
Read permissions should be granted through read-only mounts/OS capabilities;
Python alone does not prevent a privileged operator from invoking other tools.
Publisher credentials must remain inaccessible. The existing QA/publisher,
including candidate reconstruction and terminal challenges, remain authoritative.
The observer checks controller-authored QA and bindings; it does not replay the
patch or rerun tests, and its view cannot authorize publication.

Bounds: 10,000 rows per source table, 16 MiB decoded documents, 1 GiB source file,
100 queue entries per page and 100 planning recommendations. Bound violations
fail closed. Derived history grows append-only and needs operator storage
management/backup; there is no retention service. Independent source transactions
plus before/after file/WAL digests detect ordinary concurrent changes, not an
atomic multi-ledger snapshot or an adversarial change-and-restore race. Live
GitHub GETs likewise do not form an atomic provider snapshot.

Sprint 5.x records keep their original format and are retained unresolved by this
observer; no legacy success/grant is reinterpreted. Older production/API planning,
secure-ledger dispatch and metering databases are not imported into the local
catalog workflow. Unknown layouts block instead of being migrated. This is one
configured local controller's view, not a cross-host capacity lock. Those existing
systems keep their original STOP, budgeting, audit and authorization controls.
No external dashboard, network service, notifications, production activation,
GitHub application publication, merge or deployment is introduced.
