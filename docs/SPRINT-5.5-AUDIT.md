# Sprint 5.5 operational audit

The intended initial execution mode is now `chatgpt_subscription`; `api_billing`
is separate. Both are disabled. See [subscription evidence](SUBSCRIPTION-EVIDENCE.md).
Readiness reports 17 blocked mandatory gates for subscription mode and 15 for API
mode. API dollar-cap/broker gates are explicitly not applicable to subscription
mode, rather than falsely satisfied. Subscription login/entitlement, no-paid-usage
controls, exhaustion handling and supported credential-isolated transport remain
mandatory. Receipts bind the selected mode and full configuration digest; evidence
for one mode cannot clear the other. The shared live gate cannot be cleared by either.

Baseline: automation `bfbc4785d6e5d2e86f7fd70590cff6735f75062f`, tree
`40d75218a7d56087796939683302f9d91a5505c9`. Audited 2026-10-22.
This is a partially implemented activation package. **Sprint 5.6 live execution
cannot proceed.** Neither configuration nor a signed readiness receipt enables it.

## Existing controls reviewed

Sprint 5.1 (`issues.py`, `planning.py`, daily workflow) has read-only ingestion,
immutable daily planning and persistent reservations. The planner's three advisory
slots are not three live agents. Sprint 5.2 (`execution.py`, `simulate.py`) adds
simulation and independent checks; nonempty legacy execution history still needs
a reviewed migration mapping before controller takeover.

Sprint 5.3 (`secure_ledger.py`, `trust.py`, `independent_qa.py`, `publication.py`)
enforces transactional approvals, one live execution, $3 task holds, $10 daily
accounting, two retries, a nonrenewable 40-minute deadline, exact-SHA independent
QA and a durable draft-only publication outbox. Holds survive uncertainty and
cross-midnight accounting. `require_live()` blocks dispatch and publication.

Sprint 5.4 (`infrastructure.py`, `worker_entry.py`, watchdog, image/runtime locks)
adds inspected gVisor container rehearsals, independent QA images and permission
contracts. These are not production VM attestations. The App token broker is a
stub; CodexAdapter does not implement a credential-free live model channel.

## Remaining activation blockers

| ID | Classification | Implementation/evidence still required |
|---|---|---|
| controller | Infrastructure deployment required | Install reviewed root-owned immutable release, persistent existing ledger, authenticated identities; collect service/permission/configuration and crash recovery evidence. No host was deployed. |
| backup_restore | Independent security verification required | Run age-encrypted backup and restore on a separate host using operator-provisioned recipient/identity; compare logical contents and row counts, test wrong key and retain external audit copies. Local encrypted restore and ciphertext-tamper rejection passed using published upstream test vectors; off-host deployment remains unverified. |
| worker | Infrastructure deployment required | Select and deploy a disposable microVM provider implementing the bounded Unix protocol; independently verify guest request signatures, deny egress, no host mounts/credentials, original deadline and cleanup. SyntheticVMProvider runs no VM. |
| provider implementation | Software implementation required | Supply/review the host-side microVM service and guest vsock bridge behind UnixVMProvider. No Firecracker guest image, jailer service or production adapter is included. No fallback is permitted. |
| watchdog | Independent security verification required | Prove host timer works through controller crash; verify provider persistent inventory and external host fencing when watchdog/provider fails. A timer alone cannot survive host failure. |
| broker | Software implementation required | Deploy reviewed vsock/mTLS principal derivation, Codex protocol translation and cancellable bounded provider transport. Current broker is synthetic-only and rejects non-synthetic providers. Every provider access route must go through this service. |
| billing | Provider capability or billing guarantee required | Obtain a strict enforceable $10/Los Angeles day and $3/task bound covering concurrent/in-flight/failed/delayed charges and authoritative final cost attribution; implement reviewed financial reconciler. Current documented monthly controls allow delayed enforcement/overshoot. |
| server_qa | Independent security verification required | Stage exact locked npm cache, native bcrypt binding, matching ABI/shared libraries and test MongoDB; run full node --test plus explicit completion integration in fresh isolated QA. Dependency-free subset cannot clear this gate. |
| github_apps | Operator credential/configuration required | Create/install separate reader/publisher Apps only on the target repo; provision KMS signer, verify App/installation/account identity, scoped token lifecycle, expiry, remote revocation and ambiguous API recovery. AppOperations validates a synthetic transport only; live mint remains blocked. |
| approvals | Operator credential/configuration required | Provision distinct authenticated operator and independent QA issuers. OS-peer admin identity is available locally; it is not a remote approval issuer. No self-declared username/header is trusted. |
| security_review | Independent security verification required | Independent review of controller, host, microVM, model bridge, financial proof, approvals, secret boundaries and publication. Install externally protected public verification roots and collector-produced observation artifacts. |
| legacy state | Operator credential/configuration required | Review authoritative ledger inventory and any 5.2 execution migration mapping. Never initialize/reset to bypass missing history, holds or corruption. |
| activation_release | Software implementation required | Merge/review this PR, resolve all above, then separately authorize/review a future activation release. Preserve a separate dispatch approval and a separate draft publication approval. |

`python3 src/readiness.py check --mode chatgpt_subscription` (or `--mode api_billing`)
emits the machine-readable gate manifest and
exits **1**. It checks gate-specific Ed25519 receipts against external root-owned
trust paths, fixed policy, reviewed source/tree, current software digests, expiry
and complete artifact hashes. No `passed: true` field is recognized. The independent
collector must run the actual probes listed in `GATES`; signing a manual claim
does not verify an environment. Receipt verification authenticates that collector's
observations; it does not replace independent inspection or the blocked code gate.

## Evidence boundaries

The offline control-plane rehearsal uses the existing signed synthetic dispatch,
fresh-checkout independent QA, signed QA/publication approval and mock GitHub
publication. It adds broker admission and usage provenance, VM lifecycle contract
checks, revocation and persistent evidence exports. `--evidence-dir` must name a
new directory; it preserves the synthetic ledger, broker DB, candidate Git mirror
and report. It never accesses the operational ledger.

Automated regressions reject forged/missing readiness, untrusted approvals,
expired/revoked tokens, changed policy, network drift, stale artifacts, missing
assets, process/controller crashes, failed cleanup, failed watchdog, unauthorized
publication and ambiguous GitHub responses. Actual microVM deployment, off-host
restore and full real server integration remain unverified. Local age v1.2.1
encryption/restore and tamper rejection were tested using public upstream fixture
material; no operational key was generated.

See `examples/sprint-5.5-validation.json` for exact commands and observed results.
