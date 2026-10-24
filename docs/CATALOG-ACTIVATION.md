# Separate catalog activation on an existing Mac — Sprint 6.13C

This procedure establishes **one new review and execution ID** alongside an
installation whose policy has no catalog. It does not migrate policy or history.
The historical pending, failed and validated records retain their original meaning
and bytes. None authorizes this task. Installation stops at read-only Sprint 6.13B
observation review: no inference, coding, QA command, commit, push or publication
is performed. An approval is permission recorded for review; it is not execution.

Use the reviewed, merged controller checkout containing Sprint 6.13B and this
change, on the trusted controller OS account in `/bin/bash`. Do not follow the
older LIVE-OBSERVATION step 1 suggestion to use an existing approved task when
there is no catalog approval: this document supplies the separate activation
procedure for that case. Do not substitute the legacy issue-specific prepare
command. No historical validated execution is a catalog approval.

## Paths and prerequisites

Set these values to operator-chosen **absolute physical paths**. Resolve macOS
symlink aliases such as `/var`, `/tmp`, and Homebrew executable symlinks first.
These are examples, not fixed installation paths:

```sh
umask 077
FC_CONTROLLER=/absolute/reviewed/fort-custer-automation
FC_LEGACY_POLICY=/absolute/legacy/policy.json
FC_CATALOG_CONTROL=/absolute/new-catalog-control
FC_CATALOG_POLICY="$FC_CATALOG_CONTROL/policy.json"
FC_CATALOG_STATE="$FC_CATALOG_CONTROL/state"
FC_CATALOG_SCRATCH=/absolute/new-catalog-coding-scratch
FC_OBS_BROKER="$FC_CATALOG_CONTROL/observation.json"
FC_OBS_LEDGER="$FC_CATALOG_CONTROL/observation.sqlite"
FC_OBS_SCRATCH=/absolute/new-observation-scratch
FC_OBS_API=/absolute/existing/api-controller.json
FC_OBS_PRINCIPAL="$(id -un)"
FC_TASK=solver-comment-review
cd "$FC_CONTROLLER"
```

Preserve the legacy policy, ledger, state, scratch and publication records in
place. The new control directory must be private, outside source repositories,
controller checkout, both scratch directories, and the dedicated Codex
authentication `operator_home`. Do not use your entire login home as that
`operator_home`: the broker correctly rejects stores beneath that protected root.
The new state, coding scratch, observation scratch and observation ledger must
be mutually separate. The policy and broker JSON must also sit outside these
state/scratch roots. No scheduled job may point at the new configuration.

Before starting, inspect existing installation paths and STOP locations with the
operator's normal read-only tools. Preserve existing STOP files; if stopped,
resolve the reason through the normal operator procedure, never delete a STOP
just to pass this checklist. Do not create directories inside historical state.
Use the existing API configuration, key and budget ledger, with its existing
$10/day and $100 lifetime ceilings and reviewed pricing. Never initialize another
budget. The preflight checks key **metadata only**, not credential contents.
It requires zero unresolved holds and enough remaining budget for the
20,204,800 nano-USD reservation. Connectivity must remain disabled.

Only create the new private control directory and review documents at this stage:

```sh
mkdir -m 700 "$FC_CATALOG_CONTROL"  # must be a new directory; stop if it exists
cp config/catalog-activation.example.json "$FC_CATALOG_CONTROL/candidate.json"
cp config/live-observation.example.json "$FC_OBS_BROKER"
chmod 600 "$FC_CATALOG_CONTROL/candidate.json" "$FC_OBS_BROKER"
```

## Deterministic task construction and full review

Author the new policy independently from the supplied example. **Do not copy or
rewrite the legacy policy or any approval record.** In `candidate.json`, replace
all placeholder paths, binary digests and both source SHAs. Set state and scratch
to the values above. Use existing, operator-reviewed immutable application source
and exact origin identity; never fetch, rebase or change it as part of activation.
This activation profile supports the reviewed Codex `0.163.0` pin only.
Set `operator_home` to the dedicated existing Codex authentication home. Verify
its availability manually; no login or agent probe is part of preflight.

