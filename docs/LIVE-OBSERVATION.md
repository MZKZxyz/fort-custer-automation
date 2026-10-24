# Supervised live observation — Sprint 6.13B

This implementation permits one advisory classification for an independently
approved task. It remains disabled in the example configuration. Only the operator
may initiate the canary, separately after review and merge. No implementation or
CI command sends a real request. Historical synthetic broker, coding, publication
and budget records are preserved; there is no grant migration.

## Admission and accounting

`ObservationBroker` in `src/live_observation.py` extends the unified broker's
protected append-only transaction contract with a distinct
`grant-broker-v2-live-observation` protocol and a new ledger. It verifies an existing
independently approved catalog task through the existing authorization verifier.
Coding approval is a prerequisite for source review, never inference permission.
The observation grant separately binds the task, full reviewed authorization,
immutable source manifest, prompt digest, pinned model/pricing, maximum cost,
principal, execution and random claim identity. Approval uses the existing
controlling-terminal helper with a digest-specific challenge. There is no approval
response option, environment bypass or piped-input path. The grant expires after
15 minutes or the underlying review expiry, whichever comes first. Revocation,
STOP, source/policy/approval change, expiry or principal mismatch blocks delivery.

The protocol has only `authorized -> dispatched` and revocation transitions. A
committed `dispatched` intent is single use, including after restart, rejected
output, exhausted budget or a crash before sending. No recovery operation permits
redispatch. Existing synthetic ledgers are rejected, and observation claims have
no worker, QA or publication admission. Budget reservation follows committed
admission and precedes the network attempt. Separate ledgers deliberately fail
closed: a crash between writes can consume a grant without making a request.

The planner keeps `observation-decision-v1` and its four exact disposition/reason
pairs. Trusted code supplies provenance, including the observation authorization
digest. Task text is a bounded untrusted JSON member, separate from fixed policy.
It cannot supply tools, provenance or approval. Source files, prompts, reasoning,
provider IDs and credentials are never returned in receipts. CLI review prints
the exact task and digests, not the serialized model prompt. Decisions stay in
memory; the budget retains sanitized usage and binding digests only. The
protected observation ledger retains the exact reviewed task/authorization and
claim, never the serialized model prompt or provider output.

The controller privately reads the key in its existing helper. The request has
`tools=[]`, `tool_choice=none`, `store=false`, `background=false`, `stream=false`,
no parallel tools and disabled truncation. It uses `gpt-5-nano-2025-08-07`, at most
2,048 UTF-8 input bytes (task at most 1,024 bytes), and 512 output tokens with
minimal reasoning. This is a separate reviewed request profile, leaving the
256-token connectivity and 64-token synthetic profiles unchanged. It reuses the
production response validator and projection rules for unfamiliar top-level
metadata. There is no tool execution, application write, shell or publication
receiver. Trusted Git calls only inspect the approved immutable source.

The reservation is **20,204,800 nano-USD ($0.0202048)**: full 400,000-token context
at 50 nano-USD/input token plus 512 output tokens at 400 nano-USD/token. This
conservatively exceeds the tiny actual input. The existing $10 daily, $100 lifetime,
one-unresolved-request and pricing-version checks remain. Use the **existing**
controller budget ledger so past spend and holds remain effective. No second
budget initialization is part of this procedure. The earlier 8,500 nano-USD
connectivity result does not predict observation cost.

