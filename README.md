# Fort Custer Automation — Sprint 5.1

Current safety boundary: Sprint 6.8 blocks all local live coding dispatch pending
shared grant migration and verified external isolation. Earlier experiment
instructions below are historical; see the
[current runbook](docs/LIVE-CANARY-RUNBOOK.md) before operational use.

Read-only GitHub Issues ingestion and persistent advisory planning for
`MZKZxyz/fort-custer-client` and `MZKZxyz/fort-custer-server`.
Python 3.11+; standard library only. Execution remains disabled. The planner never
modifies issues, invokes Codex, merges, deploys, or connects to MongoDB.

## Local simulation

```bash
python -m unittest discover -s tests -v
python src/orchestrator.py --initialize-state --source sample --db /tmp/fort-custer-simulation.db
# Subsequent runs: omit --initialize-state and retain the same database.
python src/orchestrator.py --source sample --db /tmp/fort-custer-simulation.db
```

JSON and readable Markdown reports default to `examples/latest-report.json` and
`examples/latest-report.md`. Use a separate simulation ledger; never initialize
an operational ledger to bypass an error. The default source remains `sample`.
Missing, corrupt, old-schema, inconsistent or inaccessible state fails closed.
Existing pre-Sprint-5.1 audit-only databases require a separately reviewed migration;
they are not silently reset or treated as proof of unused budget.

## Live issue ingestion (still dry run)

Set `GITHUB_TOKEN` through your credential manager or environment, then run
`python src/orchestrator.py --source github --db /path/to/verified/planning.db`.
First-time local initialization requires explicit `--initialize-state`.

All open issues are paginated independently for both configured repositories.
Pull requests are excluded. Duplicate identities or unverifiable responses abort
the entire plan. Issues without `automation:ready`, malformed metadata, missing or
conflicting risk labels, `automation:approval-required`, `automation:blocked`,
sensitive policy terms, and protected areas appear in **Requires your approval**.
They never receive autonomous reservations. Risk labels are exactly `L0`, `L1`,
`L2`, `L3`; the default remains L3. Existing `config/policy.json` is preserved and
its sensitive terms and protected paths override low-risk labels. L0–L2 plus the
ready label indicate advisory eligibility, not approval to execute or release.

Issue bodies must be a JSON object with exactly these fields:

```json
{"area":"ui/calendar","priority":90,"estimated_usd":2.5,"depends_on":[]}
```

Priority is an integer 0–100. Estimates must be finite and positive, no larger
than the configured per-task maximum. Dependencies are canonical IDs such as
`MZKZxyz/fort-custer-client#123`. Each in-scope dependency is fetched directly;
only a verified closed issue satisfies it. Open, cyclic, self-referential or
out-of-scope dependencies remain blocked. A dependency API failure aborts planning.

Areas are global exclusive scopes. Equal areas and parent/child areas conflict,
even across repositories. Maintainers must declare a common area for shared API
contracts or other overlapping work; this planner cannot infer code overlap from
issue prose. Labels and metadata must be maintained by trusted repository editors.
Issue content is data and never executed.

## Budget and persistent state

Selection is deterministic by priority then canonical issue ID, bounded by three
active reservations and the configured $10 daily budget. Every candidate reserves
the **configured maximum ($3)**, rounded UP to cents, rather than trusting a small
issue estimate. Daily capacity is rounded down. Reservations are advisory, not
measured spend; no provider charges occur in this phase.

SQLite `BEGIN IMMEDIATE` atomically persists `daily_plans`, `tasks` (reserved,
review or blocked), and integer-cent `reservations`. Identical daily inputs reuse
the immutable saved plan. Changed inputs on the same local day fail closed.
Historical plans and audit entries remain available. **Outstanding reservations
remain held across days**, including area and concurrency slots. There is no
automatic expiry, completion, release or budget refund in this phase; these need
a future trusted reconciliation mechanism. Therefore three reserved tasks can
intentionally stop further selections. Never delete state to replenish capacity.
Calendar days use the existing `America/Los_Angeles` configuration.

## GitHub Actions configuration and permissions