The example is a narrowly scoped, comment-only server task for issue #3. Confirm
from the operator's reviewed issue snapshot that #3 is still the appropriate open
issue; replace the issue fields consistently if it is not. The minimal snapshot
is a local review assertion, not an online freshness check. Inspect the exact
committed `tools/maze-analyzer/solver.js` and `test/analyzer.test.js`; confirm that
`compile` exists and that the requested comment is useful. If not, stop and author
a different narrowly scoped task with an exact existing file and independent QA.
Do not invent a change solely to get past admission. Review the two Node QA
commands, including the test's contents and dependencies; preflight does not run
these commands or establish that QA passes. Keep task JSON within the broker's
1,024-byte ceiling. No shell commands are accepted as QA.

Inspect source and pins without starting Codex:

```sh
# Set FC_SOURCE to the exact application source path in candidate.json.
git -C "$FC_SOURCE" rev-parse HEAD
git -C "$FC_SOURCE" remote get-url origin
git -C "$FC_SOURCE" show HEAD:tools/maze-analyzer/solver.js
git -C "$FC_SOURCE" show HEAD:test/analyzer.test.js
# Use physical binary paths from the new policy, after independently reviewing them:
shasum -a 256 /absolute/trusted/bin/codex /absolute/trusted/bin/node
```

Leave only `input_hash` as `UNREVIEWED`. The helper fills it from the complete
committed repository manifest, validates task resolution, and prints canonical
JSON. It never changes a file or initializes a ledger. Same candidate and same
source produce the same policy and specification. It refuses to refresh an
already populated manifest. The source's HEAD must equal both reviewed SHAs.

```sh
# Refuse to overwrite any previously reviewed policy.
(set -o noclobber; python3 -m src.catalog_activation build \
  --candidate "$FC_CATALOG_CONTROL/candidate.json" > "$FC_CATALOG_POLICY")
```

If this command fails, preserve its output for diagnosis; do not use a partial
policy. Reconcile review documents manually before trying a new destination.
Read the **entire resulting policy**, not just its hash. Explicitly review task
instructions, issue provenance, exact revision, repository identity and origin,
full manifest, allowed files, QA argv/timeouts, limits, terminal-only approval,
binary pins, mode and paths. `enabled=true` is needed for eventual admission,
but sends nothing and schedules nothing.

Edit the broker JSON independently: use the v2 observation-only schema, exactly
one slot/live limit, new ledger and scratch paths above. Include **both** the
legacy state `STOP` path and `$FC_CATALOG_STATE/STOP`, plus every additional
operator-enforced STOP path. Set `enabled=true` in the final reviewed JSON before
initialization; the ledger will bind this exact configuration digest. No synthetic
or historical broker ledger can be reused.

## Read-only preflight before any new ledger

```sh
python3 -m src.catalog_activation preflight \
  --legacy-policy "$FC_LEGACY_POLICY" --policy "$FC_CATALOG_POLICY" \
  --broker "$FC_OBS_BROKER" --api-config "$FC_OBS_API" \
  > "$FC_CATALOG_CONTROL/preflight.json"
python3 -m json.tool "$FC_CATALOG_CONTROL/preflight.json"
```

Proceed only on exit 0 and `ready=true`. The result includes the **complete task
specification**, its digest, source revision, allowed files, QA and policy digest.
Explicitly compare all of these against the reviewed policy and committed source.
The helper rejects unsupported modes, stale HEAD/manifest, oversized observation
tasks, missing or changed pinned binaries, unprotected/symlink destinations,
overlapping stores, omitted/active STOP, existing new state, missing existing
budget, unresolved holds and insufficient budget. It does not construct a Runner,
create directories, initialize SQLite, contact a service, approve, or read old
approval documents. Record this review with your normal operator audit procedure.
A successful preflight is **not authorization** and is only a point-in-time check.

