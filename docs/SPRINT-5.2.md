# Sprint 5.2: simulation control plane

Run `python -m unittest discover -s tests -v` and `python src/simulate.py`.
The checked-in [execution report](../examples/sprint-5.2-report.md) uses only temporary
SQLite files and synthetic costs. The real planning database is never opened by
simulation. Python 3.11+ and Git are sufficient; no API keys or dependencies.

## Architecture and authority

The planner retains immutable daily plans. `execution.Controller` adds five
namespaced tables without modifying planner or audit rows. SQLite `BEGIN IMMEDIATE`
serializes admission, reservations, approval, leases, receipts, QA decisions and mock
PR creation across processes. Run against a durable local volume, not ephemeral
Actions storage or a network filesystem. A task has up to three uniquely identified
attempts (initial plus two retries); every attempt reserves fresh integer cents.
Idempotency keys bind task and reservation and cannot dispatch a second worker.
A single owner claims a dispatched attempt; lease expiry fences further heartbeats
and candidate promotion. Global shared area names serialize cross-repository work.
Up to three reservations through PR-ready occupy slots. Reconciliation also retains
slots; it never implies termination. Dispatch has a 60-second pickup lease and a
40-minute absolute deadline. Heartbeats cannot extend the deadline.

Lifecycle: planned → reserved → awaiting_approval → dispatched → running → qa →
pr_ready → completed. Reserved is recorded in the same atomic transaction as
awaiting_approval. Completed means a simulated draft was recorded, never merged.
Failures may retry only after termination and settlement; cancellation and uncertain
termination retain reservations. Expiry moves to reconciliation_required. Kill
switch is persisted and cannot be cleared by a worker; there is no automatic reset.
All active workers must be terminated by the eventual trusted supervisor; the mock
only fences state because it launches no agent process.

Controller APIs, operator names, QA evidence and metering receipts are trusted
in-process interfaces, **not authentication mechanisms**. Synthetic identities model
separation; these modules are not an Internet service or a hardened runtime. Future
coding workers must have no SQLite access. QA must run under a different OS/service
identity and scoped credential. Only the controller may write state. Future remote
messages require authenticated, signed provenance, execution binding and replay
protection; strings such as `human:name` are never sufficient authorization in live mode.

## Worker and QA boundaries

`CodexCLI.command()` records the official `codex exec --json` CLI contract. `run()`
always refuses; flipping configuration cannot activate it. The mock starts no model
or shell from issue content. Its optional fixture checkout copies a local Git repo
without shared objects, disables hooks/global configuration, strips inherited secrets,
uses a disposable branch and removes origin. Caller owns cleanup of the returned
temporary directory. This helper is only for trusted synthetic repositories; it is
not a sandbox for malicious code. Issue text stays inert data and cannot select
commands, repositories, branches, budget, allowlists or policy.

The QA gate binds unit/build and applicable API/browser evidence to an exact SHA
and complete-diff digest. Review must bind the sorted changed-file manifest and all
five risk categories (security, data, API, gameplay, release). Sensitive changes fail
for human security review; workflow/policy/environment/traversal paths fail even if
in a changed-file allowlist. Missing, failing or stale evidence blocks promotion.
Applicable checks and allowlists must be supplied by trusted policy, never issue
content. Current simulation supplies fixtures; it does not independently execute
application builds or prove real code correctness. Future QA infrastructure must
fetch the immutable base/candidate commits, compute the complete diff including
renames, symlinks, binaries and submodules, run trusted checks against that SHA in
an isolated checkout, and independently review every hunk. Candidate-owned scripts
and workflows cannot grant approval or change trusted review policy.

`MockGitHub` atomically records a draft only after QA and explicit synthetic operator
approval. It is idempotent across restarts and has no GitHub network client. Future
live PR publication needs a transactional outbox with remote deduplication and
reconciliation after uncertain network outcomes. A separate narrowly scoped GitHub
App may push only an approved task branch and open a draft at the reviewed SHA;
no merge, auto-merge, production configuration or deployment permission.

## Budget and billing limits

