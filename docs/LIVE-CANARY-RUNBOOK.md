# One manually initiated development canary — preparation only

## Sprint 6.10 Mac procedure — mandatory stop before live work

**This release cannot activate a real worker.** The steps below are a
copy-paste-ready preparation procedure plus an explicit activation checklist.
Steps 9–13 describe the exact required authorization order and identify missing
commands. Inventing commands/receipts or removing the Sprint 6.8 gate is not an
activation procedure. Missing software as well as missing Mac evidence blocks.
The older Sprint 6.9 notes below are retained as history; this section governs.

### 1. Pull the independently reviewed automation release

Use `/bin/bash` for all shell snippets. Run as `fc-controller` in its protected checkout, after choosing a reviewed
release (the draft PR from this task is not yet a reviewed release):

```sh
cd /Users/fc-controller/fort-custer-automation
git status --short
test -z "$(git status --porcelain)" || exit 1
git fetch origin main
read -r -p "Independently reviewed full automation commit: " FC_RELEASE
git cat-file -e "$FC_RELEASE^{commit}" || exit 1
git merge-base --is-ancestor "$FC_RELEASE" origin/main || exit 1
git switch --detach "$FC_RELEASE"
test "$(git rev-parse HEAD)" = "$FC_RELEASE" || exit 1
export FC_POLICY=/Users/fc-controller/control/catalog-policy.json
export FC_STATE=/Users/fc-controller/control/state
export FC_COORD=/Users/fc-controller/control/coordinator.json
export FC_BROKER=/Users/fc-controller/control/synthetic-broker.json
umask 077
mkdir -p /Users/fc-controller/control/activation-evidence
export FC_EVIDENCE=/Users/fc-controller/control/activation-evidence
```

Use bash for these snippets (`/bin/bash`); the default macOS zsh has different
`read` syntax. Do not switch away from an unresolved live controller release.
Inventory and stop existing services before changing their installed code.

### 2. Inspect STOP and broker state without initializing anything

```sh
ls -lde "$FC_STATE" "$FC_POLICY" "$FC_COORD" "$FC_BROKER"
python3 -m src.integration_control --policy "$FC_POLICY" --coordinator "$FC_COORD" --broker-config "$FC_BROKER" > "$FC_EVIDENCE/readiness.json"
test "$?" -eq 1 || exit 1
python3 -m json.tool "$FC_EVIDENCE/readiness.json"
python3 - <<'PY'
import os
from pathlib import Path
state=Path(os.environ['FC_STATE'])
print({'STOP_present_including_broken_link':os.path.lexists(state/'STOP')})
PY
```

Readiness exit 1 is expected and mandatory for this release. A missing/corrupt
ledger is unknown, never an instruction to initialize a replacement. Never use
the example's arbitrary synthetic path to evade a deployment hold.

### 3. Preserve and reconcile historical grants

Stop all known legacy controller/coordinator/worker services through their
operator-controlled service manager; retain STOP. Do not stop unrelated apps.
Take verified backups using the existing ledger-backup procedure, including WAL
where applicable; never copy a live SQLite database and assume completeness.
Run the read-only selected-ledger inventory:

```sh
python3 -m src.migration_inventory --policy "$FC_POLICY" --coordinator "$FC_COORD" --broker-config "$FC_BROKER" > "$FC_EVIDENCE/migration-inventory.json"
test "$?" -eq 1 || exit 1
python3 -m json.tool "$FC_EVIDENCE/migration-inventory.json"
shasum -a 256 "$FC_EVIDENCE/migration-inventory.json"
```

Separately inventory older Sprint 5.x ledgers, other installations, backups and
pending publication intents. For each uncertain identity, record original
evidence digest, actual service/guest inventory, external termination evidence,
publication provider reconciliation and the human disposition. Do not edit or
delete historical records or import their approvals. This command does not
complete migration: the fresh single-authority approval/claim service is missing.

### 4. Provision independent principals and verify effective isolation

An administrator manually provisions the WORKER-ISOLATION profile: controller,
two host relays, publisher and two disposable guests. Use the chosen hypervisor's
reviewed UI/configuration, retain its configuration and set external resource/
network limits. This document does not install privileged infrastructure.

Run on the Mac as administrator/operator for inspection:

```sh
id fc-controller
id fc-worker-relay
id fc-qa-relay
id fc-publisher
ls -lde /Users/fc-controller/control /Users/fc-publisher
stat -f '%Su %Sp %N' /Users/fc-controller/control /Users/fc-publisher
```

