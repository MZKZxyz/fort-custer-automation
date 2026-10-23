# Sprint 6.6 — controlled daily advisory planning

`python3 -m src.daily_planning` coordinates anonymous public discovery and fresh
Sprint 6.5 read-only evidence reconciliation. It launches no coding worker,
Codex, QA command, promotion, approval, application publication, merge or deploy.
Reports explicitly have no authorization authority. The underlying coding worker
ceiling remains one. Three future agents is a target, never a scheduling grant.
There is no persistent network service, dashboard, notification or plugin action.

## Trusted configuration and first manual cycle

Use Python 3.11+ on a Unix host with `fcntl`, interval timers and IANA timezone
data. Commands run in the main Python thread. Protect this checkout, Python,
configuration, pinned local Git objects and authoritative source evidence. Do
not run this module inside a privileged controller process or a credential-bearing
login environment. No publisher token, model login, worker secret, SSH agent,
Git credentials, or operator credential home belongs in the scheduler identity.
Only anonymous public issue GETs to the two code-allowlisted Fort Custer client
and server repositories are supported. Configuration may explicitly select
one or both; neither issue text nor analyzer output can select scope or settings.

1. Provision a protected configuration directory and the *parent* of the dedicated
   output directory. Use directory mode 0700 and file mode 0600. Output must be
   outside this automation checkout, all source repositories, worker scratch,
   controller state and protected STOP locations. Do not put arbitrary files in it.
2. Copy `config/orchestration.example.json` to an operator-owned config. Set
   `discovery` to `/operator/daily/discovery.sqlite` (or your dedicated output
   equivalent). Point `policy`, `promotion`, and `execution` at the existing
   authoritative ledgers; never initialize replacements for missing history.
   The observer `ledger` is a distinct path outside daily output and is not
   read or written by daily planning. Bind planning metadata to exact reviewed
   catalog entries as described in [Sprint 6.5](SPRINT-6.5.md).
3. Copy `config/daily-planning.example.json` to `/operator/observation/daily.json`.
   Replace every example path. Set `orchestration` to the protected observer config.
   Set `output` and its immediate child `discovery_store`. The discovery store
   is exclusively dedicated to this controller; do not have another collector
   write it. Include **every** discovery/controller STOP path in `stop_files`,
   including the exact policy state's `STOP`. This union is checked before reads.
   STOP parents are provisioned/protected by the operator; scheduler never writes
   or clears STOP. Keep `enabled: false` for manual mode.
4. Initialize once, explicitly. This creates only `daily-planning-v1` and a NEW
   `discovery-store-v1` in daily output. It refuses existing stores and performs
   no migration. Do not copy/reset an old store to bypass missing history. If
   adopting prior discovery evidence, preserve it as a separate historical
   source; this controller deliberately requires a separately provisioned store.
5. Execute a manual cycle and inspect its result:

```sh
umask 077
python3 -m src.daily_planning init --config /operator/observation/daily.json
python3 -m src.daily_planning run --config /operator/observation/daily.json
python3 -m src.daily_planning inspect --config /operator/observation/daily.json
python3 -m src.daily_planning history --config /operator/observation/daily.json --limit 25
python3 -m src.daily_planning report --config /operator/observation/daily.json
python3 -m src.daily_planning report --config /operator/observation/daily.json --cycle CYCLE_ID
```

Manual `run` works with scheduling disabled and before the local scheduled start.
It still consumes the same date/configuration identity as a scheduled run. Only
`run --scheduled` consults `enabled` and local start. No command installs a timer.
The old Actions planner is now manual-dispatch-only; its former cron trigger was
removed. Its legacy budget/state branch adapter is not used by this controller.

Config keys are exact and versioned. `retry_limit` and `backoff_seconds` must be
integer zero: automatic retries are intentionally unsupported. Existing GET
transport enforces 15-second request timeout, 1 MiB response bound, no redirects,
no credentials, bounded pages/issues/requests and rate-limit stop. Local config
also bounds duration (1–3600 s), report bytes (1 KiB–16 MiB), successful report
retention (1–366), claim count (1–100,000), and storage (1 MiB–1 GiB). Example
limits are conservative; tune only through operator review. Changing either
config's contents changes the daily digest; config path changes also change it.

## Identity, time, claims and restart behavior

Cycle ID is SHA-256 of protocol, configured local date and digest of the full
validated daily plus orchestration configurations. Default timezone is
`America/Los_Angeles`. No UTC-date scheduling approximation is used. Report order
is stable: existing reviewed task ranking and canonical JSON; no random IDs or
model analysis. Start/end observation timestamps naturally differ across cycles.

A persistent `flock` inode serializes all dates and config revisions sharing one
output root. SQLite `BEGIN IMMEDIATE` plus unique cycle ID durably claims the
cycle before discovery. The lock file is never unlinked. Duplicate launches
return the existing state and do not fetch, reconcile, rewrite reports or replay
failed work. Different config digests on the same date identify distinct reviewed
cycles, still serialized. This is a single configured local scheduler boundary;
separate roots or separate hosts are not a distributed lock. Never run another
writer against its discovery store.

