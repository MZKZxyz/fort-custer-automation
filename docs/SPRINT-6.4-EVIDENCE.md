# Sprint 6.4 — offline validation evidence

Review date: 2026-10-22 (America/Los_Angeles).
Base: `a25f33cadc6dc0ee9b9915ac1df4424278b13aa0`, merged Sprint 6.3 PR #12.
Connected GitHub reads confirmed this was latest `main` before implementation and
before delivery. The shell Git proxy was unreachable. Eighteen changed files
since the supplied Sprint 5.9 checkout were retrieved through the connected API,
verified against their Git blob IDs, and assembled into upstream tree
`1d0086f3935f778dd9ab2a699cc508f9687f6896`. The signed commit was reconstructed
from its verification payload/signature and reproduced its exact commit SHA.
No network bypass or credential acquisition was used.

## Exact validation results

- Baseline: `python3 -m unittest discover -s tests -q` — 272 tests in 60.951 s,
  OK, one existing skip (`age` unavailable).
- New security suite: `python3 -m unittest discover -s tests -p test_catalog_promotion.py -q`
  — 33 tests in 12.998 s, OK, no skips.
- Full final regression: `python3 -m unittest discover -s tests -q` — 305 tests in
  77.408 s, OK: 304 passed, one existing skip (`age` unavailable).
- `make lint` — pinned image inputs/live gate validation and Python compilation
  passed. No Docker build or activation.
- `git diff --check` — passed.
- `python3 -m src.catalog_promotion --help` — passed; only explicit init,
  attempts, prepare, inspect, approve, apply (export), and manual import operations.

All added tests use synthetic discovery data and temporary local Git sources,
operator policy, discovery SQLite and promotion SQLite. Terminal authorization is
mocked in workflow tests; terminal-specific tests reject wrong challenges and
non-TTY input. No real Codex, model account, paid API, GitHub application write,
production database, scheduler, deployment, merge or live promotion was used.
The requested draft PR writes only to the automation repository and is separate
from the promotion subsystem. Existing synthetic execution/publication regression
fixtures retain their original protocols.

## Acceptance evidence

| Boundary | Offline evidence |
| --- | --- |
| Operator review and distinct proposals | `test_reviewed_export_and_manual_import_preserves_unrelated_and_evidence`, `test_multiple_distinct_proposals`, `test_no_privileged_field_defaults` |
| Malicious text remains data | `test_malicious_text_remains_data`; independent instructions remain unchanged while original evidence is retained |
| Forged IDs, modified snapshots/proposal, missing audit | `test_forged_ids_and_modified_evidence`, `test_altered_proposal_with_valid_identifier_is_rejected`, `test_missing_audit` |
| Closed issue/current state | `test_changed_issue_state_and_offline_later_observation`, `test_network_is_explicit`; injected GET-only transport, no live reads |
| SHA, repository, manifest | `test_source_identity_manifest_and_repository_mismatch`; existing catalog source/object checks retained |
| Paths, QA, instructions, resource limits | `test_unapproved_paths_commands_instructions_resources`, `test_unknown_schema_and_unrelated_invalid_task_fail_closed` |
| Terminal grants, expiry, replay, clock regression | `test_coding_approval_cannot_authorize_promotion`, `test_expired_preparation_approval_and_import`, `test_replay_approval_export_and_import`, `test_clock_regression_rejects_approval_and_export`, `test_terminal_requires_exact_challenge_and_tty` |
| Separate manual import authorization | `test_import_requires_separate_terminal_confirmation`, `test_approval_cannot_be_forged_from_another_ledger` |
| Collision, conflict, tampered export | `test_catalog_write_conflict_and_task_collision`, `test_import_conflict_and_tampered_export` |
| Atomic failures before/after replacement | `test_interrupted_atomic_import_consumes_grant_and_retains_old_catalog`, `test_crash_after_replace_is_uncertain_and_never_replays`, `test_export_failure_consumes_grant_no_overwrite` |
| Concurrency | `test_concurrent_promotions_and_imports`, `test_concurrent_export_cannot_reuse_approval` |
| STOP | `test_stop_at_each_phase`, `test_stop_during_import_terminal`; no STOP file is cleared |
| Risk escalation | `test_high_risk_escalation` covers authentication, database, payment, deployment and explicit operator high risk |
| Filesystem ownership assumptions | `test_private_paths_symlinks_and_hardlinks`; 0600 resulting catalog; private ancestry checks include mapped filesystem-root owner |
| Separate append-only audit | `test_ledger_append_only_unknown_schema`, `test_rejections_are_audited_and_retained`; filesystem intents commit before writes |
| No coding/publication/network launch | `test_no_worker_publisher_or_runner_initialization` forbids Runner construction, LocalCLI execution and HTTP opening through the entire export/import workflow; module has no publisher import or subprocess call |
| Legacy compatibility and history | All 272 existing tests run unchanged; existing modules and historical records remain byte-for-byte identical to upstream |

## Preserved historical evidence

No original runner, catalog, discovery, publisher, test or historical ledger was
changed. Only the new promotion module/tests, new Sprint 6.4 documents and README
are part of this sprint. No actual operator execution or discovery database was
available or modified. Historical Issue #3 retains its protocol and interpretation.

| File | SHA-256 |
| --- | --- |
| `state/automation.db` | `53991a6539c1ada5fbf23c8ff89523c253b801b8e5ca834e003fb88304e62fc6` |
| `docs/SPRINT-5.9.md` | `22fa4544657cfcd6b8353ef84ae0633a72318ed370b9377a599a0cbdf4f9cc6a` |
| `docs/SPRINT-5.9-EVIDENCE.md` | `2c643e8f50c7e5807387cee183f014bd32df98db7af65a12171b55db21c49f1b` |

## Remaining security limitations

The [operator guide](SPRINT-6.4.md) documents the manual transfer boundary and
recovery procedure. Tests demonstrate application controls, not OS separation,
ACL/mount protection, root resistance, cryptographic human identity or production
activation. Discovery must remain unable to write controller-owned files. Without
that isolation, retain exports and do not invoke import in the shared environment.
Same-user code can tamper with Python, files or SQLite; hashes/triggers are not
signatures or an adversarial storage boundary. Protected operator file paths and
full terminal review are prerequisites.

Offline intake cannot establish current GitHub state. Explicit network checks are
public anonymous issue reads, not atomic source/comment/provider snapshots.
Sprint 6.3 retains the original configuration digest rather than configuration
bytes, so this component verifies that digest's identity binding and deterministic
analysis but cannot reconstruct the original scoring configuration. Unknown
formats fail closed; no migration is included.

Risk screening is conservative/advisory, can reject benign text and cannot prove
semantic safety. Operator review must catch obfuscated security/financial/database
work. Filesystem atomicity assumes cooperating catalog writers honor the persistent
lock; an uncooperative operator/root editor can race the last check. STOP has a
similar final-check race. A crash after an intent can leave uncertain outcome or
orphan temp files. Reconciliation is manual and grants cannot be replayed. The
ledger records intents/failures and preserves history; it does not automatically
complete or undo interrupted imports. No live execution follows any catalog write.
