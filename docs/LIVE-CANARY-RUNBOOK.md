# One manually initiated development canary — preparation only

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
