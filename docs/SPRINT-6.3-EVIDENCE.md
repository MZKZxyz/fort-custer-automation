# Sprint 6.3 — offline implementation evidence

Review date: 2026-10-22 (America/Los_Angeles).
Base: `ce69f40f7dfdade29e279d40aa079d6ee9d3a184`, merged Sprint 6.2 PR #11.
The connected GitHub API confirmed latest `main` before implementation and again
before delivery. The shell Git proxy was unreachable. The eleven changed files
since the supplied checkout were retrieved through the connected read API,
verified against their Git blob IDs, and assembled into exact upstream tree
`20f68d384011a9e3656f52dd5c65058534985260`. Reconstructing the signed commit from
GitHub's verification payload/signature reproduced its exact SHA. No network
bypass, credential acquisition or alternate login was used.

## Validation

- Baseline: `python3 -m unittest discover -s tests -q` — 225 tests in 64.034 s,
  OK, one existing skip (`age` unavailable).
- Discovery: `python3 -m unittest discover -s tests -p test_issue_discovery.py -q`
  — 47 tests in 0.244 s, OK, no skips.
- Final regression: `python3 -m unittest discover -s tests -q` — 272 tests in
  89.301 s, OK: 271 passed, one existing skip (`age` unavailable). All 225 legacy
  tests and 47 discovery tests are included.
- `make lint` — pinned image inputs/live gate validation and Python compilation
  passed. No image build or live activation.
- `git diff --check` — passed.
- `python3 -m src.issue_discovery --help` — exposes only init, discover,
  proposals and inspect.

All new tests use synthetic issues/comments and injected transports or mocked
HTTP responses. Existing execution/publication regressions use their existing
synthetic/offline fixtures. No live Codex invocation, server/client GitHub write,
publisher credential, model account, paid API, deployment, merge, background work
or production execution was used. The automation-repository draft PR is the
requested delivery action, outside the discovery subsystem.

## Acceptance and boundary evidence

| Requirement | Tests / evidence |
| --- | --- |
| Both repositories, multiple issues, paging | `test_multiple_repositories_and_pagination` collects three issues across both exact allowlisted repositories and inspects each event/snapshot. |
| GET-only enforcement | `test_only_get_no_credential_acquisition` inspects the actual Request method, absence of Authorization despite synthetic token environment variables, timeout 15, and bounded read size 1,048,577. `PublicGitHub`'s sole public operation is `get`. |
| Scope / no write resources | `test_arbitrary_endpoints_and_query_rejected_before_network` verifies invalid repos, traversal, Git refs, PR endpoints, unknown query keys and invalid paging never reach the mocked opener. Redirects are disabled. |
| Rate limits / bounded failures | Rate-limit tests cover 403/429 with exactly one request, no retry or secret diagnostic; 404/410, 500, redirects, corrupt UTF-8/JSON, oversized bodies, duplicate keys and NaN reject safely. |
| Injection remains evidence | Malicious body/comment text includes approval, publication, token and shell instructions. Original evidence is preserved while subprocess execution is forbidden by the test. It does not become a change instruction, path or QA command. |
| Provider identities / PRs | Tests reject forged repository/detail/comment identities, wrong issue numbers, invalid timestamps/labels/counts and duplicate/conflicting evidence; PR-shaped issue records are excluded. |
| Changes / deleted / closed | Separate tests preserve earlier evidence while adding changed source/issue revisions, snapshot closed issues without a new proposal, and record unavailable known issues without claiming deletion. Inspection exposes later availability observations. Moving details/count mismatch abort. |
| Reproducibility / ranking | Independent stores produce identical IDs for identical evidence/config/version. Weighted ranking and stable ties are checked; label signals are explicitly unverified. Config-weight changes create distinct revisions. |
| Deduplication / immutability | Restart retains exact proposal documents/events. Source/issue revisions retain old evidence. SQL triggers reject UPDATE and DELETE on proposals, snapshots, events and schema metadata. |
| Checkpoints / interruptions | Inclusive-since checkpoint reads are verified. Rate limits, request/page/issue bounds, STOP, mid-analysis cancellation and KeyboardInterrupt roll back all partial evidence and checkpoints; subsequent restart succeeds. |
| Retention | Snapshot, event and payload quota failures retain prior records without checkpoint advancement or automatic deletion. |
| Unknown formats / analyzer | Invalid config, unknown analyzer version/output/signals, malformed or future proposal formats and foreign state databases fail closed. Existing state cannot be overwritten or migrated. |
| Read-only review | Proposal list/inspection leaves database bytes unchanged; missing state is not created by reads. |
| Catalog boundary | A generated proposal fails the existing reviewed catalog resolver's exact task schema. No promotion command exists. |
| Execution / publication isolation | AST import tests reject imports of catalog, runner, planning, execution, publishers, model broker or subprocess in discovery modules. No transport write method exists. Full legacy suite is run unchanged. |

## Historical records preserved

The runner, local catalog, legacy publisher, catalog publisher and all existing
tests are byte-for-byte unchanged from verified `main`. No existing ledger was
migrated, reset, approved, executed or published. Matching historical SHA-256s:

| File | SHA-256 |
| --- | --- |
| `state/automation.db` | `53991a6539c1ada5fbf23c8ff89523c253b801b8e5ca834e003fb88304e62fc6` |
| `docs/SPRINT-5.9.md` | `22fa4544657cfcd6b8353ef84ae0633a72318ed370b9377a599a0cbdf4f9cc6a` |
| `docs/SPRINT-5.9-EVIDENCE.md` | `2c643e8f50c7e5807387cee183f014bd32df98db7af65a12171b55db21c49f1b` |

The historical run `d808dca82ca74d65ba0b7ba9ab7197de` and original Issue #3
constants retain their existing interpretation. Actual operator state/source
artifacts are not available here; no claim of real-run publishability is made.

## Limits

See [the operating guide](SPRINT-6.3.md) for scope, schema, labels/weights, manual
review workflow, retention and the complete state boundary. Collection is public
and anonymous; private repositories or authenticated reads are intentionally
unsupported. Source context stops at an observed commit SHA. No code inspection,
reproduction, test execution, cost estimation, paid analysis or automatic
promotion is claimed. Quotas fail closed instead of silently truncating a scan.
GitHub pagination/comment reads are not atomic and do not prove global snapshot
consistency. Same-user Python/SQLite is not OS isolation or tamper-proof storage;
operator protection of config, STOP locations and discovery-only state is an
external requirement. The discovery identity must have no access to publisher
credentials or mutable execution/catalog/repository state. No unsafe privilege
shortcut or live discovery activation is included.
