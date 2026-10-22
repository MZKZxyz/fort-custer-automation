# Sprint 5 rollout checklist

## Phase 0 — Review and baseline (human)
- [ ] Merge or close active Sprints 2–4 as appropriate; identify current main SHA in both game repositories.
- [ ] Create an empty **private** `fort-custer-automation` repository (do not put production secrets into it).
- [ ] Review `config/settings.json`, `config/policy.json`, and the threat model in `README.md`.
- [ ] Protect `main`; disallow direct pushes and enforce human-reviewed PRs.
- [ ] Confirm Vercel production tracks client `main`, and Railway production tracks server `main`; these are independent deployments.
- [ ] Confirm production databases/credentials are inaccessible to coding workers.

## Phase 1 — Simulated daily scheduler
- [ ] Run `python -m unittest discover -s tests -v` (all 5 pass).
- [ ] Run `python src/orchestrator.py`; review selected/skipped tasks and projected reservation amounts.
- [ ] Inspect the local SQLite `state/automation.db` and `examples/latest-report.json`.
- [ ] Set up daily GitHub Actions advisory planner and inspect its uploaded artifact.
- [ ] Verify `execution.enabled=false`, `release.auto_merge=false`, `release.production_deploy=false`.
- [ ] Deliberately change auto_merge to true; verify the scheduler refuses to operate.

## Phase 2 — GitHub and persistent control plane (new PR, human approval)
- [ ] Configure a GitHub App with read-only access to issues, commits, and checks initially.
- [ ] Read labeled, eligible issues from both repositories; validate strict issue schema.
- [ ] Treat issue text/PR comments as untrusted input, never instructions with privilege.
- [ ] Implement transactional per-task claims and durable execution state.
- [ ] Add per-area leases across repositories, TTL recovery, and crash-safe reservation accounting.
- [ ] Add webhook/event deduplication and replay tests.
- [ ] Test two simultaneous schedulers: neither may double-dispatch or exceed the budget.

## Phase 3 — Codex executor in staging (new PR, human approval)
- [ ] Add Codex SDK worker that runs in a disposable checkout with no production credentials.
- [ ] Hard-stop execution after a configurable runtime and on operator kill switch.
- [ ] Enforce max 3 workers globally, including workers started before a reboot.
- [ ] Reserve estimated maximum cost before dispatch and reconcile actual usage before scheduling further tasks.
- [ ] Define behavior for missing/incomplete usage data: stop new dispatches.
- [ ] Add a per-day external spending alert/limit if available from the provider.
- [ ] Demonstrate an end-to-end synthetic task that creates a *draft* PR.

## Phase 4 — Independent QA and gating (new PR, human approval)
- [ ] Separate coding and reviewing identities/tokens.
- [ ] Require protected unit, build, browser/API, and security checks.
- [ ] Validate check runs against immutable commit SHA, not PR branch name alone.
- [ ] Compute risk using protected policy files; classify unknown as L3.
- [ ] Demonstrate blocked promotion for failing tests, missing evidence, policy changes, and risky files.
- [ ] Add a review digest with screenshots, changed files, risks, and human-action links.

## Phase 5 — Limited live operation (explicit authorization)
- [ ] Enable daily backlog generation.
- [ ] Enable agent dispatch with an initial one-worker canary.
- [ ] Raise to three workers only after satisfactory results.
- [ ] Keep automatic merge and production deployment disabled.
- [ ] Inspect execution cost, escaped defects, review quality, and stalled tasks weekly.
- [ ] Require a new explicit decision before ever considering auto-merge.

## Recovery drills
- [ ] Kill switch prevents new tasks, cancels active workers, and retains audit evidence.
- [ ] Unexpected billing/metering failure stops dispatch.
- [ ] GitHub API errors never count as completed checks.
- [ ] Stale leases recover without double execution.
- [ ] An agent cannot change protected policy or workflow settings to self-approve.
- [ ] Every proposed release has a rollback or revert plan.