`.github/workflows/daily-planner.yml` supports manual dispatch only. Sprint 6.6
removes its legacy cron trigger; deploying source does not activate scheduling. It uses real GitHub Issues and stays
in `dry_run` mode. Setup after reviewing/merging this PR:

1. Add repository Actions secret **`BACKLOG_READ_TOKEN`**: a fine-grained PAT or
   maintained GitHub App installation token with **Issues: read** and metadata
   access to **both** client and server. The automation repository's default
   `GITHUB_TOKEN` cannot normally read other private repositories. App tokens expire;
   provide a refreshed token for each run or use a maintained secret. No Issues
   write, PR write, MongoDB, production or execution credentials are needed.
2. Permit this job's **Contents: write** on the automation repository for durable
   state. All other jobs use Contents: read. The state helper writes only
   `planning.db` on **`automation-planning-state`**. Checkout persists no credentials.
   Repository rules must allow this state branch write. This is a separate state
   adapter; the backlog adapter uses GET only and disables redirects.
3. On the **first run only**, manually dispatch the daily workflow with
   `initialize_state=true`. This explicitly bootstraps a new state branch/ledger.
   All scheduled runs and subsequent dispatches use false. Do not use initialization
   to recover deleted or lost state; restore the authoritative ledger from history
   after human inspection. Existing remote state cannot be reinitialized.
4. Review the **daily-development-plan-RUN_ID** artifact (JSON and Markdown) and
   job summary. Artifacts are uploaded only after state persistence succeeds.

The workflow concurrency group serializes runs across refs. Each state write also
uses the previously fetched GitHub Contents SHA; stale writers fail without retry
or overwrite. API, credential, rate-limit, missing-state and persistence failures
publish no successful plan. State lives in Git history, not an expiring Actions
cache or artifact. Use trusted branch protections and retain state history. A
failed state save leaves the authoritative remote state unchanged; rerun from a
fresh restore. A failed artifact upload after persistence can be retried using
the same immutable daily inputs.

The added `planning.github.eligible_label` setting defaults to `automation:ready`.
All existing safety settings and policy configuration remain in force. Execution,
auto-merge, production deploy, missing-metering bypass, more than three candidates,
and budgets above $10 are rejected even under optimized Python.

`.github/workflows/verify-planner.yml` runs tests and an isolated offline simulation
on PRs and manual dispatch, uploading a **dry-run-plan** artifact. It needs no
secrets or state writes and does not consume the operational planning budget.

## Validation and limits

Tests cover pagination, API 401/403/404/429/5xx failures and credential redaction,
missing credentials, duplicates, risk/approval routing, dependencies and cycles,
area conflicts, decimal reservations, missing/corrupt/inconsistent state,
concurrent identical and competing schedules, cross-day reservations and remote
compare-and-swap failures. Run `python -O -m unittest discover -s tests` to check
that validation is active under optimization.

This phase produces plans only. Trusted execution, metering, independent QA,
reservation reconciliation, and protected human release gates remain future work.
See [ROLLOUT.md](ROLLOUT.md) for the original phased rollout; this document supersedes
its scaffold-only descriptions for ingestion and planning.


## Sprint 5.2: offline execution simulation

Run `python -m unittest discover -s tests -v` and `python src/simulate.py`.
See [architecture, security, migration and one-agent canary requirements](docs/SPRINT-5.2.md)
and the [synthetic execution report](examples/sprint-5.2-report.md).
Live Codex invocation deliberately refuses execution. All release restrictions remain
in force. The simulation is not a production sandbox or billed-spend guarantee.
Advisory replanning freezes once execution tasks exist in the same ledger; use the
execution controller to preserve accounting authority until unified live planning
is separately reviewed. CI simulations use temporary state and never touch the
operational state branch.


## Sprint 5.3: trusted control plane, offline canary rehearsal

Run `python src/rehearsal.py` for the complete credential-free rehearsal, and
`python -m unittest discover -s tests -v` for all three sprint suites. The new
[architecture, threat model, operator procedures and activation blockers](docs/SPRINT-5.3.md)
describe signed single-use human grants, unified ledger ownership, independent QA,
container/process supervision and draft publication recovery.

