# Sprint 6.3 — isolated issue discovery

Discovery produces **untrusted recommendations, never authorized development
instructions**. It is a manually invoked, offline-analyzed subsystem with its own
SQLite file. It does not import the catalog, runner, planning/dispatch, budgets,
model broker, independent QA or either publisher. No production mode, scheduler,
background service, approval or promotion command is added. Existing systems and
historical Issue #3 evidence retain their original protocols.

## Operator configuration and workflow

Copy `config/discovery.example.json` into an operator-owned configuration outside
worker/repository control. Review the repository subset, bounds, weights and
absolute STOP file locations. Replace the example STOP locations with **all
applicable existing controller cancellation/STOP locations**, plus an optional
separate discovery STOP. The configuration cannot be supplied by issue content,
repository files or model output. Run discovery under a separate OS identity with
read-only access to the protected configuration and STOP locations, write access
only to discovery state, and no access to coding/publisher credentials, catalog,
execution ledgers or repository working trees. These OS permissions are operator
prerequisites, not a boundary established by Python.

The compiled scope ceiling is exactly `MZKZxyz/fort-custer-server` and
`MZKZxyz/fort-custer-client`; configuration can narrow it. Unknown configuration
fields/schemas, unsupported identities and invalid bounds fail closed. The
configuration has no credential field or executable paths/commands. Source
context is deliberately limited to a public `main` commit identity, issue
metadata, labels and comments. No source file is fetched, checked out or executed.

Create a new discovery database in a separately administered directory. Do not
point this command at an existing execution/publication ledger.

```sh
python3 -m src.issue_discovery --state /operator/discovery-state/discovery.sqlite init
python3 -m src.issue_discovery --state /operator/discovery-state/discovery.sqlite --config /operator/discovery.json discover
python3 -m src.issue_discovery --state /operator/discovery-state/discovery.sqlite proposals
python3 -m src.issue_discovery --state /operator/discovery-state/discovery.sqlite inspect PROPOSAL_ID
```

Only `discover` contacts GitHub. `proposals` and `inspect` open SQLite in read-only
mode and work during STOP; they require neither configuration nor network.
Output is JSON with escaped control characters. `inspect` includes the original
snapshot, its digest, proposal and append-only events. `proposals` lists all
historical revisions, including recommendations whose issue later closed or
became unavailable. They are historical observations, not a current eligible
backlog; `inspect` includes all later observations for the same issue, with
availability/state and discovery timestamps. There is no automatic revocation, catalog update or execution.

`discover` checks configured STOP files and cancellation before/after individual
reads, between proposals and before commit. It never clears STOP or cancels
another system. A blocking read can take up to the fixed 15-second timeout before
cancellation is observed. A STOP written immediately after the final check can
race with a local transaction commit; no authorized work results.

## Read-only collection

`PublicGitHub` exposes only `get(repository, resource, query)`. It builds explicit
GET requests for allowlisted issue lists, issue details/comments and
`commits/main`. It rejects arbitrary URLs, write resources, unknown query keys,
invalid pages and repository identities before opening a connection. Redirects
are disabled; credentials and environment token variables are never read. Public
anonymous access intentionally avoids acquiring even a potentially privileged
GitHub token. Private repositories and privileged read contexts are unsupported.
Do not reuse a publisher transport as a collection dependency.

Collection uses deterministic bounded pages, a maximum total request budget and
one-MiB raw/decoded response ceilings per read. Strings, labels, identities,
timestamps, comment counts and response shapes are validated. Duplicate JSON
keys, nonfinite JSON, duplicate issues/comments, forged identity URLs, wrong
detail numbers and unexpected issue states fail closed. PRs returned from issue
endpoints are excluded. Unknown unrelated GitHub metadata fields are ignored
under this explicitly projected evidence schema; unknown discovery versions are
rejected.

HTTP 403/429 stops the invocation with a redacted rate/access-limit error. No
automatic retry, sleep or checkpoint advancement occurs. Retry manually after the
provider permits reads. Deleted or inaccessible known issues (404/410) receive an
`unavailable` snapshot, **not proof of deletion or closure**. Closed known issues
are snapshotted without producing a new proposal. Other read failures abort.

Checkpoints use the scan start time and GitHub's inclusive `since` filter on
updated open issues. Every previously observed issue is also re-read, so closed,
deleted or changed known issues remain observable. Initial discovery only sees
open issues. All comments must fit bounded pagination and match the observed
comment count. A second issue-detail read detects changes during collection;
changes or pagination exhaustion abort rather than committing partial evidence.
GitHub reads are not an atomic snapshot: concurrent edits to comment bodies,
source `main`, or page ordering can still evade detection. Snapshot digests attest
to the exact observed data, not global consistency or authenticity signatures.
A subsequent scan can discover missed recently updated issues. Large backlogs
that cannot fit configured bounds require an operator-reviewed scope/bound change.

