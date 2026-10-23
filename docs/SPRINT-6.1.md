# Sprint 6.1 — reviewed local task selection

The local runner now resolves `local-catalog-v1` tasks from a declarative catalog
inside the **operator-owned local policy JSON**. There is no discovery, proposal
promotion endpoint, issue fetch, scheduler, automatic authorization, generalized
publisher, merge, deployment, or change to enabled production profiles. The
legacy `prepare --issue 3 ...` protocol and its publisher remain separate.

## Operator catalog schema

Start with the disabled `config/local-development.example.json` policy. Do not
modify the historical Issue #3 policy or ledger to retrofit a catalog: the
publisher requires their original digest. For new work, provision a distinct,
reviewed policy and its one policy-owned state directory. Never create fresh
state to bypass a hold on an existing task. Keep both outside the worker root.
All configured source directories must also be separate from scratch and state.

Add an exact `identity` and `reviewed_issues` list to each approved `repositories`
entry. Version 1 supports only `fort-custer-server` →
`MZKZxyz/fort-custer-server` and `fort-custer-client` →
`MZKZxyz/fort-custer-client`, and only when explicitly configured. The automation
repository is excluded. Each entry retains the existing absolute `source`, exact
40-character `sha`, and `branch`. The local source's origin must equal
`https://github.com/OWNER/REPO.git`. No remote is contacted. The origin is an
operator assertion, not cryptographic evidence of GitHub ownership. One reviewed
source commit per repository per policy is supported; branches are descriptive,
never resolved to mutable HEAD at execution time.

Add this `catalog` object to that policy (placeholders deliberately fail closed):

```json
{
  "catalog": {
    "schema": 1,
    "tasks": {
      "reviewed-solver-fix": {
        "repo": "fort-custer-server",
        "repository": "MZKZxyz/fort-custer-server",
        "source": "REPLACE_WITH_REVIEWED_40_CHARACTER_SOURCE_SHA",
        "input_hash": "REPLACE_WITH_REVIEWED_SOURCE_MANIFEST_SHA256",
        "issue": 3,
        "issue_snapshot": {
          "number": 3,
          "state": "open",
          "html_url": "https://github.com/MZKZxyz/fort-custer-server/issues/3",
          "title": "Operator-reviewed snapshot title",
          "body": "Operator-reviewed issue text, retained as untrusted data",
          "comments": []
        },
        "allowed": ["tools/maze-analyzer/solver.js", "test/analyzer.test.js"],
        "instructions": "REPLACE_WITH_OPERATOR_REVIEWED_CODING_INSTRUCTIONS",
        "checks": [
          {
            "name": "solver-syntax",
            "argv": ["node", "--check", "tools/maze-analyzer/solver.js"],
            "timeout_seconds": 30
          },
          {
            "name": "analyzer-tests",
            "argv": ["node", "--test", "test/analyzer.test.js"],
            "timeout_seconds": 60
          }
        ],
        "limits": {
          "timeout_seconds": 300,
          "api_spend_cents": 0,
          "usage_policy": "subscription-no-paid-refills"
        },
        "mode": "local_codex_development",
        "approval": "controlling-terminal"
      }
    }
  }
}
```

Catalog and task/check/limit objects reject unknown fields and unsupported
versions. Task IDs match `[a-z0-9][a-z0-9-]{0,63}`. Issue numbers must also be in
the repository's operator-maintained `reviewed_issues` list, and the snapshot
must describe that exact open issue URL and number, with no `pull_request` key.
Titles, bodies, comments and any other snapshot metadata are bound verbatim as
data; none is inserted into the coding prompt or interpreted as policy. The
operator independently reviews issue provenance and translates requirements into
`instructions`. No model-generated proposal or issue text can edit the catalog.

To obtain the source manifest during operator review, call
`manifest(source_files(source_path, exact_sha, explicit_allowed_paths))` from
`src.local_runner` on the trusted source. Independently review the SHA, safe tree,
issue snapshot and paths before copying this hash into policy. The manifest is
SHA-256 over canonical sorted JSON mapping each tracked path to its executable
mode and content SHA-256. Source export rejects symlinks, submodules, special
entries, Git control metadata and secret `.env` files as before. All allowed
paths must already exist. Adding/deleting files is deliberately unsupported.

Paths are literal, case-sensitive relative file names. There is no glob, prefix,
or directory expansion. Traversal, absolute paths, option-like components,
`.git`, `.codex`, `.github`, `.env*`, `AGENTS.md`, Git attributes/modules,
`config`, `infra`, `migrations`, and `src/local_*` edits are rejected. A candidate
must change at least one allowed file; it need not change every allowed file.
Any other change (including ignored files), deletion of an allowed file,
symlink, hardlink, special file or oversized output file fails validation.

## Manual workflow

On the existing trusted, credential-free local coding host, after reviewing the
policy, CLI/Node binary hashes, existing subscription login, disposable scratch
parent and source checkout, use:

```sh
python3 -m src.local_runner --policy /operator/catalog-policy.json --state /operator/catalog-state task-list
python3 -m src.local_runner --policy /operator/catalog-policy.json --state /operator/catalog-state task-prepare reviewed-solver-fix
python3 -m src.local_runner --policy /operator/catalog-policy.json --state /operator/catalog-state inspect RUN_ID
python3 -m src.local_runner --policy /operator/catalog-policy.json --state /operator/catalog-state approve RUN_ID
python3 -m src.local_runner --policy /operator/catalog-policy.json --state /operator/catalog-state execute RUN_ID
```