**Live Codex and live draft publication are code-blocked.** Official Codex token
usage does not establish authoritative billing or a hard $10 spending ceiling.
Sandbox/model transport, approval issuer deployment, server QA infrastructure and
legacy execution mapping also need separately reviewed evidence before activation.
No operational planning-state branch change is included. The existing daily
workflow remains advisory; it is not migrated to live control by this PR.


## Sprint 5.4: offline container deployment package

Run `make lint test rehearsal` on a Linux Docker/gVisor host. The rehearsal builds
three pinned-base images, verifies effective sandbox configuration and negative
probes, runs a synthetic coding task and independent container QA, and simulates
one authorized draft PR while retaining the existing ledger gates.

The [operator runbook](docs/SPRINT-5.4-RUNBOOK.md) includes App permissions/setup,
QA asset preparation, recovery, hosting guidance and the server #3 canary checklist.
[Provider capability evidence](docs/BUDGET-EVIDENCE.md) explains why billing remains
a blocker. Live execution/publication are still unconditionally disabled.

## Sprint 5.5: operational readiness package

Execution/billing profiles in `config/execution-modes.json` distinguish the intended
initial `chatgpt_subscription` from `api_billing`. Audit either with
`python3 src/readiness.py check --mode MODE`; both remain disabled and fail readiness.
Subscription mode prohibits credit purchases, paid refills, token proxying and API
fallback. Official client/headless support and the unresolved credential-isolation
boundary are documented in [SUBSCRIPTION-EVIDENCE.md](docs/SUBSCRIPTION-EVIDENCE.md).

`python3 src/readiness.py check` emits mandatory readiness gates and intentionally
exits 1. The [activation audit](docs/SPRINT-5.5-AUDIT.md) identifies remaining software,
deployment, identity, financial and independent verification requirements. Follow
the [sequential operator runbook](docs/SPRINT-5.5-RUNBOOK.md) after review.

Run `python3 src/activation_rehearsal.py --evidence-dir /tmp/fc55-UNIQUE` to preserve
the synthetic control-plane rehearsal's ledger, broker audit and candidate mirror.
The VM interface is a contract integration, not a deployed microVM provider;
the broker is synthetic-only. The frozen server #3 spec pins an exact commit/tree.
Actual server subset results and full-suite blockers are recorded separately in
`examples/sprint-5.5-validation.json`. No configuration enables live execution.

## Sprint 5.6: offline subscription bridge preflight

Live execution remains disabled. The [authentication investigation](docs/SPRINT-5.6-AUTH.md)
documents the pinned app-server schema, unresolved official registration/eligibility
and credential/tool-isolation blockers. The deterministic fake OAuth/app-server
harness tests bounded approvals, lifecycle failures and durable restart holds
without network or inference. It is not a production OAuth bridge.