A day is America/Los_Angeles local time. Admission sums settled synthetic cents plus
all unresolved reservations for that day, including failed and cancelled attempts.
Each reservation is at most 300 cents and daily total at most 1000. Sprint 5.1 reservations remain held across days and occupy global slots/areas.
`import_reserved(task_id)` copies the verified planner identity; first reservation
atomically links that exact legacy reservation to one execution attempt without
double charging it. Original task, plan and reservation rows are never rewritten.
Subsequent retries reserve fresh funds. Unmapped or inconsistent schemas fail closed.
Audit-only plans without a reservation table retain a conservative daily hold.
Advisory replanning freezes when execution tasks exist, preventing two accounting
authorities from admitting independent work; unified future planning remains a live
activation requirement. Unresolved accounting blocks admission
globally, including across midnight. Retries never reuse the prior reservation.

Receipts have unique IDs and one immutable settlement per attempt. Missing, negative,
ambiguous, excessive, non-integer or non-mock amounts fail closed. No live metering
adapter exists. Mock receipts are synthetic accounting fixtures, not actual billed
USD. Excess amounts keep the task blocked and need external operator investigation;
they are not silently capped to a reservation. Token counts and estimates are not
billing receipts. The OpenAI Costs API may be delayed or aggregated; unless a future
adapter can unambiguously attribute authoritative billed costs to an execution and
authorized day, dispatch must remain disabled. A local reservation cannot guarantee
an external provider hard cap. Require provider-enforced project limits or a prepaid
broker with hard request admission, bounded in-flight liability, and cancellation.
A budget alert is insufficient. Include independent QA costs in the same authorization
before activating paid QA. No credentials are installed in Actions.

## Migration, rollback and recovery

1. Stop planner/controller writers and take a SQLite online backup using the SQLite
   backup API. Preserve DB, WAL and SHM coherently; do not copy a live DB file alone.
2. Test `execution.migrate(backup_path)` on a backup first. It is additive, transactional
   and repeatable. Existing tables are not rewritten. Do not run against production
   state merely to generate simulation evidence.
3. To revert before admitting tasks, call `migrate(path, down=True)`; only the five
   execution tables are dropped. Downgrade refuses a nonempty task ledger. After
   admission, stop workers, settle liabilities and archive the execution ledger, then
   restore the coherent backup with operator review. Never drop live reservations.
4. On restart instantiate the same Controller and call `recover()`. Do not redispatch
   uncertain attempts. Confirm process-group/container termination with the trusted
   supervisor, obtain authoritative metering, settle, then finish as failed to allow
   a freshly reserved retry. Never accept a late expired candidate.
5. Full stop is `recover(kill=True)`. It persists the stop flag, blocks new dispatch
   and PR publication, fences running workers, and retains uncertain funds. Manual
   recovery requires a reviewed operational procedure; no automatic resume exists.

## Explicit one-agent canary activation plan (separate milestone)

1. Obtain written operator authorization naming repository, base SHA, one issue,
   branch allowlist, paths, QA scope, day, runtime and maximum liability. Keep this
   sprint's `execution.enabled=false`, auto_merge=false, production_deploy=false.
2. Implement and independently audit OS/container isolation: non-root, no host
   sockets/home/state mounts, scrubbed environment, read-only policy, disposable
   checkout, resource limits and process-group kill within 40 minutes. Deny outbound
   network at the kernel/network broker; CLI sandbox settings alone are insufficient.
3. Provision only a dedicated Codex identity and separate QA identity. No Atlas,
   MongoDB production, Railway, Vercel, deployment or controller-writing credentials
   may enter either workspace. Authenticate controller IPC outside worker authority.
4. Prove provider-supported cost attribution and external hard limits with bounded
   in-flight liability, billing failure drills and stop acknowledgements. Authorize
   at most $3 total canary liability within the shared $10 day; account for QA too.
5. Limit the audited future controller to **one** coding agent. Select a synthetic
   tooling task in an explicitly allowed sandbox repo. Operator approves dispatch;
   collect signed logs, heartbeat, termination and billing receipts.
6. Independent QA checks exact SHA and full diff; operator separately approves draft
   creation using a restricted GitHub App. No merges or deployments. Stop, reconcile,
   inspect the report, revoke canary credentials and obtain a new approval before
   increasing concurrency or scope. A boolean flip is never activation authorization.
