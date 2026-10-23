# Sprint 6.8 — supervised integration and migration boundary

This release is **not live-canary ready**. It closes the old same-account local
dispatch path. Both `Runner.execute` and direct `LocalCLI.run` reject before
claiming, materializing input, checking CLI login, or starting any subprocess.
`supervised-integration-v2-blocked` has no policy/environment/command-line override.
The coordinator continues accepting only its exact fixed synthetic worker.
The older infrastructure CodexAdapter remains blocked by its existing live gate.
No new live dispatcher, scheduler, publisher transport, merge or deployment exists.

## Authority decision

Sprint 6.7's coordinator claim and the legacy local controller approval live in
different transactions. A new lock file or a second SQLite claim would not make
them one authority. This sprint uses the explicitly permitted incompatibility
gate instead of asserting that those ledgers form a live broker. **There is no
executable v2 grant protocol yet.** Existing approvals remain readable, cancellable
historical records. They are never silently promoted to v2 grants. A failed live
attempt leaves their bytes and state unchanged.

This is a behavior change: the prior supervised same-user experiment cannot run
on this version. Do not roll back to old software to bypass this boundary.
An old process or another source checkout is outside this version's control;
before migration an administrator must stop all legacy processes, disable their
services, inventory every ledger and outstanding authorization, revoke executable
access and credentials for obsolete identities, and verify no surviving workers.
Code cannot fence a controller that still possesses independent old credentials.

Required future migration, subject to separate security review:

1. Back up all historical ledgers and hashes; inventory unresolved and ambiguous
   execution/publication attempts. Never clone ledgers to manufacture capacity.
2. Install one independently protected broker identity and durable local authority.
   Both entry points must obtain its single atomic claim. Deny direct worker start.
3. Issue fresh terminal-reviewed grants binding task, execution, source, manifest,
   policy digest, worker identity, allowed paths, instructions and limits. Preserve
   old approval bytes; link explicit migration events, never rewrite their meaning.
4. Atomically check STOP, revocation, expiry, global one-worker hold, repository
   hold and single-use grant identity; durably record fencing generation before
   startup. All starts and completions must authenticate to the broker.
5. Hold uncertain startup/termination forever until independent reconciliation.
   Expiry is cancellation intent, never proof of process death or permission to retry.
6. Deploy and verify the worker, independent QA and publisher boundaries below.
   Only then replace this unconditional gate in a separately reviewed change.

## Isolation evaluation

Separate directories, filtered environments, private SQLite, wire hashes and
Python classes are integrity mechanisms, **not security sandboxes**. The synthetic
worker is trusted in-process test code. The existing local QA runs arbitrary
candidate JavaScript under the controller UID; that is also unsuitable for hostile
live artifacts. Its deterministic reconstruction does not establish OS isolation.

Linux: an administrator-controlled unprivileged worker user plus hardened container
or VM is practical. Existing dormant Docker/runsc arguments supply useful starting
constraints: non-root UID, no capabilities, no-new-privileges, read-only root,
network none, PID/CPU/memory/fsize limits and bounded tmpfs. They are launch
specifications, not verified deployment. Do not expose the Docker socket, host PID
namespace, controller home, SSH agent, policy, ledgers, publisher credentials,
production credentials, repository .git/config or a shared writable checkout.
Use a private source export and output volume with quota, authenticated bounded
transfer, fixed image digest and separately administered watchdog/cgroup lifecycle.
Daemon access is privileged; a worker must never have it. A separate user alone
does not restrict networking or enforce disk/CPU/memory.

macOS: a distinct non-admin user with separately owned homes and restrictive ACLs
is the minimum permission separation, but does not by itself enforce every
network/resource constraint. A dedicated VM is the preferred hostile-worker
boundary. Disable shared folders, clipboard, host agents and credential forwarding;
use explicit read-only source transfer and bounded output retrieval. Run independent
QA in another disposable VM with no coding or publisher credentials. A container
inside a dedicated Linux VM is an option after validating host sharing and runtime
configuration. Same-account subprocesses and workspace-write flags are insufficient.
No new virtualization dependency is installed or claimed verified by this sprint.

The worker may access only its disposable export, reviewed request and bounded
output. Controller policy/approval storage, protected operator files, GitHub writes,
publisher identity, production services and shared mutable checkouts are forbidden.
The current implementation cannot prove those live restrictions, so dispatch fails.
Account login alone is not a safe model transport: supported credential-free
execution or an independently mediated transport remains a prerequisite.

## Worker handoff

`worker-handoff-v2-synthetic` is a wire format exercised in the synthetic
coordinator, not a live authorization or remote launch service. Canonical UTF-8
request **bytes** are retained by the controller, outside worker storage. A detached
decoded copy goes to the fixture. It binds exact task/execution/repository,
source commit/manifest, policy digest, allowed paths, reviewed prompt, resource
limits, worker identity, fencing token/generation, deadline and artifact maximum.
No policy/ledger/operator path or secret is included.