`task-list` resolves and validates the complete catalog without preparing runs.
Preparation pins the complete resolved task, protocol, catalog ID, source content
manifest, full reviewed entry, prompt plus fixed guardrails, commands, limits,
issue snapshot and whole policy digest. Every approval/claim re-resolves them
from controller policy and compares the complete canonical specification.
Changing allowed paths, instructions, checks, limits, source, issue or any policy
field invalidates the old authorization; computing a new task digest does not
promote an unreviewed specification.

Approval still requires the exact `APPROVE <binding>` response from `/dev/tty`
within ten minutes. There are no approval flags, environment variables, stdin
fallbacks, issue directives or model approval messages. Only the Python trusted
controller API accepts a response (for the terminal adapter and offline tests).
As before, this is local terminal authorization, not a remote identity service.

A catalog ID is single-use in its ledger, including failed, expired and cancelled
work. There is no retry, expiry renewal, hold release or reset command. The
transactional claim precedes subprocesses; a surviving `running` record blocks
all subsequent execution until separately reviewed operator reconciliation.
Different reviewed tasks can be prepared independently, but only one execution
may run per policy-owned state. `cancel` sets the same persistent STOP file;
new preparation, approval and execution fail while it exists. Inspection remains
available. Never remove STOP or rewrite/delete historical records to resume.

## Independent QA and limits

The controller supports only the exact argv grammar
`["node", "--check" | "--test", "existing/literal/file.js"]` (also `.mjs` or
`.cjs`). Each unique named check has its own positive integer timeout bounded
by the task timeout; the task timeout cannot exceed policy timeout or 2400 s.
Checks may target any reviewed source file, including a test outside the editable
allowlist. The worker cannot select commands, executables, working directories,
environment, timeout or output limits. Shells, inline eval, loaders, installers,
custom executables, wildcards and dynamic substitution are unsupported.

QA reconstructs the original safe source and only the approved candidate files
in a fresh root, verifies the complete mode/content manifest, runs fixed Git
diff checking plus reviewed checks, and verifies QA did not modify the candidate.
It records the complete binary patch, candidate tree/revision, manifests and
bounded command results. Exact Node binary hash/executable checks, isolated
environment, fixed fresh-root cwd, per-command supervision, process-group
termination and the independent guardian remain in effect. Each subprocess has
an 8 MiB output threshold; snapshot files have a 16 MiB limit. These are existing
supervision limits, not kernel disk or memory quotas. Output may briefly exceed
the threshold between supervision polls. No stdout text is interpreted as a
command or approval. Wall-clock timeout includes coding and QA; the supervisor
also uses monotonic deadlines.

Supported spending policy is **zero API spend**, using only the pinned official
CLI's existing ChatGPT subscription login, with no API fallback, paid refills,
credit purchase or automatic login. Nonzero API budgets and other usage policies
are rejected. Subscription usage counters are retained, but a per-task token or
monetary hard cap is **not available** in this CLI contract. CPU/RAM quotas and
kernel filesystem quotas are also not introduced. Tasks needing these guarantees
are unsupported and must wait for a reviewed execution adapter. No production
mode or readiness configuration is enabled here.

## Trust boundaries and legacy preservation

The operator controls policy, trusted Git source, binaries, SQLite ledger and
terminal. Candidate files, issue content and CLI output are untrusted. Approval
hashes detect content changes but do not authenticate a privileged local attacker
who can rewrite controller code/policy/ledger or impersonate the operator. Keep
permissions and independently reviewed backups, as required by Sprint 5.9.
History is retained using the existing record/history format; no migration,
compaction, evidence regeneration or historical record rewrite is performed.

The existing worker sandbox flags and credential allowlist are unchanged. QA
still executes JavaScript on the trusted local host as in Sprint 5.8; it is not a
new OS isolation boundary. Tests may import other candidate source files. Use
only operator-reviewed low-risk code on a disposable credential-free host whose
OS controls deny access to controller state and secrets. This sprint does not
claim sandboxing arbitrary hostile JavaScript or deterministic behavior of
arbitrary application tests. Controller command selection and acceptance rules
are deterministic; operators must review tests for stable local behavior.

Legacy records have no `protocol` field. Their fixed Issue #3 checks and artifact
interpretation remain unchanged. New catalog records have `local-catalog-v1`;
unknown protocols fail closed. The Sprint 5.9 publisher rejects **every** record
with a protocol field before reconstruction and retains its original hardcoded
run/base/candidate/tree/revision allowlist. Coding approval cannot authorize any
GitHub mutation. Inspect the preserved
`d808dca82ca74d65ba0b7ba9ab7197de` with its original policy/state; do not execute it
again or manufacture replacement evidence. Its operator artifacts are not in
this checkout, so their real-world presence and integrity cannot be attested here.

## Proposed Sprint 6.2 interfaces (not implemented)

- An inert proposal format carrying repository/issue/source suggestions and
  rationale, with no executable or approval status. An operator-only review tool
  could emit a catalog diff for separate review; never automatic promotion.
- A versioned execution adapter attesting hard resource limits and authoritative
  usage enforcement, with explicit capability rejection for unsupported budgets.
- A separate QA isolation adapter retaining fixed controller argv, manifest
  reconstruction, bounded results and stable test fixtures.
- An operator reconciliation record referencing an expired/failed original run,
  preserving history and requiring a fresh terminal challenge. No automatic retry.
- Any future publisher must have a new separately reviewed protocol and approval;
  this sprint's catalog records must continue to be rejected by Sprint 5.9.
