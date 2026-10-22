# Operator activation sequence

**Stop status: live execution and publication remain disabled in code.**
This package does not deploy cloud resources, create Apps/credentials, touch
production services, modify client/server repositories or reset planning state.
Commands below are for the owner to run after review. Steps explicitly marked
STOP are unresolved requirements, not switches to bypass.

## 1. Review and provision hosting (owner)

Use a dedicated supported Linux host with persistent encrypted storage for the
trusted controller, a separate VM worker host with hardware virtualization, and
separate QA identity/images. Start with 2 vCPU/4 GiB for controller and at least
4 vCPU/8 GiB for disposable workers/QA; capacity is a sizing recommendation,
not an isolation guarantee. Do not attach production networks, Atlas or Railway.
No worker receives the controller filesystem, SQLite ledger or Docker socket.

Prefer Firecracker + jailer on a dedicated KVM host, with **no guest NIC** and a
task-bound vsock channel. Pin kernel, rootfs, VMM and jailer by digest; create
fresh encrypted scratch disks; disable metadata, shared filesystems and host
devices; use independent CPU/memory/pid/deadline limits. A microVM host service
must verify the signed execution request and source/scope itself before boot.
Give the guest neither model keys nor GitHub credentials.

**STOP:** this repository supplies `UnixVMProvider`, not a complete Firecracker
host service/guest image. Select/review/deploy that service before continuation.
There is intentionally no `docker` or process fallback.

## 2. Verify the reviewed automation release (automated locally)

```sh
git checkout <reviewed-automation-commit>
make lint test
python3 -O -m unittest discover -s tests -q
python3 src/activation_rehearsal.py --evidence-dir /tmp/fc55-evidence-UNIQUE
python3 src/readiness.py check
# Expected exit status: 1. Do not change it to unblock activation.
```

On a Docker/gVisor rehearsal host, `make images rehearsal` also runs the real
container security probes and synthetic independent QA. It proves only that
specific image/runtime configuration, never the future microVM environment.

## 3. GitHub Apps and identity (owner checklist)

1. In GitHub Settings → Developer settings → GitHub Apps, create a **reader App**.
   Disable webhooks unless a separately reviewed receiver is deployed. Grant
   repository **Contents: read**, **Issues: read**, implicit Metadata: read only.
2. Create a distinct **publisher App**, granting repository **Contents: write**,
   **Pull requests: write**, implicit Metadata: read. Grant no Actions, Workflows,
   Administration, Deployments or Secrets permissions.
3. Install each App with **Only select repositories** on fort-custer-server for
   this canary. Record numeric App ID, installation ID, account owner and client
   ID. Never reuse the broad Codex connector identity as proof of these scopes.
4. Provision signing material through the owner's existing KMS/secret manager.
   Do not add private keys to this repo, build context, image or worker. Sign
   short-lived App JWTs on the trusted side. AppOperations verifies installation
   identity and exactly one repository before requesting scoped tokens.
5. For the trusted transport implement `installation`, `repositories`, `mint`,
   `revoke`: GET installation identity; paginated installation repository
   enumeration; POST `/app/installations/{id}/access_tokens` with the exact
   role permissions/repository; DELETE `/installation/token` on revocation.
   Disable redirects, bound responses and redact credentials/errors.
6. Test wrong App/installation/account, unselected repo, expanded permissions,
   expired token and remote revocation with no worker credential access. Keep
   reader/publisher identities separate even if they share a repository.
7. Provision an authenticated human issuer and independent QA issuer. Bind
   dispatch to the frozen spec; bind QA to full diff, report/candidate/tree and
   risk decisions; bind publication to candidate SHA + signed QA digest.
   Nonces are consumed transactionally. A username in JSON is not authentication.
8. Validate draft-only publication against a mock. On ambiguous pushes inspect
   exact remote SHA; on ambiguous PR POST, recover only a single matching draft.
   If absent/ambiguous, require human reconciliation; never blindly repeat POST.

**STOP:** live minting/publishing is still code-blocked. No App or key was created
by this sprint. Owner setup alone cannot enable dispatch.

## 4. Existing ledger and controller deployment (owner)

Retain the existing authoritative SQLite file and its history. If absent or
corrupt, restore a verified backup; never call initialization to recover it.
Nonempty Sprint 5.2 execution history needs a separately reviewed mapping.