Create only non-secret sentinel files as their owning identities:

```sh
# In a real fc-controller login:
umask 077
printf 'nonsecret denial probe\n' > /Users/fc-controller/control/isolation-sentinel
# In a separate real fc-publisher login:
umask 077
printf 'nonsecret denial probe\n' > /Users/fc-publisher/isolation-sentinel
```

Run from each real worker and QA guest, and separately from each actual host
relay login:

```sh
id
mount
python3 - <<'PY'
import os
paths=['/Users/fc-controller/control/isolation-sentinel',
       '/Users/fc-publisher/isolation-sentinel']
for path in paths:
    try:
        fd=os.open(path,os.O_RDONLY)
    except OSError:
        print(path, 'not accessible; retain mount/identity evidence too')
    else:
        os.close(fd)
        raise SystemExit('FAIL: protected sentinel readable')
PY
```

Nonexistent guest paths alone are insufficient: inspect mount/integration and
all host paths, group memberships and ACLs. Test denied writes to the host
automation/application checkout without modifying their contents. Review global
readable secrets, keychain entitlements, agents and management sockets. Verify
guest egress denial against the operator's controlled IPv4/IPv6/DNS/host probes
and actual vCPU/RAM/disk/PID ceilings. Retain results from the actual Mac.

### 5. Establish safe Codex authentication

```sh
python3 - <<'PY'
from src.codex_worker import authentication_boundary
import json
print(json.dumps(authentication_boundary(),indent=2))
PY
```

Expected: blocked. Do not run personal `codex login`, copy account files, or
mount an operator home into the worker. A successful login is not a credential
separation test. Resolve the supported-relay/dedicated-identity decision in
WORKER-ISOLATION under separate review. Prove generated code cannot read its
authentication material, controller/publisher credentials or relay storage.
**Stop activation here until that software and evidence exist.** Preparation
and inert tests below remain safe.

### 6. Test worker communication with inert fixtures

```sh
python3 -m unittest discover -s tests -p test_grant_broker.py -v
PYTHONPATH=.:tests python3 tests/test_grant_broker.py --demo
```

These same-UID tests are software checks only. A provisioned real host relay must
also reject the wrong controller UID before receiving a request, authenticate its
guest hop, durably reject duplicate token/generation/request identities, and pass
the descriptor/credential sentinel tests. No production receiver is shipped.
Never pass an actual coding request merely to test communication.

### 7. Verify independent QA using inert candidates

```sh
python3 -m unittest discover -s tests -p test_activation_readiness.py -v
shasum -a 256 infra/qa-assets/direction-vectors.mjs
```

Provision the QA image separately; pin Node and the oracle from the reviewed
automation release outside candidate storage. Test the real QA peer, exact
bundle reconstruction, file/mode tampering, forbidden controller/publisher
access, deadline/STOP and whole-guest termination. Its receipt must include
controller-selected checks, the trusted oracle and candidate immutability.
The external QA client is implemented; production receiver and broker
finalization/oracle integration are missing. Local candidate tests must never run
under the privileged controller identity. No passing fixture clears this gate.

### 8. Refresh the low-risk source and review a fresh task

Run as the read-only source identity with a clean, disposable source mirror:

```sh
cd /Users/fc-reader/sources/fort-custer-server
git fetch origin main
test -z "$(git status --porcelain)" || exit 1
export FC_CANARY_SHA="$(git rev-parse origin/main)"
git show "$FC_CANARY_SHA:tools/maze-analyzer/solver.js" | head -n 1
git show "$FC_CANARY_SHA:package.json"
git diff --name-status d82c272b47486161bf9f37508b69fe3240678655 "$FC_CANARY_SHA"
```

At task inspection main was `d82c272b47486161bf9f37508b69fe3240678655`.
All 33 blobs were fetched at that commit and verified against Git blob hashes;
the full source manifest was
`1b76b0476f0cee84cefa72d93fccd4dc94f7304d85f3520beb97ee8b0dbe561a`.
The exact writable allowlist is `tools/maze-analyzer/solver.js` and
`test/analyzer.test.js`. No other writable file is authorized.

Export the newly reviewed source through trusted ingestion to the QA guest,
never share the reader checkout. From that guest's disposable export:

