# Sprint 6.13E: prepare the second live-observation canary

This is a preparation-only change. No operator Mac files have been inspected or
changed, no real authorization has been recorded, and no OpenAI request or Codex
worker has run. The deployed `policy-v2.json` and its immutable hashes are not in
this repository. Generate the next policy from that exact protected file locally;
do not substitute the example policy or reconstruct its source manifest.

## Why a new policy works

`Runner.task_prepare` permanently consumes a catalog task ID across all records in
the policy-owned `local.sqlite`, including failed and expired records. Preserve
that check and ledger. The new identifier is `solver-comment-verification-2`.
`src.catalog_canary candidate` retains every original field and entry and adds a
deep copy of `solver-comment-review` under that identifier. This preserves the
source SHA, manifest, allowed solver file, checks, limits, issue snapshot and
comment-only instructions exactly. Review the original instructions to confirm
they still say to add only an explanatory comment and preserve executable behavior.
The helper never refreshes a hash or changes an instruction.

The resulting `policy-v3.json` retains the same state, scratch, binary pins,
credentials references and security boundaries. It has a new policy digest and
new task specification/binding. Historical records still refer to v2. Never
reapprove them against v3: use the original file to inspect their original binding.

`Broker.tx` binds metadata to the digest of the complete broker configuration.
The configuration contains no policy path or policy digest. Each observation
instead embeds its own reviewed policy path/digest, catalog digest, specification,
execution and controller approval. Consequently the existing broker can admit a
fresh v3 task without changing its configuration or ledger metadata. Existing
observations remain bound to v2; changing v2 would invalidate their freshness.
The broker also enforces a unique task ID in its grants table. Neither uniqueness
check is relaxed. `live_limit` and all other existing limits remain unchanged.

## Operator preparation after review and merge

These commands are documentation for a later operator session, not authorization
to perform activation during this PR. Use the reviewed controller checkout and
existing protected paths. Keep other controller activity quiescent. Preserve the
original policies, catalog execution ledger, broker configuration and ledger, API
budget, credentials and all authorization/audit records. Do not clear STOP,
resolve budget holds by deletion, initialize stores or copy a ledger to a new path.

Set `FC_V2`, `FC_V3`, `FC_OBS_BROKER` and `FC_OBS_API` to the existing v2 policy,
a **new** sibling `policy-v3.json`, and the unchanged broker/API configuration.
Use a private operator-owned directory outside source/controller/worker roots.
Inspect the old task and confirm its consumed record is present. Confirm no
unresolved worker or API reservation exists. Do not print credentials.

Build to a private temporary candidate; validate command success before installing
it exclusively at the new versioned destination. The helper prints JSON only and
does not install or modify any file itself:

```sh
umask 077
FC_CANDIDATE=$(mktemp "${FC_V3}.candidate.XXXXXX")
python3 -m src.catalog_canary candidate --original "$FC_V2" > "$FC_CANDIDATE" || exit 1
# Stop on any nonzero exit. Inspect the candidate before the next command.
# Verify the ONLY semantic difference is the identical entry under the new ID.
# ln fails if FC_V3 exists; never overwrite an existing version.
ln "$FC_CANDIDATE" "$FC_V3" && rm "$FC_CANDIDATE"
python3 -m src.catalog_canary preflight --original "$FC_V2" \
  --policy "$FC_V3" --broker "$FC_OBS_BROKER" --api-config "$FC_OBS_API"
```

Stop on any error. Do not run subsequent commands after a failed candidate build.
The hard-link staging name must be removed after successful installation so the
final policy has exactly one link, as required by protected-file validation.
Reconcile failed staging manually without replacing an existing policy.

Preflight reads the existing ledgers without initializing them, verifies the exact
one-entry policy delta, source HEAD/manifest, original consumption, unused second
ID, STOP coverage, broker metadata/config binding, enabled state, task ceiling,
existing budget and absence of unresolved reservations. It reads no credential
contents and performs no transport. This is a preparation check, not a complete
observation review or authority grant; runtime path separation and freshness
checks still apply to the subsequently approved execution.

**Stop here for preparation.** A later independently authorized activation session
may use the existing runner CLI with `--policy "$FC_V3" --state` pointing to the
unchanged catalog state: `task-prepare solver-comment-verification-2`, inspect the
entire new pending specification, then `approve NEW_EXECUTION_ID` on the controlling
terminal. Preparation permanently consumes the new identifier even if approval
or observation later fails. Do not prepare speculatively or reuse the first ID.
Then use `src.live_observation review` with the unchanged broker, v3 policy, new
execution, new task ID and current OS principal. Stop at successful read-only
review. Fresh controller approval is required; no old authorization transfers.

Observation `authorize` and `run` require a separate future decision under
[LIVE-OBSERVATION.md](LIVE-OBSERVATION.md). Do not execute workers or publish an
application change. This PR does not grant permission for any live canary.

## Precise blockers and recovery boundary

If the deployed broker configuration differs from its original ledger metadata,
`Broker schema/configuration mismatch` blocks admission. Do not change metadata,
reset/reinitialize the ledger, point to a replacement ledger, or add a policy
field to the config. If the existing configuration omits the catalog STOP path,
activation is blocked: adding it would change the immutable config digest. Report
that exact missing path and configuration-binding conflict for a separate design
review. This procedure cannot repair it. Disabled brokers, exhausted task/storage
ceilings, consumed second IDs, STOP, changed source, expired approvals and budget
holds also block; do not raise limits or automatically retry.

Offline tests use temporary synthetic sources/stores and mocked terminal decisions
to demonstrate admission under the unchanged broker configuration, preservation
of the first grant, distinct policy bindings, refusal of pending/mismatched tasks,
continued single-use enforcement, configuration mismatch, STOP and budget holds.
The read-only preflight test denies Runner construction and compares every fixture
file byte before/after. No real ledger, terminal, credential or network is used.

Run focused checks with:

```sh
python3 -m unittest discover -s tests -p test_catalog_canary.py -q
python3 -O -m unittest discover -s tests -p test_catalog_canary.py -q
```

Focused local evidence for this PR: new canary suite 4/4 normal and 4/4 under
optimized Python; existing activation suite 8/8, live-observation suite 34/34,
and catalog suite 12/12. Python compilation and `git diff --check` passed.
Responses in existing regression tests are fakes. GitHub Actions was not awaited.