## Establish the separate approval and stop at observation review

Only after reviewing the complete preflight output, create the reviewed new
scratch parents. Preserve all JSON; changing it requires a fresh review.

```sh
mkdir -m 700 "$FC_CATALOG_SCRATCH" "$FC_OBS_SCRATCH"
python3 -m src.local_runner --policy "$FC_CATALOG_POLICY" \
  --state "$FC_CATALOG_STATE" task-prepare "$FC_TASK" \
  > "$FC_CATALOG_CONTROL/prepared.json"
python3 -m json.tool "$FC_CATALOG_CONTROL/prepared.json"
```

`task-prepare` initializes only the new state/ledger and creates one pending record
with a random execution ID. No worker runs. Record its exact `id` as
`FC_OBS_EXECUTION`; never take an ID from the legacy installation. The catalog ID
is single-use, including failures and expiry. Do not reinitialize or overwrite a
ledger to recover from failure. Approval expires 600 seconds after preparation;
if review cannot finish in that window, stop for explicit operator reconciliation.

```sh
read -r -p 'NEW prepared execution ID: ' FC_OBS_EXECUTION
python3 -m src.local_runner --policy "$FC_CATALOG_POLICY" \
  --state "$FC_CATALOG_STATE" inspect "$FC_OBS_EXECUTION"
python3 -m src.local_runner --policy "$FC_CATALOG_POLICY" \
  --state "$FC_CATALOG_STATE" approve "$FC_OBS_EXECUTION"
```

Review the displayed **complete** record again. Type its exact `APPROVE <binding>`
challenge on the controlling terminal. No historical approval, pipe, environment
variable, `--yes` or copied response substitutes for this fresh decision. This
records the existing task-bound coding approval prerequisite; **do not execute
it**. Observation authority remains separately gated.

Initialize the separate observation broker once, then run the existing Sprint
6.13B read-only admission review:

```sh
python3 -m src.live_observation init-broker --broker "$FC_OBS_BROKER"
python3 -m src.live_observation review --broker "$FC_OBS_BROKER" \
  --policy "$FC_CATALOG_POLICY" --execution "$FC_OBS_EXECUTION" \
  --task "$FC_TASK" --principal "$FC_OBS_PRINCIPAL"
python3 -m src.api_controller status --config "$FC_OBS_API"
python3 -m src.live_observation audit --broker "$FC_OBS_BROKER"
```

**Stop here.** Successful review establishes eligibility, not a live request.
Do not run `execute`, `publish-*`, observation `authorize` or observation `run`
during activation. There is no publication boundary shared with legacy state:
new publication tables, if ever separately authorized, belong only to the new
ledger. This procedure creates none.

A future, separately authorized supervised canary must follow
[LIVE-OBSERVATION.md](LIVE-OBSERVATION.md), using this new policy/execution ID,
the existing budget and final new broker config. It needs a second, distinct
controlling-terminal `AUTHORIZE ONE OBSERVATION <digest>` decision. No task
approval alone authorizes inference. Expired reviews, STOP or changed source,
policy or approvals block it. Do not retry inference or manufacture replacement
approvals on failure. Preserve both installations and all audit evidence.

## Offline evidence and limits

`test_catalog_activation.py` exercises legacy history preservation, deterministic
construction, no-write preflight, failure prerequisites, STOP, revision and path
mismatches, fresh terminal approval and the complete v2 admission path. Its final
response uses only fake Responses transport, with sockets, key helper, coding
and publication denied. Linux/macOS broker CI runs it normally and under `-O`;
full regression workflows discover it too. No CI job activates a real policy.

Protected controller OS access remains the authority boundary. This helper does
not sandbox a malicious operator, validate login, certify QA correctness or watch
for races after preflight. Existing runner/broker checks enforce their bindings
at approval and observation admission. Keep the legacy installation quiescent
using its normal operator controls; this procedure does not cancel or reinterpret
its pending execution. Preserve historical state and never clear STOP automatically.
