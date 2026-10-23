# Sprint 6.5 — offline validation evidence

Review date: 2026-10-22 (America/Los_Angeles).
Base: `bdfbcd41dcf7f1e8e45c0a969a2a71cc84d655c5`, merged Sprint 6.4 PR #13.
The connected GitHub API confirmed latest `main` and PR #13's merged status.
The supplied checkout was at Sprint 5.9 `2231a9a`. Shell Git failed to connect to
its configured proxy; no proxy/identity bypass was attempted. Twenty-two changed
files were retrieved through the connected GitHub tool, each verified against
its Git blob SHA. Their assembled upstream tree exactly reproduced
`aef6e537397bbfd39827b4eaf5303f387950231e`. The signed commit reconstructed from
GitHub's verification payload/signature exactly reproduced the base commit SHA.

## Validation

- Baseline: `python3 -m unittest discover -s tests -q` — 305 tests in 85.021 s,
  OK, one existing skip (`age` unavailable).
- New suite: `python3 -m unittest discover -s tests -p test_task_orchestration.py -q`
  — 49 tests in 23.530 s, all passed, no skips.
- Final full regression: `python3 -m unittest discover -s tests -q` — 354 tests in 110.133 s, OK: 353 passed and one existing skip (`age` unavailable).
- `make lint` — pinned image inputs/live gate validation and Python compilation
  passed; no Docker build, activation, or deployment.
- `git diff --check` and `python3 -m src.orchestrator queue --help` — passed.

The full regression includes the new suite and all 305 prior tests. The new
fixtures use temporary local Git sources, synthetic discovery/promotion/controller
SQLite, mocked Codex worker output, real controller-selected QA on synthetic
JavaScript, and in-memory mock GitHub publication/reads. Existing terminal
challenges are mocked only within authorized synthetic fixture setup. The
orchestrator itself never initializes a runner/publisher or invokes their actions.
No real Codex task, model account, paid API, application GitHub write, production
DB, scheduler, merge or deployment was used. The requested draft PR is delivery
to the automation repository, separate from the observer and application publisher.

## Synthetic lifecycle demonstration

A local temporary-fixture demonstration produced:

| Evidence supplied separately by the synthetic subsystem fixture | Observer state |
| --- | --- |
| Reviewed catalog | `awaiting-coding-approval` |
| Promotion preparation | `awaiting-promotion-review` |
| Separate controller approval | `approved-for-coding` |
| Mock coding and successful independent local QA | `awaiting-publication-review` |
| Mock draft publication completion | `published-draft-recorded` |
| Matching mock read-only GitHub observation | `awaiting-human-merge` |

It reported `repeat_sync_same_snapshot: true`,
`observer_execution_performed: false`, and `live_network: false`.
The proposal/promotion/import path is separately exercised through actual
synthetic export/import, including distinct mocked terminal reviews and queue
collapse into the imported catalog task. Reproduce both through:

```sh
PYTHONPATH=tests:. python3 -m unittest \
  test_task_orchestration.OrchestrationTests.test_complete_synthetic_lifecycle \
  test_task_orchestration.OrchestrationTests.test_promotion_review_export_import_deduplicates -v
```

## Acceptance and security checks

