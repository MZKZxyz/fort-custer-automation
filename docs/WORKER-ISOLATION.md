# Worker isolation deployment profile

**Reference topology only. Not provisioned or proven by this sprint.**
A different directory, Python module, JSON UID, environment allowlist or Unix
peer UID is not a sandbox. The current implementation has no live worker launcher.

## macOS reference topology

| Principal/boundary | Input and storage | Explicit exclusions |
| --- | --- | --- |
| Non-admin `fc-controller` host user | Protected policy, approvals and sole broker DB; immutable reviewed source export | No publisher credential; worker cannot read home/state |
| Non-admin `fc-worker` disposable VM guest | Credential-free home, read-only exact source image, disposable bounded writable workspace | No host homes/shares, controller DB/policy, Git write remote, agents, tokens, clipboard or integration sockets |
| Non-admin `fc-qa` separate disposable VM | Independently reconstructed exact source/candidate; pinned Node and reviewed test assets | No worker disks, controller state, publication credential or network |
| Non-admin `fc-publisher` host/VM user | Human-reviewed candidate and QA evidence through protected intake | No automatic dispatch; separate short-lived scoped publication identity |
| Administrator/watchdog | Provisioning and VM lifecycle, network/disk limits, evidence storage | No model-controlled lifecycle/recovery |

A host Unix socket directly authenticates a local host OS principal. A guest UID
is NOT a host kernel peer credential. For a VM, an administrator-provisioned
credential-free local relay principal must own the AF_UNIX endpoint and convey
only immutable source/task and bounded artifacts over a separately authenticated
VM channel. The relay has no controller/publisher access. Its guest channel,
receiver replay ledger, task/source image verification and independent watchdog
are NOT implemented/tested here. Do not expose a public port. A VM/container
profile requires a separate reviewed adapter before activation; do not point
`IsolatedEndpoint` at an unauthenticated forwarding socket and call the guest
identity proven.

A host-only alternative uses a separate non-admin macOS account with dedicated
home and isolated source/work directories. Private directories 0700, files 0600,
reviewed groups and ACLs can protect controller/publisher state. The socket's
parent can be root- or worker-owned without group/world write permission; use
explicit directory traversal and socket ACLs/group permission for the controller.
Use canonical paths without symlink ancestors (for example macOS
`/private/var/...` rather than `/var/...`). No shared writable Git repository
or operator directory is permitted. Snapshot
or copy source into worker-owned storage; only the controller's independently
verified export is authoritative. A malicious worker can lie about its local
checkout; trusted reconstruction must never rely on its repository.

That account alone does NOT enforce comprehensive filesystem denial, no egress,
resource limits or descendant termination. It must not have admin/sudo rights,
publisher/reader group membership, readable global secrets, or access to Docker/
VM management sockets. Never interpret an account name in JSON as provisioning.

## Administrator provisioning and evidence

1. Freeze legacy live entrypoints, stop old controllers and inventory every
   historical active/ambiguous grant. Keep original ledgers and backups intact.
   Resolve uncertainty with retained termination evidence. Select one service-owned
   broker path; reject arbitrary paths from manual/coordinator callers. Do not
   initialize a new ledger to clear an occupied slot or recover lost state.
2. Provision distinct controller, relay/worker, QA and publisher principals with
   private homes, explicit groups/ACLs and no elevation. Review ownership using
   `id`, `ls -lde` and `stat -f '%Su %Sp %N'`. Run actual denial probes as each
   principal against non-secret sentinel files in controller/publisher locations.
   Record effective ACLs and results, never secret content.
3. Launch a fixed, reviewed worker/relay executable under the actual principal
   from administrator-owned storage. Clear inherited environment, including
   agents, cloud/GitHub/model tokens and host tool configuration. Pass only the
   deliberate IPC descriptors and stdio; close all other inherited descriptors.
   Use no shared .git, host home, SSH agent, keychain access, Docker socket or
   arbitrary host mount. A clean env/FD set is hygiene, not filesystem isolation.
4. Authenticate local peers with real `getpeereid` on macOS or `SO_PEERCRED` on
   Linux. Reject expected UID zero or controller UID. Prove wrong-identity
   rejection before request bytes leave the controller. Verify socket path,
   ownership, parent ACLs and maximum frame/deadline/EOF behavior. Kernel UID
   authenticates principal only; malicious code under that UID remains untrusted.
5. Independently authenticate any guest channel and pin the read-only source image
   to exact repository, commit and manifest. Reject automatic source fetching,
   rebasing, shell commands or extra request fields selected by the worker.
6. For network denial, disable VM networking/host integration using the selected
   hypervisor's enforced controls and run guest egress denial probes (IPv4/IPv6,
   DNS and host/local endpoints). For host-only accounts, a username/env variable
   is no egress control; administrator firewall rules and their limitations need
   actual verification. No PF or hypervisor automation is included here.
7. Enforce VM vCPU/RAM and bounded disk outside the guest and test limits. CPU time,
   wall time and memory ceilings differ. macOS `setrlimit`, process timeouts and
   subscription telemetry do not prove hard RAM/disk/egress/spend limits. The
   transport's deadline limits controller waiting, not worker lifetime.
8. Provision QA independently from the worker with no credentials and a fresh
   reconstruction. Pin executable/test assets, prohibit network, enforce output
   and process limits, and verify the candidate remains byte/mode-identical after
   tests. Candidate Node code must not run under a privileged controller in live
   operation. The current reused local QA path is synthetic only.
9. Test external watchdog termination of worker AND QA guests/descendants during
   startup, transfer, checks and controller death. Archive termination evidence.
   Missing response/deadline/PID exit alone cannot release capacity. Operator
   attestation must refer to real evidence; hashes are not a termination oracle.
10. Exercise broker backup/restore without replay, endpoint persistence/fencing,
    STOP races and publisher separation on the target Mac. Obtain separate
    activation review. This release has no configuration override to activate.

## What is verified versus unverified

| Control | This sprint |
| --- | --- |
| Single-ledger claim race, durable intents and fencing | Linux synthetic process tests |
| Bounded framing, kernel peer authentication, descriptor rejection | Linux local socket tests; macOS CI job supplied |
| Mock environment/FD minimization | Same-UID subprocess fixture checked against sentinels |
| Distinct-principal refusal | API refuses same UID/root; actual cross-user deployment unproven |
| Host policy/approval/publisher filesystem denial | Unprovisioned; requires real-principal probes |
| macOS peer auth and sandbox deployment | CI configured; no macOS result claimed from Linux |
| VM guest channel and receiver execution replay protection | Not implemented; activation blocker |
| External independent QA | Not provisioned; local inert synthetic QA only |
| Hard CPU/RAM/disk/network ceilings and external kill | Unverified; unsupported by this Python transport |
| Live capacity | Zero; future approved ceiling one |

Do not activate if a required control cannot be measured. The fail-closed
architecture is the delivered boundary until those prerequisites are reviewed.