## Analysis, proposal schema and prioritization

`DeterministicAnalyzer` is a replaceable interface, with a strict, validated
`deterministic-1` output containing category and binary signals. There is no LLM
adapter, paid API or model account. Alternate semantics/versions require
controller review; an adapter cannot invent signals or override ranking. Issue
text and comments are preserved as evidence only. Titles appear only in the
reported problem; body/comment instructions are never interpolated into operating
rules, commands, policy or QA. Classification checks exact category labels in a
fixed order (bug, regression-tests, performance, reliability, security,
maintainability, observability, documentation), falling back to maintainability.

The reviewed default weights are:

| Signal | Observed condition | Weight |
| --- | --- | ---: |
| Severity | `critical` or `security` label | 20 |
| User impact | `user-impact` label | 10 |
| Reproducibility | `reproduced` label | 15 |
| Testing | `tests-present` label | 10 |
| Blocking work | `blocks-other-work` label | 5 |
| Evidence available | Nonempty issue body | 10 |
| Complexity | `large` label | -10 |
| Regression risk | `security` or `high-risk` label | -10 |

Scores are sums of weighted binary signals. Labels are unverified reports, not
proof of reproduction, severity, coverage or dependencies. Dependency references
are not followed into other repositories. Risk remains `unverified` (or `high`
when flagged); complexity is `unknown` or `large`; execution cost is null because
available evidence does not support it. Ties sort by repository, numeric issue
number, then full proposal ID. The full weights/configuration digest is bound to
every proposal revision. Weight changes require operator review.

`discovery-proposal-v1` contains: deterministic ID; repository/issue identity;
immutable snapshot digest; problem and proposed assessment; original evidence
references; candidate paths; advisory QA; risk/complexity/cost; priority and
weighted rationale; observed source commit; discovery timestamp; analysis version;
policy digest; category; separately stated facts and hypotheses; fixed state
`proposed`; and fixed trust `untrusted-proposal`. Candidate paths are currently
empty and QA is a prose recommendation for controller-owned review, never an
executable argv. Passing validation confers no authority.

## Durability, retention and review boundary

The dedicated `discovery-store-v1` database stores canonical JSON snapshots and
proposals, append-only discovered/proposed events, and durable per-repository
checkpoints. SHA-256 snapshot IDs include the observed source commit and complete
projected issue/comment evidence. Proposal IDs bind schema, snapshot, analysis
version and configuration digest. Timestamp is observation metadata, excluded
from identity. Same evidence/config/version deduplicates across restarts; changed
issue, comment, source revision or configuration creates a distinct immutable
revision. Previous evidence is retained. SQL triggers prohibit updates/deletes of
snapshots, proposals, events and schema metadata.

A bounded invocation commits all repositories, events and checkpoints in one
transaction. Exceptions, STOP, rate limits and interruptions roll back everything;
restart repeats reads from the prior durable checkpoint, with an overlap, rather
than resuming an unstable page number. SQLite permits one discovery writer at a
time. Schema checks reject other databases without migration; initialization is
exclusive and never overwrites an existing file.

Retention is a **capacity stop**, not automatic deletion. Configuration caps
snapshots, events and combined UTF-8 snapshot/proposal payload bytes; SQLite page,
index and checkpoint overhead is additional and bounded by row limits. At capacity
or on a prospective overflow the scan fails without advancing checkpoints or
deleting evidence. Operators archive the complete database read-only and
explicitly initialize a separate store after reviewing retention requirements.
A new store starts a fresh checkpoint history and may rediscover issues. No
cleanup, destructive migration, automatic rotation or historical rewriting exists.
Same-user SQLite access is not tamper-proof; protect state/backups externally.

The state boundary is:

| State | Owner |
| --- | --- |
| Discovered | Discovery snapshot event |
| Proposed | Untrusted discovery recommendation |
| Operator-reviewed | Independent operator process; not implemented here |
| Prepared for coding | Existing reviewed catalog/runner |
| Approved for coding | Existing separate terminal approval |
| Validated | Existing independent QA |
| Approved for publication | Existing separate publication protocol |

There is **no proposal-to-catalog promotion implementation**. An operator may
consult evidence while independently authoring a reviewed catalog entry. The
catalog's exact schema rejects a proposal as a task entry. Discovery has no API
for coding, catalog mutation, branches, PRs, comments, merge, deployment or
scheduling. It does not reserve execution budgets or reinterpret historical
approvals. See [offline evidence](SPRINT-6.3-EVIDENCE.md).