```sh
sudo groupadd --system fc-operators
sudo useradd --system --no-create-home --shell /usr/sbin/nologin fc-controller
sudo usermod --append --groups fc-operators fc-controller
sudo install -d -m 0755 /opt/fort-custer /etc/fort-custer
sudo install -d -o fc-controller -g fc-controller -m 0700 /var/lib/fort-custer
```

Install this reviewed release root-owned under `/opt/fort-custer` using your
release packaging process. Do not run from an operator-writable checkout. Verify
the package/image digest against the independent review record. Existing ledger
ownership must allow only fc-controller (0600); operator access goes through
the socket, not shared ledger writes. Maintain off-host append-only audit copies.

Create a root-owned release manifest from the **reviewed** package, then compare
against review-approved digests on a separate machine before installation:

```sh
python3 - <<'PY' > /tmp/fc55-release.json
import hashlib,json,pathlib
r=pathlib.Path('/opt/fort-custer')
print(json.dumps({str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest()
 for folder in ('src','infra','config') for p in sorted((r/folder).rglob('*'))
 if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'},sort_keys=True))
PY
sudo install -m 0644 /tmp/fc55-release.json /etc/fort-custer/release.json
sudo install -m 0644 infra/controller.example.json /etc/fort-custer/controller.json
sudo install -m 0644 infra/fc55-controller.service infra/fc55-watchdog.service infra/fc55-watchdog.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/fc55-*.service /etc/systemd/system/fc55-watchdog.timer
```

Set `operator_uids` to explicitly authorized numeric OS UIDs (root for emergency
administration); use your normal audited OS login/sudo policy and the operators
group for socket access. No remote admin listener is provided. The service only
supports `status` and persistent `kill`, and startup fences orphaned executions
without releasing holds. Repeated startup does not reset history.

**STOP:** install/review the provider socket and external host fencing first.
Then the owner can run `sudo systemctl daemon-reload` and
`sudo systemctl enable --now fc55-controller.service fc55-watchdog.timer`.
These units were syntax-validated, not deployed here. Systemd runs the watchdog
independently every 5 seconds; external infrastructure must fence the worker
host if the watchdog or its provider stops. A failed watchdog is a readiness
failure, not evidence of cleanup.

## 5. VM provider and model bridge deployment (owner + implementation)

Create a root-owned Unix socket at `/run/fort-custer-vm/provider.sock`, mode 0660
and group fc-controller (0600 if root alone connects), with no writable parent directories.
The provider verifies the controller peer and execution signature independently.
`UnixVMProvider` authenticates the root peer using SO_PEERCRED; the protocol is
one bounded JSON request/response per connection. Operations: `provision`,
`inspect`, `exchange`, `terminate`, `absent`, `inventory`. No shell command, URL,
arbitrary mounts or network policy can be supplied by issue text.

Persist execution ID, original issued/deadline and VM/disk/vsock identity **before**
provision. `inspect` must return exactly the effective values in
`vm_runtime.validate_inspection`. `absent` must verify VM and disks gone, broker
transport revoked and watchdog record retained. A lost provision response still
terminates by the durable execution ID. Failed cleanup retains the financial hold.
Inventory survives controller restart and cannot renew the 2400-second deadline.

The broker's guest-facing principal must come from the task's vsock mapping or
authenticated mTLS connection. It must never be accepted from a worker-supplied
header. Only one approved execution and one request may be active; allow only
reviewed model/operation/schema, bounded inputs/outputs, no arbitrary provider
URLs/tools/background jobs. The synthetic implementation persists pending requests
before calling its provider; ambiguous requests stay fenced after restart.

**STOP:** live Codex protocol bridge, cancellable provider transport and financial
authority require separate implementation/review. `SyntheticProvider` is CI only.
Keep provider credentials solely in the separately deployed broker's secret store.
Do not start a live model service or paid request as part of this runbook.

## 6. Real server QA staging (owner in disposable preparation VM)

```sh
git clone https://github.com/MZKZxyz/fort-custer-server.git server-reviewed
git -C server-reviewed checkout --detach c4f480abb309a7a4d141b20ab462552a868ef0e3
python3 src/server_qa.py inspect server-reviewed
# Optional dependency-free subset, gVisor only; does not clear full QA:
python3 src/server_subset_qa.py server-reviewed > server-subset.json
```