| Requirement | New test evidence |
| --- | --- |
| Lifecycle and separate approvals | `test_complete_synthetic_lifecycle`, `test_coding_approval_is_not_publication_authority`, `test_promotion_review_export_import_deduplicates` |
| Independent server/client planning | `test_independent_client_repository_planning`; two advisory recommendations, one active-worker ceiling |
| Missing/unsupported/contradictory evidence | `test_missing_configured_source_blocks_every_task`, `test_unknown_source_protocol`, `test_missing_qa_and_forged_state`, `test_duplicate_execution_claims_fail_closed` |
| Malicious text/forged grants | `test_malicious_issue_text_and_forged_approval`, `test_missing_independent_approval_history`, `test_json_duplicate_keys_rejected`, `test_forged_publication_branch_with_recomputed_binding` |
| Duplicate/replayed evidence | `test_duplicate_promotion_event_blocks`, `test_promotion_replayed_under_another_identity`, `test_replayed_sync_is_restart_safe_and_preserves_sources` |
| Expiration and chronology | `test_expired_coding_authorization`, `test_expired_promotion`, `test_expired_publication_is_not_approved`, `test_clock_regression_and_future_approval`, `test_real_promotion_clock_calls_can_differ` |
| Cancellation/QA failure/interruption | `test_cancelled_execution`, `test_failed_qa`, `test_publication_cancelled`, `test_running_and_interrupted_claim_hold_capacity`, `test_interrupted_publication` |
| Source/provider changes | `test_stale_source_specification`, `test_source_change_during_reconciliation_blocks`, `test_changed_github_branch_and_pr_status`, `test_remote_read_failure_blocks_publication` |
| Dependencies/conflicts/capacity/STOP | `test_dependency_completion_fails_closed`, `test_dependency_cycle_and_missing_dependency`, `test_repository_conflict_priority_and_cost_unknown`, `test_capacity_configuration_rejects_more_than_one_active`, `test_invalid_running_evidence_still_holds_global_capacity`, `test_stop_state_blocks_all_and_does_not_clear` |
| Durable observations and queue | `test_snapshot_can_return_to_previously_observed_state`, `test_queue_determinism_pagination_and_bounds`, `test_optional_github_reads_retained_as_immutable_evidence`, `test_cli_inspection_and_reports_are_historical` |
| Immutable history/read-only source capability | `test_ledger_is_exclusive_and_append_only`, `test_readonly_database_cannot_mutate`, `test_modified_snapshot_or_missing_observation_is_rejected`, `test_initialization_never_replaces_source_ledger`, `test_symlink_source_is_rejected`, `test_corrupted_export_receipt_blocks_promotion` |
| No executor/publisher authority | `test_no_execution_approval_or_publication_capability_used` patches runner/publisher constructors, execution and network opening to fail throughout observer reconciliation/storage/planning/reporting; AST checks prohibit action calls and privileged imports |
| Legacy compatibility | `test_legacy_sprint5_records_remain_unresolved_and_untouched`; all existing regression tests retained |

## Preserved evidence and assumptions

All preexisting subsystem modules, protocols, configuration and tests are
unchanged, except four CLI routing lines in the old dry-run orchestrator and a
README addition. No actual operator discovery/controller/promotion/publication
ledger was available or modified. New fixtures leave historical repository files
unchanged. Verified historical SHA-256 values match Sprint 6.4:

| File | SHA-256 |
| --- | --- |
| `state/automation.db` | `53991a6539c1ada5fbf23c8ff89523c253b801b8e5ca834e003fb88304e62fc6` |
| `docs/SPRINT-5.9.md` | `22fa4544657cfcd6b8353ef84ae0633a72318ed370b9377a599a0cbdf4f9cc6a` |
| `docs/SPRINT-5.9-EVIDENCE.md` | `2c643e8f50c7e5807387cee183f014bd32df98db7af65a12171b55db21c49f1b` |

OS protection of source/derived evidence and operator-controlled metadata remains
required. Same-user/root compromise can forge hashes, code, ledgers or terminal
intent; no signature/attestation service is introduced. SQLite read-only handles
and capability-restricted adapter interfaces demonstrate application boundaries,
not an OS sandbox. The catalog resolver issues fixed local Git reads; it never
runs reviewed QA argv. Publisher credentials remain unavailable to the observer.
The observer checks controller-authored QA bindings but does not independently
replay its patch. The separately authorized publisher must still reconstruct and
verify that candidate. No observer state is an execution/publication grant.

## Known limitations

The [operator guide](SPRINT-6.5.md) describes all state/queue/recovery semantics.
In particular: CLI views are saved historical observations; `preview` refreshes
local reads only. No live GitHub transport is shipped, so normal CLI views cannot
attest current PR status. A trusted optional read-only integration may supply
observations; failures and changed metadata block. Multi-ledger reads and provider
reads are not atomic global snapshots. Ordinary local changes are detected by
before/after file/WAL hashes; adversarial change-and-restore races are outside the
operator-owned file trust model.

Dependencies remain conservatively blocked because current source protocols
cannot prove merged dependency incorporation. Legacy Sprint 5.x executions are
retained unresolved, without reinterpreting approval or success. The separate
older API-budget/secure-dispatch ledgers are not migrated or unified with local
subscription accounting. This is one local controller view, not cross-host
concurrency enforcement. Future capacity is three; current worker authority
remains the unchanged single-worker runner. CPU/RAM quotas and subscription hard
dollar/token caps remain unsupported. History is append-only and needs operator
storage management. No unattended coding, autonomous approval, background service,
notifications, GitHub application write, merge, deployment or production scheduling
is activated.
