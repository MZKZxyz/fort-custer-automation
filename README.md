# Fort Custer Automation — Sprint 5.1

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

`.github/workflows/daily-planner.yml` runs daily at **16:17 UTC** (9:17 a.m. PDT /
8:17 a.m. PST) and supports manual dispatch. It uses real GitHub Issues and stays
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