The scheduler evaluates the current local date only; there is no catch-up loop
or backfill for missed dates. History exposes the gaps. Launchd can coalesce missed
wakeups; the actual launch date governs. On a spring DST gap, a nonexistent start
(e.g. 02:30) becomes eligible on the first launch after the gap (03:00 or later).
On a fall fold, both occurrences share one identity; the second is suppressed.
The operator must ensure the host's calendar timezone matches the configured
zone for launchd. Configured-zone validation still rejects an early wakeup; it
does not reschedule it. A local date or epoch older than the last claim is rejected.
Within a cycle, backwards wall time or a forward jump beyond monotonic elapsed
plus 60 seconds fails closed. A duplicate identity never launches work even after
a clock change. No expiry-based lock stealing or silent restart occurs.

SIGTERM/SIGINT, cancellation, periodic STOP checks and a 100 ms interval supervisor
interrupt ordinary blocked Python/transport/reconciliation work and record a
failed report. A monotonic deadline applies across adapters and final report writes. Up to five
seconds (at most one fifth of the duration) is reserved for failure reporting;
if finalization also exceeds the bound, the claim stays incomplete. This is not a hard
kernel storage-I/O or hostile C-extension deadline: an uninterruptible syscall,
SIGKILL, power loss or full disk can leave an incomplete claim. Such a claim
blocks **all future new cycles** in that root. Never interpret it as success.

## Evidence, reports and failure recovery

Discovery commits snapshots/proposals/checkpoints transactionally through the
existing collector. Partial GitHub scans, pagination exhaustion, changed issue
snapshots, timeouts, access/rate limits, cancellation and STOP roll back the entire
scan. Existing discovery evidence stays immutable. A committed discovery scan
can coexist with a failed reconciliation/report; it is never coding or QA proof.
There is no retry within a cycle and no replay of its failed identity.

Every cycle freshly reconciles the real catalog, discovery, promotion, execution,
QA and publication evidence. A missing, corrupt, concurrently changed or unsupported
source remains an error and blocks recommendations. No old success snapshot is
substituted. `task-orchestration-v1` protocols and source hashes are preserved.
Read-only validation was extracted into `observation_validation.py` and
`source_observation.py`: the observer no longer imports promotion or runner action
modules. The catalog validator uses only fixed local Git reads with no network,
hooks, credentials or candidate execution. Original promotion helper APIs remain
available as imports; no existing authorization flow or protocol was changed.

`CYCLE_ID.json` contains ranked task summaries, sequential advisory order,
new/revised proposal IDs, pending promotion/coding/publication reviews, failed QA
and blocked executions, local draft PR records awaiting human merge, source
errors, STOP/infrastructure, usage and unsupported cost estimates. QA success
comes only from reconciled independent controller evidence. Local recorded draft
PRs do not prove current remote state: this cycle does not ship a PR GET adapter.
Human merge is always separate. Source evidence refs and a full-view digest bind
observations without copying prompts, patch contents or subprocess logs. JSON and
text escape untrusted text/control characters. Reports contain no executable
instructions derived from issue prose. Text reports give concise actionable rows;
JSON retains evidence hashes and resource details.

Each report is written via a private temporary file, fsync and atomic rename,
followed by directory fsync. A durable ledger receipt binds both files' SHA-256.
The pair is not a filesystem transaction: only a finalized receipt is success.
`report` verifies both hashes and cycle identity/state. Partial output, altered
bytes, missing text or failed receipt commit never becomes success. All reports
are historical snapshots; `report` does not refresh sources. CLI exits nonzero
for failed/incomplete/interrupted runs, including duplicate failed launches.
Exception text is excluded to prevent provider/credential leakage; report `stage`,
exception type and source errors identify the area for operator investigation.

| Condition | Explicit operator action |
| --- | --- |
| Failed scan or reconciliation | Inspect the report, STOP and named source evidence; fix the cause. The next date is a new cycle; if urgent, independently review a new configuration revision. Never edit claims or grant state. |
| Incomplete/stale process claim | Establish that the old process and descendants have stopped, inspect discovery checkpoints and any partial files, preserve copies and record `recover` with a reason. Recovery never runs discovery or rewrites the report. |
| Disk full or interrupted report write | Restore capacity without deleting authoritative records, preserve partial files, inspect the incomplete claim, then record recovery. Report without a receipt remains unusable. |
| Retention deletion failure | Current cycle fails; tombstone precedes deletion, so old files may remain but are not advertised as valid retained reports. Inspect/remove only those derived retired files after preserving evidence. |
| Unknown/corrupt cycle ledger | Preserve it; restore from a trusted backup after review. Never auto-initialize over it. |
| Claim/history/storage capacity | Preserve and archive the complete root with hashes/backups, then separately review/provision a new root and config. Do not delete evidence to manufacture approvals or replenish coding budget. |
| Interrupted initialization | Preserve partially initialized output; inspect manually before provisioning a new root. `init` does not reset or resume unknown state. |

