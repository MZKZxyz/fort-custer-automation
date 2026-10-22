# Operator setup and remaining activation work

This is a preparation procedure. **Do not execute a live canary in Sprint 5.6.**
The project contains no supported live subscription bridge yet. Complete these
steps in a separately authorized implementation/activation phase. Account-specific
registration, consent and billing controls cannot be completed by Codex here.

1. Read all five current official references in [the authentication investigation](SPRINT-5.6-AUTH.md).
   Confirm this application's open-source/deployment eligibility and supported
   runtime. For the registered-app SIWC route, establish the required application
   registration with OpenAI; record its approved app/client identity and limitations.
   Ordinary official Codex login is a different path and does not establish SIWC
   registration. If eligibility/registration is unavailable, leave activation blocked.
2. Select and pin the documented supported runtime/version. Do not select the
   installed runtime's internal-only `chatgptAuthTokens` variant. Independently
   verify its supported authentication, refresh, revocation and remote-tool behavior.
3. In the trusted broker deployment, provision a secret manager with access restricted
   to the broker identity. Configure only the callback URI and state/PKCE/redirect
   validation required by the current official registration flow. Exact callback
   syntax, scopes and grant settings are unresolved; do not invent defaults or
   copy auth caches. Provision a supported revocation path and retention policy.
4. The human operator explicitly authorizes the registered application using the
   official consent flow, after reviewing account/workspace and requested scopes.
   The broker validates state, token provenance/audience/account/scopes/expiry and
   refresh capability. Never ask a worker or CI job to perform this login. Ordinary
   browser login by itself is not task dispatch approval.
5. Deploy the trusted broker separately from untrusted repositories and workers.
   It may hold tokens; coding and QA guests, GitHub Actions and artifact collectors
   may not. Implement/review a supported bounded remote tool channel preserving
   the VM boundary. If Codex requires local untrusted tools beside credentials,
   stop: this topology is not ready. No generic OAuth/Responses forwarding endpoint.
6. Independently test expiry, token rotation/account mismatch, remote revocation,
   cancellation, controller/broker restart and host watchdog termination. Revoke by
   cancelling/fencing the execution first, using the official app/account revocation
   mechanism, invalidating broker sessions and confirming future calls fail. Exact
   account UI/revocation endpoint must be taken from current docs, not this simulator.
7. Verify subscription-only billing controls against the actual account, including
   any preexisting paid credit balance and automatic/manual refill behavior. Inspect
   `config/execution-modes.json`: subscription selected, both modes disabled,
   `automatic_credit_purchase`, `paid_refills`, `api_billing_fallback` and
   `automatic_mode_switch` false. These values prohibit behavior; they do not prove
   account controls. Keep API keys and alternative provider credentials absent from
   subscription processes. No paid refill or purchase is authorized by this sprint.
8. Review structured exhaustion events (`usageLimitExceeded`, exhausted documented
   rate-limit windows) in the future sanitized broker audit by execution/thread/turn.
   Inspect the retained uncertain hold, stop reason and cancellation evidence.
   Never inspect tokens or raw auth/provider responses in logs. Unknown failures
   require operator investigation, not inferred quota or automatic retry.
9. Complete the server assets procedure below, VM provider/guest signature checks,
   deny-egress and credential-isolation attestations, persistent kill switch, host
   watchdog/fencing, encrypted off-host backup/restore, and legacy-state inventory.
   Do not initialize or reset the operational planning ledger.
10. Configure separate scoped GitHub Apps and authenticated dispatch, independent QA
    and publication issuers. GitHub's `main` response on 2026-10-22 reported
    `protected:false`; branch protections still require operator configuration.
    Collect gate-specific signed observation artifacts outside the checkout.
11. Run `python src/readiness.py check --mode chatgpt_subscription` and separately
    `--mode api_billing`. Both must currently exit 1 with `ready:false`. The additional
    eligibility/isolation/execution-binding/task gates cannot be cleared by booleans
    or fake harness results. A later reviewed code release and separate explicit
    task dispatch authorization are still required even after valid receipts.

## Full server QA preparation

The reviewed server is `c4f480abb309a7a4d141b20ab462552a868ef0e3`, tree
`9015875cca2b85a845f7168ba237c5935e86445c`. Issue #3 is investigation-only.
`examples/sprint-5.6-qa-assets.json` enumerates every locked npm dependency URL,
version and SHA-512 integrity, pinned Node/Python images, bcrypt 5.1.1 output,
MongoDB 8.0.16 requirement and missing evidence. It is an **inventory, not an asset
manifest or attestation**. Reproduce with
`python src/server_qa_assets.py /path/to/reviewed/package-lock.json` and verify the
recorded lock SHA against the exact source first.

In a disposable preparation VM with registry-only egress, no credentials and no
production data: populate a complete cache using the exact lockfile; fetch MongoDB
for the pinned Linux x64 image and independently verify the vendor archive checksum;
build/verify bcrypt in an equivalent pinned image, with any necessary lifecycle
scripts confined to that disposable VM. Collect the native binding and all ELF
shared libraries needed by MongoDB/bcrypt, recording ABI, image digests, toolchain
and independent provenance/checksums. Never execute downloaded binaries or npm
scripts on the broker/controller. Destroy preparation environment after export.

Have a separate reviewer independently verify every asset against lockfile/vendor
provenance and approve a complete SHA-256 manifest. A manifest produced solely by
the downloader is not independent proof. Use `server_qa.verify_assets` with the
externally reviewed source/tree-bound manifest and the build-time verifier's
separate manifest format as documented in `infra/qa-assets/README.md`. Reject
symlinks, extra/missing files and changed bytes. Verify the final QA image embeds
those exact assets; directory verification alone does not attest image contents.

Run in a fresh disposable network-isolated QA VM with the pinned runtime and
watchdog. Install offline with scripts disabled, stage the verified bcrypt binding,
probe bcrypt load/hash, then run full `node --test`, analyzer and explicit
`test/completions.test.js`, deterministic smoke, syntax, diff/protected-file checks.
The inspected completion tests spawn a new loopback `mongod` and temporary dbpath,
ignore `MONGO_URI` and clean up. Supply only `MONGOD_BINARY=/opt/mongodb/mongod`,
`NODE_ENV=test` and the existing strict guest environment. Never inject Atlas URIs,
credentials, developer HOME/npmrc or production config.

This session retrieved/inspected the lockfile and completion test through the
GitHub connector without executing server code. Assets are absent (`infra/qa-assets`
contains only README; shared download staging is empty). Docker daemon access
returned `operation not permitted`; no disposable preparation/QA VM is available.
No MongoDB archive checksum or native transitive-library manifest is verified.
The full server suite was **not run** and `server_qa`/`qa_assets` stay blocked.
The earlier subset result cannot clear them. Do not weaken isolation to run here.
