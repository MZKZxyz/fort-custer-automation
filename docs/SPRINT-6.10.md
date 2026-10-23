# Sprint 6.10 — Single-worker activation preparation

**Status: fail-closed delivery; software integration is incomplete and live
activation is blocked.** Base: merged #18, exact main commit
`f78728cfd7f2649f27a172c5e3ab4a4978fbc81b`.

This release does not claim a working real Codex worker, production QA service,
completed broker migration, or verified Mac deployment. It supplies reviewable
source/QA handoffs, durable synthetic exhaustion handling, read-only migration
inventory, an independent regression oracle, and a Mac preparation procedure.
The user's permitted fallback applies: safe live migration and personal-account
credential isolation could not be demonstrated, so dispatch stays blocked.

## Implementation and authority review

| Component | Finding and resulting boundary |
| --- | --- |
| grant_broker | One synthetic SQLite authority, exclusive initialization, atomic consumption, durable startup/QA intents, single occupied slot including ambiguity, token/generation fencing; no live claim API |
| worker_transport | Bounded one-shot AF_UNIX, Linux SO_PEERCRED / Mac getpeereid, close-on-exec, descriptor rejection, peer check before request; no VM authentication or filesystem isolation proof |
| worker_handoff | Exact task/source/policy/instructions/worker/token binding; replacement bytes only; no worker QA or executable command selection |
| local_runner / LocalCLI | Both hit unchanged unconditional Sprint 6.8 gate before live work; dormant operator-home authentication is unsafe to revive without credential separation |
| concurrency_coordinator | Synthetic independent ledger retained; explicit live-dispatch refusal added; synthetic slots do not authorize live workers |
| integration_control | Eight distinct prerequisite states added; no evidence import, enable flag or environment override; always exits 1 |
| independent_qa / local Runner.qa | Historical implementation reconstructs exact candidate, but local candidate tests execute as caller; it is not safe production QA under controller identity |
| catalog_publication | Separate controlling-terminal publication approval and exact reconstruction; existing publisher accepts only historical local-catalog validated evidence; broker receipts cannot be imported |
| STOP / audit / secure_ledger / watchdog | Existing sticky STOP, append-only history, held ambiguity and separate historical gates retained; generic watchdog adapters do not constitute an installed Mac hypervisor watchdog |

No older evidence files or operational databases were rewritten. Synthetic v1
grants remain synthetic. New optional usage fields preserve older broker events.
Preparation APIs do not change broker schema, consume another approval, contact
an endpoint or change an execution state.

## Migration barrier and required design

`src/migration_inventory.py` reads selected protected local/coordinator/broker
ledgers and emits execution IDs, evidence digests and termination-review flags.
It does not certify inventory completeness or a simultaneous snapshot. Unknown,
failed and interrupted historical local executions conservatively need review;
active synthetic broker/coordinator holds need termination review too. Separate
installations, old Sprint 5.x ledgers, backups and publication ambiguities require
operator inventory. The tool cannot discover every installed controller.

No historical execution was available to reconcile in this workspace. Do not
replace that missing evidence with synthetic fixtures or a generated attestation.
Real reconciliation remains an operator requirement. Preserve original ledgers,
write the reviewed disposition and external termination evidence separately, and
never silently convert old approvals.

The future migration must stop/revoke every legacy writer, protect one fixed
service-owned broker path, and introduce a versioned fresh approval whose
preparation, controlling-terminal approval and claim all reside in that same
SQLite authority. It must bind source, whole policy/catalog, instructions, QA,
worker/QA principals, resource profile and reconciliation inventory. Manual and
coordinator callers must use the same service, with receiver-side durable fences
before launch. Old SQLite commits cannot be made atomic by timing them together.
Until independently reviewed and implemented, there is no authoritative live
route and **every live route is blocked**. This is the explicit migration fallback,
not a claim that acceptance criteria 1–4 are fully met.

## Source and QA integration