Exact tree: `9015875cca2b85a845f7168ba237c5935e86445c`. Stage assets against the
pinned Node 24 image in `infra/images.lock.json`, matching architecture, libc,
OpenSSL and shared libraries. Never run dependency scripts on the controller.
Inside a disposable restricted networked preparation guest:

```sh
npm ci --ignore-scripts --no-audit --no-fund --cache /staging/npm-cache
# In the same isolated build ABI, after review of dependency lifecycle scripts:
npm rebuild bcrypt --build-from-source --offline --cache /staging/npm-cache
install -D node_modules/bcrypt/lib/binding/napi-v3/bcrypt_lib.node /staging/native/bcrypt_lib.node
```

Stage Node headers/build toolchain first for the offline native build. Fetch test
MongoDB 8.0.16 plus its official checksum in the preparation guest from
`https://fastdl.mongodb.org/linux/mongodb-linux-x86_64-ubuntu2404-8.0.16.tgz`;
verify the checksum **and** ABI/shared libraries in the pinned QA image. A binary
for Ubuntu 24.04 must not be assumed compatible with Debian bookworm. Prefer an
independently verified compatible build or a separately reviewed QA base if
needed; do not silently swap images. Stage only `mongod`, never Atlas credentials.
This environment received HTTP 403 for that URL; request supported network access
or supply an independently verified artifact. Do not bypass destination policy.

Create and independently review a manifest with `source`, `tree`, `files` mapping
each staged relative file to SHA-256. Pin its digest in the review record. Use
`python3 src/server_qa.py verify-assets /staging reviewed-assets.json`. Include all
npm cache objects, bcrypt binary and library dependencies. Keep the older
`infra/verify_assets.py` complete manifest for image build, including empty browser
directory if not needed by the server. Place reviewed assets under
`infra/qa-assets/` only in the local build context; do not commit binary caches.

Build with `python3 src/infrastructure.py build-node-qa`. Inspect the immutable
image ID and contents against the reviewed asset manifest. Run
`python3 src/server_qa.py run server-reviewed --image sha256:REVIEWED_IMAGE_ID --assets /staging --reviewed-manifest reviewed-assets.json`.
This exports a fresh exact tree, installs locked deps offline with scripts
disabled, loads the staged native bcrypt binding, runs full `node --test`, explicit
analyzer and completion integration tests, deterministic smoke and JS syntax.
The integration test creates its own loopback MongoDB and temporary data directory.
Retain exact commands/exit statuses, output hashes, image/runtime IDs and source/tree.
Inspect the full candidate diff/protected paths through IndependentQA separately.
**STOP on missing assets, skipped tests or incompatible native dependencies.**

## 7. Financial safeguards (owner + independent reviewer)

First choose the explicit profile in `config/execution-modes.json`. The intended
initial profile is `chatgpt_subscription`; both modes remain disabled. Audit each:

```sh
python3 src/readiness.py check --mode chatgpt_subscription
python3 src/readiness.py check --mode api_billing
# Both exit 1. These commands do not log in, buy usage or invoke a model.
```

For **chatgpt_subscription**, read `SUBSCRIPTION-EVIDENCE.md`. Official
browser/device login and headless execution exist for suitable accounts/trusted
runners; the SDK is not a subscription proxy. Future owner setup must use official
Codex-managed sign-in on a separately reviewed trusted runner. Do not log in as part
of this sprint. Do not copy auth caches to coding/QA environments or extract/forward
tokens to the custom broker. Verify account/workspace eligibility and no-paid-credit
controls through supported product interfaces; none have been verified here.

On a future supported collector, structured exhaustion or exhausted quota windows
stop execution; CLI failures stop as unknown. Preserve accounting/termination
evidence, cancel/revoke execution and require operator review. Never automatically
buy credits, use paid refills or earned resets, retry after a quota reset, send
credit-nudge emails, switch to API billing or choose another provider. Unknown quota
does not permit dispatch. Usage limits are not guaranteed per-task cutoffs; an
existing credit balance may invalidate a subscription-only guarantee.