```sh
node --check tools/maze-analyzer/solver.js
node --check test/analyzer.test.js
node --test test/analyzer.test.js
node test/analyzer.test.js
node --input-type=module - <<'JS'
import assert from 'node:assert/strict';
import {compile,initialState,transition,directions} from './tools/maze-analyzer/solver.js';
const maze=compile(['SE']);
assert.equal(transition(maze,initialState(maze),'right').pos,1);
assert.equal(Object.isFrozen(directions.right),false);
directions.right[1]=99;
assert.equal(transition(maze,initialState(maze),'right'),null);
console.log('current vulnerability reproduced in this process only');
JS
```

If the bug is absent, source changed, checks fail or dependencies are unavailable,
stop and review a new task. The checked baseline has 14 passing analyzer tests,
including deterministic replay and client movement comparisons; no npm install
is needed. Independently select/create a matching issue and review
`examples/direction-vectors-task.review.json`. Its issue=null and review state
intentionally prevent using it as a catalog entry or coding approval.
Do not use Issue #3's historical authorization. Bind the fresh issue, current
source/full manifest, exact instructions, immutable QA/oracle digest, limits and
worker/QA identities to the future versioned broker task.

### 9. Human coding approval (blocked in this release)

Required order: review complete fresh broker task → controlling-terminal
challenge over exact task/source/policy/QA/worker/resource binding → atomic
approval record in the same authoritative database that owns claims. No legacy
approval conversion. The existing `local_runner approve` is a historical
approval, not a fresh live broker grant, and must not bridge this gap.
**No live broker approval command exists; do not approve speculative work.**

### 10. Execute exactly one worker (blocked in this release)

After all eight readiness categories have independent evidence, a separately
reviewed versioned activation implementation must require a human terminal
confirmation binding release, inventory and evidence digests. Claim exactly once
in the authoritative broker before external startup; commit receiver fencing
before any generated tool action. Retain the sole slot on any uncertain result.
**No executable activation/dispatch command exists here.** A config/env/receipt
cannot substitute for it. Never patch out `block_live_dispatch` or use an older
checkout. These missing commands are software blockers, not operator omissions.

### 11. Verify independent QA

Capture only bounded allowlisted replacement bytes and sanitized usage. Rebuild
source plus candidate in the separately provisioned QA guest. Run fixed syntax,
analyzer, diff/allowlist checks and the immutable direction-vector oracle;
verify candidate bytes/modes unchanged afterwards. Failed/unknown/exhausted or
late outcomes remain held. The operator checks exact token, generation, source,
candidate, QA request/result and external termination evidence.
Do not import worker reports or substitute same-principal local QA.

### 12. Prepare and separately approve publication

Publication requires a distinct publisher principal, protected intake, verified
base/candidate/diff/QA and a fresh controlling-terminal challenge for exact
branch/commit/title/body/draft action. Broker-to-publisher intake is not
implemented. Existing `catalog_publication` commands below support historical
local-catalog executions only; **do not rewrite/import a broker execution into
that ledger to make them accept it**. A reviewed adapter must provide the exact
new commands and independent publisher reconstruction before canary activation.
Coding/QA authorization never authorizes publication.

### 13. Review the resulting draft PR

After separately authorized publication in a future reviewed release:

```sh
read -r -p "Verified canary PR number: " FC_PR
gh pr view "$FC_PR" --repo MZKZxyz/fort-custer-server --json url,isDraft,headRefOid,baseRefName,files,autoMergeRequest,state
gh pr diff "$FC_PR" --repo MZKZxyz/fort-custer-server
```

Verify one open draft, exact reviewed head/base, the two-file scope, successful
independent QA and no auto-merge. Stop after human review. No merge/deployment
is authorized by this procedure.

### 14. Cancel, recover or revert

As controller, create sticky STOP using the existing command:

```sh
cd /Users/fc-controller/fort-custer-automation
python3 -m src.local_runner --policy "$FC_POLICY" --state "$FC_STATE" cancel
python3 -m src.integration_control --policy "$FC_POLICY" --broker-config "$FC_BROKER"
```

Administrator independently powers off/revokes both guests, confirms absence
of all descendants/storage/channel access and retains watchdog evidence.
Subscription exhaustion requires this same conservative review; do not poll
for refill, retry or enable paid fallback automatically. Preserve partial
artifacts, original ledgers, request IDs and publication provider observations.
For synthetic grants only, existing Broker.hold/recover requires exact claim
challenge and external termination-evidence digest; it never requeues identity.
No production recovery receipt/CLI exists. Never initialize another ledger to
release a hold. Keep STOP until separately reviewed reconciliation.

For a verified unmerged canary, follow the existing manual close/branch cleanup
below. An independently merged change would require a separate reviewed revert
PR; never force push or deploy. Clearing STOP is a later human-controlled
decision, not an automatic part of cancellation or recovery.