`Broker.prepare_worker_synthetic` returns a bounded immutable package containing
the exact approved handoff and a complete source export, without Git metadata,
controller paths, policy, credentials or approval history. HEAD drift and policy
drift fail. A 1 MiB transport ceiling also limits encoded source packages; large
repositories fail closed rather than receiving a partial export.

After durable startup and captured output, `prepare_qa_synthetic` reconstructs
the candidate from the retained source and captured replacement bytes. It binds
the fixed controller-selected checks and manifests, rejects missing/extra files
and mode changes, and executes no candidate process. `unpack_qa` performs the
same reconstruction on the QA side, with a narrow Node check/test grammar.
Symlinks, unsafe paths, noncanonical bytes, permission changes and unexpected
fields fail. No worker-supplied report is accepted.

`IsolatedQA` is the controller's external QA client. It requires the existing
kernel-authenticated endpoint type and a QA UID distinct from controller, worker
and root. It checks the caller's STOP/fence guard before and after IPC and accepts
only an exact successful request-bound receipt. This is a handoff client, not an
installed production service. The caller still needs a durable QA intent before
contact; no production broker finalization/import is provided in this release.
On lost replies or cancellation, keep the grant held and terminate the guest.
Do not call the old local QA implementation from a live controller.

The QA VM service must authenticate the controller in the reverse direction,
persist each request/fence before execution, pin Node and trusted test assets,
reconstruct in an empty disposable workspace, run only reviewed commands,
supervise deadlines/output, kill descendants externally and verify post-test
byte/mode immutability. It must reject duplicate requests after restart.
Those service and VM deployment requirements are outstanding.

The canary additionally requires the automation-owned
`infra/qa-assets/direction-vectors.mjs` oracle, installed outside candidate
storage. Candidate tests alone cannot be the oracle because the two-file
allowlist includes the test file. The generic handoff's Node grammar does not
yet integrate this external oracle; a reviewed QA-service version must bind its
digest/command/result before this canary can pass activation.

## Codex authentication and resources

`src/codex_worker.py` reports the unsupported authentication boundary and blocks
real execution before subprocesses or transport. It parses bounded candidate CLI
JSONL into sanitized usage only. This parser is exercised with controlled
fixtures; live CLI error-schema compatibility is not established. Structured
`usageLimitExceeded` is a first-class
`subscription-exhausted` state; free-text diagnostics never prove exhaustion.
Unknown/auth/partial/protocol failure is `unknown`. Neither state retries.
`Broker.capture_codex_synthetic` durably holds that identity and its only slot;
successful synthetic telemetry is retained with captured bytes. Raw CLI
messages/diagnostics are not stored. Telemetry remains untrusted and is neither
termination evidence nor a dollar meter.

See WORKER-ISOLATION for the credential conclusion and alternatives. Existing
CLI/account files must not be copied or mounted into an untrusted worker.
Nothing here implements a supported subscription OAuth relay. The internal
external-token schema variant is not a supported alternative.

Implemented software limits: one synthetic active/ambiguous grant, absolute
deadlines, request/output/manifest/file-count ceilings and the existing
process-group supervisor/guardian. Process-group killing does not contain a
hostile child that calls setsid, and a transport timeout cannot stop a VM.
Hard vCPU, RAM, disk, egress, PID and whole-guest termination require external
enforcement. No $10/day monetary cap, refill schedule, paid retry or API fallback
is claimed or enabled.

## Acceptance disposition

Offline safety integration and regression verification are reviewable. The
target canary baseline/vulnerability are revalidated, with a review-only fresh
task definition. No unattended coding, publication, merging or deployment is
enabled. Remaining blockers include real historical reconciliation, single live
authority migration, credential-isolating Codex transport, receiver fences,
production QA service/oracle integration, actual Mac isolation/resource probes,
publisher intake separation, backup recovery and separately reviewed activation.
See the evidence file and runbook for observed results and exact stop points.