The bounded response contains only protocol, request digest, token, generation,
changed-file bytes/modes and artifact digest. Reject duplicate JSON keys, extra
fields, wrong request/token/generation, deadline expiry, unsafe/protected paths,
oversized transfer, bad modes and digest mismatch. Digests do not authenticate a
worker; transport identity must be independently provided before live integration.
The controller must check current broker ownership/revocation and STOP at
ingestion. The synthetic coordinator already guards those stages with its own
synthetic claim; that is not a migrated live grant.

Worker claims and test reports confer no trust. QA reconstructs from pinned source
plus captured delta in fresh storage, verifies the full candidate manifest and
allowlist, selects fixed checks from reviewed controller policy, then checks for
mutation. The publisher reconstructs again under its own separate approval.
New wire evidence is checked by read-only coordinator observations; historical
records without wire evidence retain their original v1 interpretation and hashes.

## Read-only operational health

```sh
python3 -m src.integration_control --policy /operator/controller/catalog-policy.json \
  --coordinator /operator/concurrency/config.json
```

Exit status is deliberately **1**, including otherwise valid evidence. The JSON
reports source HEAD and clean checkout validation, policy/catalog compatibility,
STOP (including broken symlinks), controller ledger integrity, approved-task count,
active/ambiguous holds, optional synthetic coordinator holds, Node binary validity,
unverified worker/QA/publisher isolation, unknown GitHub prerequisites and disabled
scheduling/live concurrency. Missing or contradictory evidence is unknown and
blocks. No ledger initialization, approval, login, GitHub request or dispatch occurs;
credential values and raw exceptions are never printed. Git status may inspect
the source index; no application files are modified. Counts are local observations,
not a globally atomic live snapshot. No green readiness claim can result.

Discovery/promotion/orchestration/daily planning remain manually invoked advisory
systems. Discovery evidence is untrusted input; promotion review and import do
not authorize coding. Orchestration observes evidence and never creates grants.
Daily planning does not dispatch; previous scheduling examples remain disabled.
The health command does not pretend to inspect a Mac or a GitHub identity remotely.

## Controls actually available

| Control | Current status |
| --- | --- |
| One live worker | Zero new live workers possible; future broker ceiling one |
| Synthetic concurrency | Up to three fixed trusted fixtures; no live adapter |
| Deadline/STOP | Polling, process-group QA supervisor and guardian; held uncertainty; not external hostile-worker containment |
| Artifact bytes | Bounded wire (1 MiB including encoding), capture and ingestion; coordinator configured ceiling and SQLite page limit |
| Aggregate scratch | Not hard-enforced; operator storage monitoring needed |
| CPU/memory | Not hard-enforced on local fixtures; dormant container flags only |
| Network | No live worker; no verified adversarial local restriction |
| Subscription usage | Reported token counters; incomplete metrics explicitly unavailable |
| API costs | No paid API use/fallback in this workflow; older API reservation protocol preserved |
| $10/day | Operator goal, not a hard subscription dollar cap |

The 1 MiB wire limit includes hex/JSON overhead and may be stricter than raw artifact
limits. Oversized or interrupted transfer holds the synthetic claim; it never
automatically resumes or replays. Existing $3/task API assumptions are not evidence
of a provider-enforced cost cap. CPU and peak-memory measurements remain unknown.

## Recovery and compatibility

Always set STOP first and preserve source, policy, SQLite (including WAL where
applicable), artifact hashes and process observations. Never edit historical rows
or delete a store to clear an authorization. Use the subsystem's terminal-reviewed
reconciliation procedure; no automatic side-effect retry.

| Condition | Required response |
| --- | --- |
| Abandoned grant before startup | Reconcile/cancel under original protocol, retain identity; fresh reviewed task identity only after diagnosis |
| Ambiguous startup or controller crash | Retain global/repository hold, verify all descendants stopped using external administrator/watchdog; explicit reconciliation |
| Failed/incomplete QA | Preserve failed artifact and report, no publication, independently diagnose, never accept worker test claims |
| Interrupted output transfer | Retain claim and partial bytes, verify termination, reconcile; no resume/replay authorization |
| STOP during coding | Request cancellation, verify external process/container death; keep STOP and unresolved holds |
| Publication uncertainty | Read GitHub branch/commit/PR state with publisher identity; preserve intent; no repeat write until exact reconciliation |
| Credential rotation | STOP, revoke old credentials, isolate/reprovision identities, revalidate scope/expiry, preserve audit; no credentials in artifacts |
| Stale base | Stop; fetch through read-only identity, re-review source/catalog and obtain fresh authorization; no automatic rebase |
| Repository conflict | Keep queued/held; verify canonical repository identity across controllers, serialize; do not rename repository to evade conflict |

Rollback: stop using the new commands, preserve all evidence, and revert the
automation PR only after reconciling active synthetic claims. Restoring old code
does not authorize live use or make same-account execution isolated. Application
canary rollback is separately described in the runbook.

Historical protocol schemas, state database and previous evidence files are
unchanged. Only the old dispatch behavior is deliberately blocked. Historical
protocol tests explicitly mock the new gate to run their inert generated program;
this is test instrumentation, with no production switch and no isolation claim.
See [evidence](SPRINT-6.8-EVIDENCE.md) and [canary runbook](LIVE-CANARY-RUNBOOK.md).