**STOP: Sprint 6.9 still cannot execute this canary.** A synthetic single-ledger broker and bounded local peer transport now exist.
Live broker migration, a credential-free model bridge, external worker/QA
isolation and publisher identity remain unimplemented/unverified. The health command always exits 1.
Do not remove the gate, mock it, use an older checkout, or approve speculative
coding to work around it. This runbook prepares a later independently reviewed
activation; it does not authorize it. No real task was executed for this sprint.

## Sprint 6.9 preparation and recovery

Read [the broker state/authority design](SPRINT-6.9.md) and
[the macOS provisioning profile](WORKER-ISOLATION.md). Synthetic grants are not
live grants and cannot be imported into old execution/publication ledgers.
The old controller and coordinator are not atomically migrated across databases.
Do not use a second broker ledger to evade an active/ambiguous claim.

Run read-only health with an explicitly protected synthetic configuration:

```sh
python3 -m src.integration_control --policy POLICY --coordinator COORDINATOR_CONFIG --broker-config BROKER_CONFIG
```

Exit 1 is required. Check the broker integrity, active/ambiguous counts, STOP,
legacy migration status, actual live capacity zero, unverified worker/QA/publisher
isolation and unsupported resource ceilings. Endpoint API availability is not
endpoint or filesystem readiness. The disabled example must remain synthetic.
There is no operational live broker command in this release.

For synthetic failure inspection use the trusted `Broker.inspect`, `hold` and
`sweep` APIs described in Sprint 6.9. A lost reply, `starting`, `checking`, STOP,
expiry or unconfirmed termination must keep the only slot occupied. Independently
terminate the endpoint/guest/descendants before operator recovery with retained
termination-evidence digest and exact challenge. Recovery permanently interrupts
the identity and never launches a replacement. Do not retry startup, transfer or
uncertain QA. Retain wire bytes, audit history and watchdog evidence.

## Suggested task and source evidence