Validated usage is settled before classification parsing and post-response
authorization checks. Missing visible text, incomplete output, refusal or invalid
classification can therefore be billed without delivery. Unvalidated envelopes,
unexpected tools, malformed usage, HTTP errors or transport ambiguity retain the
full durable hold and sanitized failure evidence. Never retry. Manual billing
reconciliation follows the existing [controller recovery procedure](API-CONTROLLER.md#recovery)
and cannot make the observation claim reusable.

## Exact Mac operator procedure

Run `/bin/bash` on the Mac as the existing trusted controller account, from the
reviewed merged checkout. The CLI binds the principal to that OS account.
Use existing protected paths; all configuration/ledger parents must be owned and
non-writable by other users and all configuration/ledger files private (0600).
Do not change application source, initialize another budget, run connectivity,
start workers/QA, or publish anything for this canary.

1. Identify **one already independently approved, low-risk catalog task** and its
   existing execution ID from the operator's review records. Prefer the existing
   Fort Custer task already reviewed on this Mac. This checkout contains no
   operational approval ledger, so this document cannot assert an execution ID
   is approved. The direction-vector example is explicitly *not* an approval;
   do not create/approve a new coding task just to satisfy this procedure. If the
   selected review/source has expired or changed, stop. No automatic refresh.
2. Set these local values to the actual existing protected files and exact IDs:

   ```sh
   cd /Users/fc-controller/fort-custer-automation
   FC_OBS_BROKER=/Users/fc-controller/control/live-observation.json
   FC_OBS_API=/Users/fc-controller/control/api-controller.json
   FC_OBS_POLICY=/Users/fc-controller/control/local-policy.json
   read -r -p 'Existing approved execution ID: ' FC_OBS_EXECUTION
   read -r -p 'Existing approved catalog task ID: ' FC_OBS_TASK
   FC_OBS_PRINCIPAL="$(id -un)"
   python3 -m src.live_observation readiness
   python3 -m src.api_controller status --config "$FC_OBS_API"
   python3 -m src.api_controller audit --config "$FC_OBS_API"
   ```

   The existing API config must reference the existing $10/day, $100 lifetime
   budget, reviewed pricing and private external key file. Keep
   `connectivity_enabled=false`. Stop if there is any unresolved hold. Preserve
   the operator's existing STOP files; never remove STOP merely to pass this run.
3. For first installation only, copy `config/live-observation.example.json` to
   `$FC_OBS_BROKER` and edit its absolute paths to the actual protected locations.
   Include every STOP path enforced by the selected policy, including its
   `state/STOP`. `mode=observation-only` and the v2 protocol expose only observations. Leave `enabled=false` while reviewing paths. Its ledger must be
   new and separate from every historical ledger, credential and application
   repository. After review, set this observation config to `enabled=true`
   **before** initializing the final deployed configuration. Initialize exactly once:

   ```sh
   chmod 600 "$FC_OBS_BROKER"
   python3 -m src.live_observation init-broker --broker "$FC_OBS_BROKER"
   ```

   On later runs, inspect the ledger; never recreate or replace missing state.
   The ledger binds the exact configuration digest, so do not edit its deployed
   config. Keep any disabled rehearsal config/ledger separate and preserved.
4. Review the exact task, immutable source, manifest, prompt digest, pinned model
   and maximum 20,204,800 nano-USD reservation:

   ```sh
   python3 -m src.live_observation review --broker "$FC_OBS_BROKER" \
     --policy "$FC_OBS_POLICY" --execution "$FC_OBS_EXECUTION" \
     --task "$FC_OBS_TASK" --principal "$FC_OBS_PRINCIPAL"
   ```

   Read-only review does not approve, reserve or send anything. Verify the task
   is acceptable for external advisory classification. No file contents are sent.
5. Separately authorize the exact binding from an interactive controlling terminal:

   ```sh
   python3 -m src.live_observation authorize --broker "$FC_OBS_BROKER" \
     --policy "$FC_OBS_POLICY" --execution "$FC_OBS_EXECUTION" \
     --task "$FC_OBS_TASK" --principal "$FC_OBS_PRINCIPAL"
   ```

   Review the displayed task and type the complete displayed `AUTHORIZE ONE
   OBSERVATION <digest>` challenge. Do not pipe a confirmation. This permits only
   one request, expiring within 15 minutes; coding/publication remain separate.
6. Execute this command **once**, without any retry wrapper:

   ```sh
   python3 -m src.live_observation run --broker "$FC_OBS_BROKER" \
     --api-config "$FC_OBS_API" --execution "$FC_OBS_EXECUTION" \
     --principal "$FC_OBS_PRINCIPAL"
   ```

   It sends at most one POST and returns a sanitized advisory decision plus usage
   receipt, or a blocked/unknown result. Lack of visible text is not evidence of
   zero billing. Any failure ends the canary; do not rerun or authorize another
   task to recover the missing classification. An application repository is never
   modified, and no coding, QA execution or publication is invoked.
7. Inspect durable evidence and preserve the final ledger/config pair for audit:

   ```sh
   python3 -m src.live_observation audit --broker "$FC_OBS_BROKER"
   python3 -m src.api_controller status --config "$FC_OBS_API"
   python3 -m src.api_controller audit --config "$FC_OBS_API"
   ```

   End the canary by revoking the grant (and use the existing operator STOP
   procedure if further dispatch must be blocked). Keep the deployed config
   unchanged so its audit remains readable:

   ```sh
   python3 -m src.live_observation revoke --broker "$FC_OBS_BROKER" \
     --api-config "$FC_OBS_API" --execution "$FC_OBS_EXECUTION"
   ```

## Limits and offline validation

The trusted local OS account and protected ledgers are the authority boundary;
this CLI is not a remote multi-user service. STOP is checked before dispatch and
again after accounting and before delivery; it cannot recall an already sent
request. A restart cannot recover the in-memory classification. The 512-token
profile is bounded but has no live evidence of classification sufficiency, and
provider structured-output mode is not required: strict local parsing rejects
anything outside the reviewed schema. No live canary has been run by Codex.

Tests patch only the production HTTP transport boundary, forbid sockets and the
credential helper, clear inherited environment data, and use temporary sources
and ledgers. Existing synthetic adversarial parser/accounting tests remain. The
Linux/macOS broker workflow explicitly runs the live integration tests in normal
and optimized Python; full regression workflows discover them too. Exact results
are recorded in [Sprint evidence](SPRINT-6.13B-EVIDENCE.md).
