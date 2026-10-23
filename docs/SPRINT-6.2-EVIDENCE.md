# Sprint 6.2 — offline implementation evidence

Review date: 2026-10-22 (America/Los_Angeles).
Base: `c1f7d4364894adc66cd52b06d4b4a5db7f3efb03`, merged Sprint 6.1 PR #10.
The connected GitHub API confirmed this as latest `main`. The shell Git proxy
was unreachable. Changed upstream files were retrieved through the connected
read API, verified against their Git blob IDs, and assembled into the exact
upstream tree `b740a6e9014ac57bde811df562f9d056dfa0639e`. Reconstructing the signed
commit from its GitHub verification payload/signature reproduced its exact SHA.
No network bypass, credential discovery or alternate login was used.

## Validation

- Baseline: `python3 -m unittest discover -s tests -q` — 193 tests in 39.557 s,
  OK, one existing skip.
- New suite: `python3 -m unittest discover -s tests -p test_catalog_publication.py -q`
  — 32 tests in 27.766 s, OK.
- Final regression: `python3 -m unittest discover -s tests -q` — 225 tests in
  78.757 s, OK, one existing skip (`age` is unavailable).
- `make lint` — pinned image inputs/live gate validation and Python compileall
  passed. No image builds or live gate activation.
- `git diff --check` — passed.

Tests use temporary synthetic Git repositories, mock coding output, local fixture
Node checks, and an in-memory fake GitHub transport. No actual Codex task,
server/client PR, server/client GitHub write, credential provisioning, merge,
deployment or production activation occurred. The requested automation-repository
draft PR is a delivery action, separate from these offline publication tests.

## Acceptance and security coverage

| Requirement | Offline evidence |
| --- | --- |
| Two distinct reviewed tasks | `constant` and `test-case` reconstruct into distinct trees, publication commits, branches, bodies and fake draft PRs. |
| Multiple reviewed repositories | Synthetic client `demo.js` publishes against `review/base`; another server task publishes from the same reviewed policy/ledger using a separate fake remote. |
| Durable reconstruction | Worker and QA roots have been removed; a restarted runner reconstructs from SQLite plus pinned Git source. Original record is unchanged. |
| Complete action binding | Full resolved specification, policy, artifact/history/QA digests, manifests, tree, changed paths, source/base branch, deterministic commit, title/body, UID, draft action and expiry are checked. |
| Tampering | Reject changed policy/source/allowlist, missing source, patch suffix, manifest/tree/revision evidence, changed-file set, usage, history, QA command/code/reason/output and request edits including recomputed request hashes. |
| Separate authorization | Coding response, absent preflight, forged response, unvalidated task, expired approval, replay, deleted approval audit and cancellation/STOP reject before remote writes. CLI has no approval flag or stdin fallback; existing terminal tests verify separate tty handles and terminal checks. |
| Remote preflight | Reject wrong identity, advanced base, existing branches (including exact candidate before claim), and existing PRs including closed ones. |
| Durable claims/recovery | New branch claim precedes creation; lost branch responses reconcile after restart; pre-write branch failure can retry atomic creation; lost PR responses adopt only an exact draft. Empty ambiguous PR results never repeat POST, renew approval or reset the hold. |
| Expiry and mid-operation changes | Expired unfinished recovery retains its hold. Cancellation is checked between individual object writes. A changed base during upload blocks branch and PR creation. |
| Read-only verification | Repeated completion and remote inspection do not write; changed draft state, title/body, base/head, repository, commit metadata, URL or maintainer settings fail verification. |
| Transport/credentials | Repository/scope/selection mismatch rejects. Blob/tree/commit identities are compared. Only reviewed feature-ref and draft PR payloads exist; update/delete refs, merge, review, release, deployment and non-draft payloads reject without network access. API errors redact credentials and do not retry. |
| Privilege boundary | Observed publisher subprocesses are exclusively `/usr/bin/git`, with disabled hooks and credential-free environment. No publisher application QA, installer or model execution. |
| Legacy separation | Legacy reconstruction/preparation/execution reject catalog runs; the catalog publisher rejects no-protocol legacy runs and unknown versions. Existing Sprint 5.9 regression tests remain intact. |

## Preserved historical artifacts

The existing runner, catalog and legacy publisher are byte-for-byte unchanged
from the verified main commit. No historical record was migrated, regenerated,
reauthorized, deleted or rewritten. Pre-change and post-validation SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `state/automation.db` | `53991a6539c1ada5fbf23c8ff89523c253b801b8e5ca834e003fb88304e62fc6` |
| `docs/SPRINT-5.9.md` | `22fa4544657cfcd6b8353ef84ae0633a72318ed370b9377a599a0cbdf4f9cc6a` |
| `docs/SPRINT-5.9-EVIDENCE.md` | `2c643e8f50c7e5807387cee183f014bd32df98db7af65a12171b55db21c49f1b` |

The original run `d808dca82ca74d65ba0b7ba9ab7197de` and legacy base,
candidate manifest, tree and revision constants are unchanged. The actual
operator ledger/policy and trusted server objects for that historical run are
not present here; real-run publishability is not claimed or simulated as proof.

## Known limitations and external assumptions

See [the runbook](SPRINT-6.2.md) for complete operator prerequisites and recovery
limits. Actual GitHub credential scope, branch protection, separate OS identity /
host, protected policy/ledger/source and reviewed backups are externally enforced.
A same-user Python process is not security isolation. SQLite histories and
colocated digests are not tamper-proof signatures, and generalized tasks have no
compiled candidate pin. QA provenance trusts the protected controller records;
the old synthetic QA revision metadata cannot be recomputed independently.
GitHub repository identity is the exact reviewed full name, not a stored numeric
ID. GitHub calls cannot atomically bind a base check to later writes; final
verification detects observed races but cannot retract accepted operations.
Unsupported branch grammar, missing evidence, oversized PR evidence, expired
unfinished work and unresolved ambiguous POSTs fail closed. No automatic repair,
renewal, hold reset or cleanup mutation is provided.