Candidate: prevent mutation of exported maze direction vectors in
`fort-custer-server`. At observed main
`d82c272b47486161bf9f37508b69fe3240678655`, the first line of
[`tools/maze-analyzer/solver.js`](https://github.com/MZKZxyz/fort-custer-server/blob/d82c272b47486161bf9f37508b69fe3240678655/tools/maze-analyzer/solver.js)
freezes only the outer directions object. The exported nested arrays are writable.
Mutating `directions.right[1]` changes internal transition behavior for every
consumer of the module. Reproduction on a temporary copy of pinned source:

```sh
node --input-type=module - <<'JS'
import {compile, initialState, transition, directions} from './tools/maze-analyzer/solver.js';
const maze = compile(['SE']);
console.log(transition(maze, initialState(maze), 'right')?.pos);
directions.right[1] = 99;
console.log(transition(maze, initialState(maze), 'right'));
console.log(Object.isFrozen(directions), Object.isFrozen(directions.right));
JS
```

Observed: `1`, then `null`, then `true false`. This mutates only that process's
module memory. Proposed fix: freeze each of the four nested arrays and add a
regression asserting mutation is rejected and legal transitions remain correct.
No change to generator algorithms, movement semantics, authentication, database,
deployment or security policy. Exact proposed writable allowlist:

- `tools/maze-analyzer/solver.js`
- `test/analyzer.test.js`

The existing test imports `directions`, checks legal/invalid transitions,
client agreement and deterministic generator behavior.
[`package.json`](https://github.com/MZKZxyz/fort-custer-server/blob/d82c272b47486161bf9f37508b69fe3240678655/package.json)
defines `test:analyzer` as `node --test test/analyzer.test.js`. There is no dependency
installation needed for the Node built-in unit tests themselves. The complete
analyzer file also includes CLI/generator fixtures and a bounded 5,000-maze test;
verify its runtime and all referenced assets on the isolated QA image before
calling it a fast baseline. This sprint reproduced the small bug only, not the
entire application QA suite. Baseline QA remains a prerequisite.

Issue [#3](https://github.com/MZKZxyz/fort-custer-server/issues/3) was still **open**
at inspection. Its title is “Investigate deterministic maze-generation rejections
and document reproducible cases.” The prior inherited-property direction regression
is present in current tests, but does not prove that generation investigation is
complete. The proposed mutation fix is a separate small task: the operator must
create/select a matching issue and review its scope. Do not reuse Issue #3's old
authorization or claim it is resolved.

## Required Mac preparation and identities

An administrator must provision and verify all boundaries; no `sudo` setup script
is shipped. Suggested paths are examples, not existing verified installations:

| Identity | Files and capabilities |
| --- | --- |
| `fc-controller`, non-admin | `/Users/fc-controller/fort-custer-automation`, protected policy `/Users/fc-controller/control/catalog-policy.json`, state `/Users/fc-controller/control/state`; no publisher token |
| `fc-reader`, non-admin | Read-only GitHub identity, pinned source mirror `/Users/fc-reader/sources/fort-custer-server.git`; no repository writes |
| Worker VM guest `fc-worker` | Disposable source export and immutable request only; no host shares, approvals, publisher credentials or production access |
| Independent QA VM guest `fc-qa` | Fresh source plus bounded artifacts and pinned Node/test assets, no worker credentials or write tokens |
| `fc-publisher`, non-admin | Separate protected home and repository-scoped short-lived draft publication credential; approved candidate intake only |
| Administrator/watchdog | Lifecycle and resource enforcement, can terminate worker/QA VM independently of controller |

Use private homes, directories 0700, files 0600 and explicit restrictive ACLs.
Verify effective ACLs with `ls -lde PATH`, identity with `id`, and ownership with
`stat -f '%Su %Sp %N' PATH`. Separately log into each identity and verify read/write
attempts against non-secret sentinel files in protected directories are denied.
Verify the guest cannot enumerate host policy, approval, publisher or production
paths and has no shared .git checkout, host sockets, SSH agents or mounted homes.
Do not print credential files or environment values. Permission tests must run as
the real guest/user, never as a mocked Python object. No such boundary was
provisioned in the Linux implementation workspace.

A separate unprivileged Mac user can enforce filesystem permissions if ACLs,
groups and privilege escalation are reviewed. It cannot substitute for separately
verified networking, resource and descendant-process enforcement. Prefer dedicated
VMs without host integration; verify networking and independent kill controls.
Install the reviewed fixed controller outside worker-writable storage. Revoke old
runner access and stop all old controller instances before migration.

## Exact authorization sequence after prerequisites are implemented

1. Administrator inventories historical controllers/ledgers, reconciles all old
   holds and deploys the reviewed shared broker plus isolation implementation.
   No old approval becomes a broker grant implicitly. Verify no scheduling or
   multi-worker live mode is enabled.
2. Reader retrieves current issue and source. Pin a full commit, origin,
   source manifest and test assets; the SHA above is evidence, not a promise that
   future main is unchanged. Reject dirty checkout or stale base. Independently
   reproduce the problem and pass baseline QA in the isolated QA environment.
3. Operator reviews discovery evidence and writes a catalog entry with the exact
   two-file allowlist, source/manifest, explicit freeze-only instructions, fixed
   checks and short deadline. Use existing promotion prepare → inspect → terminal
   approve → export → separate terminal import. Discovery/planning grants nothing.
   Existing CLI syntax (paths and IDs must be actual protected evidence):

   ```sh
   python3 -m src.catalog_promotion --ledger PROMOTION_DB --policy POLICY --discovery DISCOVERY_DB --stop STOP_PATH prepare PROPOSAL_ID --task-id freeze-direction-vectors --reviewed-entry ENTRY_JSON --risk low
   python3 -m src.catalog_promotion --ledger PROMOTION_DB inspect PROMOTION_ID
   python3 -m src.catalog_promotion --ledger PROMOTION_DB --policy POLICY --discovery DISCOVERY_DB --stop STOP_PATH approve PROMOTION_ID
   python3 -m src.catalog_promotion --ledger PROMOTION_DB --policy POLICY --discovery DISCOVERY_DB --stop STOP_PATH apply PROMOTION_ID --export EXPORT_JSON
   python3 -m src.catalog_promotion --ledger PROMOTION_DB --policy POLICY --stop STOP_PATH import --export EXPORT_JSON
   ```

4. A separate controlling-terminal coding review binds the exact task/source/
   policy/instructions/limits to a fresh execution:

   ```sh
   python3 -m src.local_runner --policy POLICY --state STATE task-prepare freeze-direction-vectors
   python3 -m src.local_runner --policy POLICY --state STATE inspect EXECUTION_ID
   python3 -m src.local_runner --policy POLICY --state STATE approve EXECUTION_ID
   ```

   The operator types `APPROVE <exact binding>` in the terminal. Those commands
   alone are not a v2 grant. The later broker migration must specify its fresh
   authorization command; none exists in this release. Never invent a JSON flag
   or insert a row to bridge this gap.
5. Operator manually requests exactly one broker dispatch after health verifies
   every required boundary. This release deliberately supplies **no executable
   live dispatch command**. `local_runner execute` fails before consuming approval.
   Broker must atomically fence the grant before external startup; uncertain
   startup consumes/holds it and cannot be automatically retried.
6. Transfer bounded wire output under the exact token/request digest. Independent
   QA reconstructs source plus delta, ignores worker reports, verifies allowlist,
   manifests, no secret/config/path additions, and performs:
   `git diff --check`, `node --check tools/maze-analyzer/solver.js`,
   `node --check test/analyzer.test.js`,
   `node --test test/analyzer.test.js`, a reviewed mutation regression and
   post-test candidate immutability verification. Missing/failed checks block.
7. Publisher independently reconstructs and reviews exact candidate, diff, test
   receipt, base, branch, commit/tree and draft PR title/body. Use existing separate
   publication prepare → inspect → preflight → terminal approve → execute → verify,
   under isolated publisher identity with a short-lived repository-scoped credential:

   ```sh
   python3 -m src.catalog_publication --policy POLICY --state STATE prepare EXECUTION_ID
   python3 -m src.catalog_publication --policy POLICY --state STATE inspect PUBLICATION_ID
   python3 -m src.catalog_publication --policy POLICY --state STATE --credential PUBLISHER_CREDENTIAL preflight PUBLICATION_ID
   python3 -m src.catalog_publication --policy POLICY --state STATE approve PUBLICATION_ID
   python3 -m src.catalog_publication --policy POLICY --state STATE --credential PUBLISHER_CREDENTIAL execute PUBLICATION_ID
   python3 -m src.catalog_publication --policy POLICY --state STATE --credential PUBLISHER_CREDENTIAL verify PUBLICATION_ID
   ```

   Type `PUBLISH <exact binding>` only after review. These are existing manual
   publication operations, not authorized execution during this sprint. The
   future separate-identity deployment must provide protected transfer/access to
   the required state without granting the worker any access.
8. Read-only orchestration sync reconciles publication evidence and separately
   observed GitHub state. A human confirms one open draft PR, exact repository,
   base/head/candidate, no auto-merge, no merge/deployment actions. Stop here.
   A draft PR is the final canary result, not approval to merge.

## STOP, recovery and rollback

From the protected controller identity:

```sh
python3 -m src.local_runner --policy POLICY --state STATE cancel
python3 -m src.integration_control --policy POLICY --coordinator COORDINATOR_CONFIG
```

Keep STOP active. An administrator must independently stop/inspect every worker/
QA guest and descendant. Absence of a response, a passed deadline or a process
exit code is insufficient evidence of termination. Retain all ambiguous claims
and publication intents, output fragments and hashes. Use the original ledger's
terminal-reviewed recovery; never clear STOP or requeue automatically. The
recovery table in [Sprint 6.8](SPRINT-6.8.md) covers abandoned grants, startup,
transfer, QA, publication, credentials, stale base and repository conflicts.

For an unmerged canary, the application main is unchanged: after remote
reconciliation, close the draft and delete its branch manually if appropriate:

```sh
gh pr close PR_NUMBER --repo MZKZxyz/fort-custer-server
git push origin --delete REVIEWED_CANARY_BRANCH
```

Verify exact branch/PR first; do not delete an uncertain publication or main.
If a human later merged it under separate authority, prepare a reviewed revert:

```sh
git switch -c revert-freeze-direction-vectors origin/main
git revert --no-edit CANARY_COMMIT_SHA
git diff HEAD^ --check
node --test test/analyzer.test.js
```

Review and publish that revert through the normal human process; never force-push
or deploy automatically. Credential rotation requires revocation, STOP and
scope/expiry revalidation. Source drift requires new review and authorization,
not reuse of the old task or automatic rebasing.

## Readiness report

Source evidence and a small reversible candidate are available. Missing:
matching operator-reviewed issue/catalog entry; current full source export and
baseline QA; shared atomic grant migration; verified Mac identities/VM isolation;
credential-free supported model transport; external watchdog and hard scratch/
CPU/memory/network controls; isolated QA and publisher; verified GitHub credential
scope/expiry/current branch state; tested backups/recovery; separate activation
review. Subscription counters are telemetry; $10/day remains an operator goal.
No identity, credential, VM, baseline or activation is presumed ready. Stop until
these are resolved in a separately reviewed implementation and deployment.