```sh
python3 -m src.daily_planning recover --config /operator/observation/daily.json \
  --cycle CYCLE_ID --reason 'Operator verified old process exited; inspected partial evidence and preserved backup'
```

`recover` requires the exclusive lock, an existing incomplete claim and a nonempty
reason. It appends `interrupted`; that identity can never run again. It does not
remove STOP, grant approval, release a coding claim or retry an uncertain write.
History and recovery are bounded local operations. `history --limit` is 1–100;
no automatic history pruning is implemented. Retired report receipts remain in
append-only history; successful report pairs are retained up to the configured
count. Failed reports are never automatically deleted; they consume capacity and
can intentionally stop future cycles. SQLite page allocation caps reserve room
for discovery rollback journal and report output; row/document limits remain in
force. Whole-root checks include partial/orphan files. Storage/retention errors
fail closed, rather than allowing unbounded retries or silent deletion.

## Isolation and optional macOS scheduling

Preferred deployment: a dedicated unprivileged identity with OS-enforced read-only
mounts/ACLs to reviewed config, local Git objects, source ledgers and STOP parents,
and write permission **only** to daily output. Egress should allow anonymous
`api.github.com:443` GET discovery only. It must lack publisher/model/worker
credentials, controller-state write permission, reviewed-policy write permission,
and STOP write permission. The current shared validators require private files
owned by the invoking UID. This prevents claiming that a separate UID can read
controller-owned evidence without a separately reviewed export/mount/ownership
arrangement; do not weaken those checks with group-write permissions. A future
read-only evidence export can solve that boundary, but is not supplied here.

For macOS single-user operation, mode 0600/0700 is **not strong isolation against
the same UID**. That UID can normally read its other credentials and rewrite
policy/STOP. This implementation deliberately does not certify unattended
single-user scheduling as isolated. Safe supported fallback: leave scheduling
disabled, use a clean credential-free manual environment, and have the operator
run/review one cycle. Hashes/triggers protect against accidents, not same-user or
root tampering. SQLite may require filesystem access for shared-memory handling
when source ledgers use WAL: provide a reviewed readable snapshot or OS-enforced
read-only mount if necessary; do not grant source writer authority just to make
observation work. Independent multi-source reads are not an atomic snapshot.

`ops/com.fort-custer.daily-planning.plist.example` is an inert, disabled template.
No installer exists and tests never invoke launchctl. Only after independently
resolving the identity limitations above, an operator may manually:

1. Review and replace Python, checkout and config absolute paths; use protected
   code, not a mutable worker directory. Set matching hour/minute in config and
   `StartCalendarInterval`; confirm macOS timezone matches the configured zone.
2. Set `enabled: true` in the protected config and review its new digest. Remove
   the template's `Disabled` key (or set false) in the installed copy. These are
   two distinct deliberate activation steps; changing source alone does neither.
3. Copy the reviewed plist to `~/Library/LaunchAgents/com.fort-custer.daily-planning.plist`,
   mode 0600, then run `plutil -lint` on it. Avoid unbounded stdout/stderr log files;
   authoritative output is the bounded report directory.
4. Explicitly run `launchctl enable gui/$(id -u)/com.fort-custer.daily-planning`
   and `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fort-custer.daily-planning.plist`.
   Do not use KeepAlive or retry loops. Bootstrap does not run the job immediately
   (`RunAtLoad` is false). Do not `kickstart` a live cycle merely to test installation.
5. Inspect the next expected cycle and history. Host sleep, wrong timezone and
   stopped host can miss a date; there is no backfill authorization.

Removal: set protected config `enabled: false`, run
`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.fort-custer.daily-planning.plist`,
then `launchctl disable gui/$(id -u)/com.fort-custer.daily-planning`, and remove the
installed plist. Keep evidence/config/backups. If bootout interrupts a cycle,
inspect/recover it explicitly. Do not delete the lock or database. These commands
are documentation only; merge, import, initialization and testing never execute
them. Deployment of code is distinct from scheduler activation.

## Cost and remaining boundaries

Reports aggregate available controller token usage and expose per-task reviewed
limits. Missing estimates are `unknown`; CPU/RAM quotas and a hard subscription
$10/day billing cap are unsupported. This cycle itself launches no inference.
Legacy advisory reservations are not authoritative subscription billing and are
not imported or reset. A future independent cost policy must deny dispatch before
any model/provider action, reserve worst-case cost atomically, consume trustworthy
provider metering, cancel at enforced limits and fail closed on unavailable data.
Adding that policy to a report or reading subscription usage cannot enforce it.

No scheduler identity, timer, remote service, real Codex task, application PR,
merge or deployment was activated in this sprint. Delivery of this implementation
as a draft automation-repository PR is separate from application publication.
