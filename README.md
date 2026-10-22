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