See [operator and full server QA preparation](docs/SPRINT-5.6-OPERATOR.md) and the
[separate server issue #3 canary checklist](docs/FIRST-LIVE-CANARY-3.md).
Run `python -m unittest discover -s tests -v`; readiness intentionally remains
nonzero. Full real server QA is still blocked by missing independently verified
MongoDB/native/npm assets and an isolated QA runtime. Neither offline tests nor
configuration flags authorize live usage.

## Sprint 5.8: manual local development runner

The separate, disabled-by-default `local_codex_development` workflow prepares,
inspects, terminal-approves and executes one trusted local task at a time. See
[operator procedure and security limits](docs/SPRINT-5.8.md). It uses an existing
operator-managed official CLI login, disposable workspaces and controller-owned
QA. Production profiles/readiness and daily scheduling are unchanged. No first
real task, remote write or PR publication is authorized by this sprint's tests.

## Sprint 5.9: guarded draft publication

The local runner has separate terminal publication approval and durable artifact
reconstruction. A dedicated publisher reconciles a new feature branch and exact
draft PR using explicitly selected narrow GitHub credentials. See the
[publication runbook](docs/SPRINT-5.9.md) for permissions, commands, crash recovery,
operator-state integrity limits and the pinned first experiment. Offline tests
do not authorize live server publication, model execution, merges or deployment.

### Reviewed local task catalog (Sprint 6.1)

The manual local runner supports `task-list` and `task-prepare TASK_ID` from an
operator-owned, versioned catalog embedded in the local policy. Exact repository,
source manifest, reviewed issue snapshot, editable paths, coding instructions,
independent Node checks and zero-API-spend subscription limits are bound to the
existing controlling-terminal coding approval. Catalog draft publication requires
the separate Sprint 6.2 workflow below; the Sprint 5.9 publisher remains
restricted to its original Issue #3 candidate.
Production execution remains disabled. See [schema, workflow and trust limits](docs/SPRINT-6.1.md)
and [offline evidence](docs/SPRINT-6.1-EVIDENCE.md).

### Human-authorized catalog draft publication (Sprint 6.2)

Validated catalog tasks can now use `python3 -m src.catalog_publication` to
reconstruct durable artifacts, prepare an immutable request, perform read-only
GitHub preflight, and request a separate controlling-terminal publication
approval. A restricted publisher can create a new branch and draft PR; collisions,
expiry and ambiguous PR responses fail closed. The legacy Sprint 5.9 publisher
and historical Issue #3 evidence remain separate. See the
[operator workflow and security limits](docs/SPRINT-6.2.md) and
[offline test evidence](docs/SPRINT-6.2-EVIDENCE.md). No production execution,
automatic approval, merge or deployment is enabled.

### Read-only issue discovery (Sprint 6.3)

`python3 -m src.issue_discovery` manually collects bounded public issue evidence
from the two configured Fort Custer repositories and produces deterministic,
ranked **untrusted proposals** in a separate SQLite database. Anonymous GET-only
collection, offline analysis, immutable revisions and explicit retention limits
keep recommendations separate from reviewed tasks. No promotion, coding approval,
execution, publication or scheduling path is added. See the
[configuration and operator workflow](docs/SPRINT-6.3.md) and
[offline test evidence](docs/SPRINT-6.3-EVIDENCE.md).

### Controlled catalog promotion (Sprint 6.4)

`python3 -m src.catalog_promotion` stages an existing discovery proposal with a
complete independently supplied task entry. A distinct, expiring terminal
approval permits a single manual export. A separate operator import requires a
second terminal review and installs through a locked, conflict-checked atomic
replacement. High-risk work is escalated; no coding or publication approval is
granted. See the [operator workflow and security limits](docs/SPRINT-6.4.md) and
[offline validation evidence](docs/SPRINT-6.4-EVIDENCE.md).

### Read-only task orchestration (Sprint 6.5)

`python3 -m src.orchestrator` now accepts explicit `init`, `sync`, `queue`,
`inspect`, `status`, `report`, and `preview` subcommands with `--config` pointing
to a protected copy of `config/orchestration.example.json`. A separate versioned
ledger retains evidence references and reproducible operator review queues.
Planning is advisory, keeps the active worker ceiling at one, and grants no
coding or publication approval. See the [operator guide](docs/SPRINT-6.5.md) and
[offline test evidence and limitations](docs/SPRINT-6.5-EVIDENCE.md).

### Controlled daily discovery and planning (Sprint 6.6)

`python3 -m src.daily_planning` provides explicit `init`, manual `run`, `inspect`,
`history`, `report`, and operator `recover` commands. It combines bounded anonymous
issue discovery with fresh read-only evidence reconciliation and atomic JSON/text
advisory reports. Durable daily claims suppress duplicates and preserve interrupted
cycles; no approval, coding worker, application publication, merge or deploy runs.
Scheduling is disabled in `config/daily-planning.example.json`; the launchd
example is inert and disabled. The legacy Actions cron trigger is removed (manual
dispatch remains). See the [operator setup, isolation limits and recovery guide](docs/SPRINT-6.6.md)
and [offline evidence](docs/SPRINT-6.6-EVIDENCE.md). Same-UID filesystem permissions
are not credential isolation; safe manual mode remains available.

### Synthetic concurrency readiness (Sprint 6.7)

A separate versioned coordinator provides durable task/slot claims, fencing,
repository collision control, independent synthetic QA and per-task accounting.
Three synthetic workers can be demonstrated offline; the live worker limit stays
one and no live dispatcher is added. Configuration is disabled by default.
Read-only local commands expose slots, queues, claims, results and recovery holds.
See the [operator and isolation guide](docs/SPRINT-6.7.md) and
[validation evidence](docs/SPRINT-6.7-EVIDENCE.md).

### Supervised integration boundary (Sprint 6.8)

Live local execution is now blocked before claiming an approval or starting a
process. The separate legacy/coordinator ledgers require a shared broker migration
and independently verified worker/QA isolation. There is no configuration override.
Historical records and offline synthetic rehearsals remain usable.
`python3 -m src.integration_control --policy POLICY` provides read-only health
and intentionally exits 1 until the migration is implemented.
See [integration and recovery](docs/SPRINT-6.8.md),
[validation evidence](docs/SPRINT-6.8-EVIDENCE.md), and the
[supervised canary preparation runbook](docs/LIVE-CANARY-RUNBOOK.md).
No real canary, scheduling, live concurrency, merge or deployment is activated.


## Sprint 6.9: grant broker and local peer transport (synthetic only)

The [versioned broker](docs/SPRINT-6.9.md) owns one atomic synthetic claim ledger,
with process races, fencing, durable startup/QA intents and explicit termination
recovery. The one-shot Unix transport authenticates kernel peer credentials,
bounds wire bytes/deadlines and rejects descriptor transfers. Trusted QA
reconstructs exact-source candidates; publication still requires separate human
review. Historical ledgers are preserved and are not atomically migrated.

**Live dispatch remains unconditionally disabled by Sprint 6.8.** No flag can
activate the broker. The subprocess demo uses the same UID and proves no external
sandbox. Read [worker isolation](docs/WORKER-ISOLATION.md),
[validation evidence](docs/SPRINT-6.9-EVIDENCE.md), the
[canary runbook](docs/LIVE-CANARY-RUNBOOK.md) and the disabled
[example](config/grant-broker.example.json) before considering a separate activation.

```sh
python3 -m unittest discover -s tests -p test_grant_broker.py -v
PYTHONPATH=.:tests python3 tests/test_grant_broker.py --demo
python3 -m src.integration_control --policy POLICY --broker-config BROKER_CONFIG
```

The readiness command always exits 1 and reports unverified external isolation,
blocked legacy migration, zero live capacity and unsupported hard resource limits.
No real Codex worker, application publication, merge or deployment is performed.

## Sprint 6.10: single-worker activation preparation

[Sprint 6.10](docs/SPRINT-6.10.md) adds complete source/candidate handoff bundles,
an external QA client with distinct peer identities, durable synthetic subscription
exhaustion/unknown holds, a read-only historical inventory and eight separate
readiness prerequisites. The [Mac runbook](docs/LIVE-CANARY-RUNBOOK.md) identifies
mandatory verification and exact stop points. The fresh canary
[review template](examples/direction-vectors-task.review.json) is not an approval.

**Software integration is incomplete; live activation remains blocked.**
Safe personal-account authentication, authoritative live migration, external
QA/VM receivers and publisher intake are still missing. There is no enable flag
or receipt override. No account files are forwarded, no privileged infrastructure
is installed, and no live Codex task or application publication is performed.
See [test evidence and outstanding blockers](docs/SPRINT-6.10-EVIDENCE.md) and
[credential/isolation requirements](docs/WORKER-ISOLATION.md).

```sh
python3 -m unittest discover -s tests -p test_activation_readiness.py -v
python3 -m src.migration_inventory --policy POLICY --coordinator COORDINATOR_CONFIG --broker-config BROKER_CONFIG
python3 -m src.integration_control --policy POLICY --broker-config BROKER_CONFIG
```

Both inspection commands intentionally exit 1; inventory cannot authorize
activation or convert historical approvals. The
[installation plan example](config/single-worker-activation.example.json)
is disabled and is not runtime activation configuration.
