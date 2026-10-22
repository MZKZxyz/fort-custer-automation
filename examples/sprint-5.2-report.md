# Sprint 5.2 synthetic execution report

**No Codex calls, billed usage, pushes, deployments or live draft PRs.**

## Scenarios

- Three independent workers running concurrently
- Fourth admission: BLOCKED (Concurrency or cross-repository work-area conflict)
- Duplicate dispatch returned original execution ID
- Process restart restored all three active leases
- Crash retry before accounting: BLOCKED (Unresolved accounting or worker termination)
- Missing metering retained reservation and blocked admission
- Kill switch admission: BLOCKED (Kill switch engaged)

## Final ledger

| Task | State | QA | Draft |
|---|---|---|---|
| 0 | completed | [] | mock draft |
| 1 | failed | ['sensitive change requires human security review'] | none |
| 2 | reconciliation_required | pending | none |
| 3 | planned | pending | none |
| 4 | planned | pending | none |
| 5 | planned | pending | none |
| 6 | planned | pending | none |

## Accounting

Amounts below are synthetic cents, not actual billed dollars.

| Attempt task | Reserved | Synthetic settled | Held |
|---|---|---|---|
| 0 | 200 | 75 | 0 |
| 1 | 200 | 75 | 0 |
| 2 | 200 | 50 | 0 |
| 2 | 200 | None | 200 |

## Human actions required

- Confirm termination and reconcile the interrupted retry; its reservation remains held.
- Review the sensitive QA failure and the simulated draft.
- Separately authorize a future one-agent canary after external billing and sandbox enforcement exist.
- Merge and production deployment remain outside this controller.
