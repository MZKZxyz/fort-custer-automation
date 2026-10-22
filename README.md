# Fort Custer autonomous development — Sprint 5 scaffold

This is a **safe, runnable dry-run** of the scheduler. It cannot launch Codex, create GitHub issues or PRs, merge branches, access production data, or deploy. No credentials are required.

## Quick start

Requires Python 3.11+.

```bash
python -m unittest discover -s tests -v
python src/orchestrator.py
```

Reports are written to `examples/latest-report.json`, with a local SQLite audit entry in `state/automation.db`.
The GitHub Actions workflow runs a read-only daily advisory plan at **16:17 UTC** (roughly 9:17 a.m. PDT / 8:17 a.m. PST). The cron is UTC and therefore changes local hour with daylight saving time. Modify the schedule if a fixed local time is required.

## What is implemented

- Configuration validation (dry-run only)
- Maximum three concurrent coding task *candidates*
- Daily $10 reservation ceiling, including existing reservations passed into the scheduler
- Exclusive-area conflict avoidance and dependency awareness
- Deterministic priority ordering
- Local SQLite append-only advisory audit entries
- GitHub Actions daily read-only report artifact
- Tests for budget, conflict, concurrency, and fail-closed settings

## What remains before real autonomy

1. Add a **real, persistent task ledger** with transactional reservations, running-job leases, heartbeat expiry, and deduplication; the current planner is not safe for multiple scheduler instances.
2. Connect GitHub App credentials with minimal issue/PR permissions. Fetch backlog from GitHub Issues, not a sample JSON file. Sanitize untrusted issue text.
3. Implement Codex SDK execution using isolated disposable workspaces. Enforce task cancellation, timeouts, spending reservations, secret redaction, and telemetry-based reconciliation. **Never enable dispatch by merely flipping a configuration boolean**: `validate()` intentionally rejects live mode.
4. Implement an independent QA runner with trusted CI results, reviewer identity separation, and artifact verification.
5. Integrate an external protected merge policy. Leave auto-merge disabled until a separate signed-off milestone; no agent can approve its own PR.
6. Add staging-only end-to-end tests for Fort Custer backend using synthetic data and a dedicated MongoDB instance. Set up separate Railway/Vercel credentials only if a later deployment phase is explicitly approved.
7. Add trusted cost reporting. Current reservation estimates are examples, **not measured spend**. A hard $10 billed-usage guarantee requires provider-supported metering/cancellation or infrastructure-based spending limits; do not claim a hard billing cap without that.

## Approval boundaries

Every merge requires human approval. Production deployments, database writes, credentials, and changes to automation policies or workflows remain prohibited. See `config/policy.json`. The policy JSON is design input; the current script enforces only its explicit dry-run settings. Don't treat it as a working production release gate.

## Suggested GitHub issues for the next milestone

- FC-AUTO-01: GitHub App read-only backlog ingestion
- FC-AUTO-02: atomic ledger and budget leases
- FC-AUTO-03: bounded isolated Codex execution adapter
- FC-AUTO-04: independent QA and protected review gate
- FC-AUTO-05: mission-control report and kill switch