**STOP:** the credential-free worker/custom-broker design has no reviewed official
subscription integration. Keep `subscription_transport` blocked after owner login.
The synthetic rehearsal proves no real entitlement. Do not clear existing holds or
convert them to $0 subscription settlements.

For **api_billing**, separately enabled API billing/trusted broker credentials need
a distinct future review. The original dollar policy below continues in full; it
does not claim that subscription quotas enforce financial caps:

Read `BUDGET-EVIDENCE.md`. Preserve $10/day, $3/task, one live agent, 40 minutes,
two retries, no automatic merge/deployment. Configure provider project restrictions
and alerts as defense in depth; monthly limits with overshoot are insufficient.
Obtain an enforceable bound and authoritative finality/attribution, including
cross-midnight holds and delayed invoices. Do not release holds from token counts
or estimates. **STOP:** no qualifying guarantee/reconciler has been established.

## 8. Backup and recovery (owner)

Provision an age recipient and separate restore identity through existing secret
management; keep restore private material off the controller. Install reviewed
age on the host. With the authoritative ledger online, SQLite's backup API creates
a consistent snapshot including WAL state:

```sh
python3 src/ledger_backup.py backup /var/lib/fort-custer/planning.db /backup/UNIQUE.db.age --recipient OWNER_PUBLIC_RECIPIENT
# On the separate recovery host, never over the original ledger:
python3 src/ledger_backup.py restore /backup/UNIQUE.db.age /recovery/UNIQUE.db --identity /secure/owner-identity
```

Compare `logical_sha256` and every row count with the backup record. Test wrong
key, modified ciphertext, abrupt backup interruption and unused-target enforcement.
Stop admission, terminate/reconcile VM inventory and restore to a new ledger path
only after independent approval. Never discard outstanding holds, append-only audit
rows, publication outbox or planning history. Boot recovery fences orphaned runs;
it does not infer termination, financial finality or successful publication.
Local encryption/restore and tampered-ciphertext rejection passed with age v1.2.1
and public upstream test vectors. **STOP:** a separate-host operator restore and
real secret-store integration remain unverified.

## 9. Readiness and first dispatch (owner after future activation release)

Install independent collector Ed25519 public keys and their pinned hashes in a
root-owned `/etc/fort-custer/readiness-trust.json`, mapping each gate ID to
`public_key` and `key_sha256`. No checkout-owned trust roots are accepted.
Collectors sign canonical receipt payloads with: gate, exact `context` from the
readiness report, exact policy, `synthetic:false`, issued/expires (at most one day),
and every required observation pointing to a nonempty hashed artifact beneath
the evidence directory's `artifacts/`. Store base64 Ed25519 signatures beside
payloads as `GATE.json`. Retain raw probes; never sign manually edited booleans.

```sh
python3 src/readiness.py check --trust /etc/fort-custer/readiness-trust.json --evidence /var/lib/fort-custer-readiness
```

Sprint 5.5 always exits 1 because activation is intentionally blocked. There is
no force flag. Only a separately reviewed future release may change that gate.
The frozen canary is `config/canary-target.json`: issue #3, exact commit/tree,
investigation/reproduction and two documentation files only. New tests/files or
a new source SHA need a new reviewed scope. Production API, auth, migration,
generator and deployment changes remain forbidden. Dispatch needs explicit
authorization after merge; publishing a draft needs a distinct later approval.

## 10. Emergency shutdown and costs (owner)

```sh
sudo python3 /opt/fort-custer/src/controller_service.py kill
sudo systemctl start fc55-watchdog.service
sudo python3 /opt/fort-custer/src/controller_service.py status
```

If controller/socket/provider/watchdog is unavailable, use the independently
provisioned host fencing control to stop the worker host and revoke broker/App
authority. Preserve ledger and disk evidence. Verify VM/disk absence before
marking termination; never refund uncertain spending. There is no automatic
unkill/reset operation.

Planning allowance (not a vendor quote): dedicated controller, worker/QA capacity,
encrypted backups and monitoring may cost roughly $30–150/month depending on
region, uptime and virtualization requirements. Obtain actual host/storage/egress
quotes before provisioning. Rehearsals here make no paid model calls. Future model
spend must remain at most $10/day and $3/task only after the required enforceable
guarantee exists; do not represent that policy as a proven provider billing cap.
