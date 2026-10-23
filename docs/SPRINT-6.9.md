# Sprint 6.9 — Unified grant broker and isolated worker transport

Status: **synthetic infrastructure only; live activation remains blocked**.
Based on main `1b4959ce7e84df9e76a82b5bbf54d947675e00ca` (merged #17),
verified against GitHub's main branch on October 22, 2026 (Pacific time).

## Authority and trust boundaries

`src/grant_broker.py` implements `grant-broker-v1-synthetic`. One protected
SQLite ledger owns admission AND consumption in one `BEGIN IMMEDIATE` transaction.
Unique execution and task keys, append-only events, full synchronization and a
single active slot serialize competing controller processes. A monotonically
increasing event sequence plus random token fences every operation. The broker
binds the independent execution approval, exact catalog entry and whole catalog,
controller policy, repository/source/source manifest, allowed files, reviewed
checks, worker name, synthetic isolation profile, deadline and approved limits.
It issues no approval and accepts no caller-supplied authorization object.
Admission reads and verifies existing terminal approval from the protected
controller ledger. Explicit synthetic admission never updates that ledger.
Discovery, promotion and orchestration documents cannot be consumed as approvals.

This is NOT atomicity across the old local/coordinator databases. They remain
historical, independently writable stores. The coordinator's three-slot synthetic
experiments remain unchanged and confer no broker or live capability. The broker
allows one synthetic claim; there is no live admission implementation. Both
`Runner.execute` and `LocalCLI.run` still hit the unchanged unconditional Sprint
6.8 gate before approval consumption. `Broker.dispatch_live` also rejects, even
if the first gate were accidentally stubbed. The older service's `require_live`
gate remains unchanged. No migration, backup replacement, old-record rewrite or
historical approval conversion occurs.

Future live execution requires an exclusively deployed broker service with a
single fixed ledger, a reviewed live protocol and fresh independent approvals.
Manual and coordinator callers must use that SAME service. A Python object with
a caller-selected SQLite path is not a deployed global authority; two separate
ledgers cannot provide global exactly-once claims. This release deliberately
cannot turn either into a live execution path. Initialization is explicit,
exclusive and never automatic after state loss. No policy/environment flag can
activate live dispatch. The disabled example cannot be changed into a live mode.

## Durable lifecycle

| State | Meaning | Allowed next state |
| --- | --- | --- |
| claimed | Approval identity durably consumed before assignment/contact | starting, held |
| starting | Startup intent committed before endpoint contact; response uncertain | received, held |
| received | Exact bounded worker bytes retained for QA | checking, held |
| checking | QA intent committed before checks; never automatically replayed | validated, held |
| validated | Trusted checks passed; candidate evidence only | none |
| held | Uncertain execution/termination, cancellation, STOP or expired deadline | held, interrupted |
| interrupted | Operator attested confirmed termination; identity remains consumed | none |

All active states occupy the only slot, including expired claims. Restart only
reads evidence: no launch, replacement, reconnect, response replay or QA replay.
`starting`, `checking` and `held` are reported as ambiguous; expired/STOP-active
claims also become ambiguous. `sweep` records holds but infers no process death.
A crash after claim and before assignment still blocks every other grant.
A lost validation commit leaves `checking`; a lost successful completion response
leaves `validated`. Neither permits another dispatch. Broken STOP symlinks count
as STOP. STOP is checked before/after transitions and by the QA supervisor.
A concurrent STOP cannot undo already-started work; an external watchdog must
terminate workers and descendants. Persistent ledger/STOP protection is an OS
provisioning requirement, not a property of hashes.

`hold(claim, reason)` records operator cancellation or transport uncertainty.
Recovery requires the exact full claim, a named trusted operator, retained
termination-evidence SHA-256 and the challenge:

```
CONFIRM TERMINATED <SHA256 of canonical claim> <termination evidence SHA256>
```

Only the trusted operator API can record this attestation. A digest/string alone
is not verified process termination or a human signature. An administrator must
first inspect the endpoint/VM and descendants and retain watchdog evidence.
Recovery consumes the identity permanently; it never requeues or retries.
There is intentionally no externally callable recovery service or live CLI.

## Transport and artifact acceptance

`src/worker_transport.py` is a one-shot AF_UNIX client, not a public listener or
worker launcher. It validates socket type/owner and protected parent chain,
authenticates kernel peer UID BEFORE transmitting the immutable request, frames
both directions with a four-byte length and 1 MiB maximum, and uses a single
monotonic deadline across connect/send/receive/EOF. It rejects truncation, extra
frames, unexpected ancillary data and SCM_RIGHTS (closing received descriptors).
It never reconnects or retries. Linux uses `SO_PEERCRED`; macOS uses libc
`getpeereid`; unsupported systems fail closed. Parent directories may be owned
by root, controller or expected worker, with no ordinary group/world writes.
AF_UNIX socket ACLs/group access must be explicitly provisioned.

`IsolatedEndpoint` additionally rejects root and the controller's own UID. This
is a necessary principal check, NOT proof of filesystem, VM or network isolation.
The low-level transport permits the same UID for explicit synthetic tests; no
broker API can use it to enable live work. The deployed endpoint must authorize
the controller in the opposite direction too and persist replay/fencing state
before any future side effect. No production worker server or model bridge is
shipped; its receiver-side execution fencing is an activation prerequisite.

The existing immutable handoff protocol binds replies to exact request hash,
random token and generation. The controller retains request/response bytes as
UNTRUSTED artifacts in its private ledger. Checksums bind bytes; they do not make
worker claims truthful. Replay is rejected by the durable broker state. Captured
output must include every allowed file exactly once, and no other file. Replacement
bytes only: this version cannot create/delete files. The trusted controller reads
the exact pinned source again, checks its manifest, prohibits mode changes,
constructs the complete candidate, and runs the policy's approved checks in a
fresh checkout using the pinned Node binary and existing QA mutation checks.
Unsafe source links/file types, symlink artifact modes, executable-bit changes,
changed source, unexpected/failed checks, malformed manifests and stale tokens
block validation. Worker-selected commands/reports are never accepted.

Synthetic QA is local and is NOT an external security boundary. Candidate code
can be hostile; this path is for inert offline fixtures only. See
[worker isolation](WORKER-ISOLATION.md) for the required production QA VM.
Validated broker evidence is not imported into legacy execution/publication
ledgers. A separate publication review/adapter must be designed in activation;
no broker completion can trigger publication, push, merge or deployment.

## Readiness and reproduction

```
python3 -m src.integration_control --policy POLICY --coordinator COORDINATOR_CONFIG --broker-config BROKER_CONFIG
python3 -m unittest discover -s tests -p test_grant_broker.py -v
PYTHONPATH=.:tests python3 tests/test_grant_broker.py --demo
python3 -m unittest discover -s tests -q
```

The health command remains read-only and always exits 1. New observations include
broker schema/integrity, synthetic atomic authority, legacy migration blocked,
active/ambiguous grants, STOP, peer API availability, unverified filesystem/QA/
publisher boundaries, actual live capacity zero (policy ceiling one), and
unsupported hard CPU/memory/disk/egress controls. It never authenticates to a
worker, reads credentials or provisions isolation. Malformed/missing broker
configuration reports contradictory evidence and stays blocked.

The demo uses reviewed fixture catalog → existing terminal approval verifier →
broker → authenticated SAME-UID mock subprocess → bounded artifacts → fresh
source reconstruction and approved QA → validated candidate → explicit separate
publication review requirement. It does NOT prove a distinct OS-user boundary,
run Codex, or publish an application PR. Process races and actual process death
are exercised separately in the suite. Synthetic results are never live grants.

See [evidence](SPRINT-6.9-EVIDENCE.md) for exact validation and limitations,
[isolation provisioning](WORKER-ISOLATION.md), and the updated
[canary runbook](LIVE-CANARY-RUNBOOK.md). No activation or deployment is included.
