# Trusted Responses API controller

See [the current evidence-based compatibility review](RESPONSES-OBSERVED-COMPATIBILITY.md)
for the 256-token connectivity profile and the reviewed zero-only `tool_usage` shape.

Sprint 6.12 prepares a text-only operator connectivity command and offline
broker integration. **Live coding capacity remains zero.** No API key is needed
for tests. The existing subscription and legacy live gates remain closed.

## API and trusted boundary

Python 3.12+ standard-library HTTPS calls the documented
`POST https://api.openai.com/v1/responses`; there is no third-party SDK dependency,
custom base URL, proxy override, redirect, automatic retry or undocumented endpoint.
The allowlist contains only `gpt-5-nano-2025-08-07`. This is a connectivity model,
not approval to use it as a coding agent. Changing models requires code review.
Official references checked October 23, 2026:

- [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [GPT-5 nano specification and prices](https://developers.openai.com/api/docs/models/gpt-5-nano)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Data controls](https://developers.openai.com/api/docs/guides/your-data)
- [Deprecations](https://developers.openai.com/api/docs/deprecations)

GPT-4.1 nano's announced shutdown is October 23, 2026; it is not allowlisted.
The synthetic worker profile accepts at most 2,048 UTF-8 input bytes and 64 generated
tokens, including reasoning. The separately reviewed operator connectivity profile
uses only the fixed prompt `Reply with OK.`, 256 output tokens and minimal reasoning.
An incomplete response is accounted for using actual reported usage, including zero
usage; it grants no permission to retry and does not independently prove billing. Documented reasoning is validated and discarded; no raw
reasoning, assistant text, refusals, IDs, metadata or headers enter receipts.

A trusted spawned controller helper reads only the configured external private
credential file; credentials are never in argv, environment, worker payloads,
prompts or accounting records. It rejects symlinks, permissive files, hardlinks
and unprotected ancestors, checks the opened file and bounds credential bytes.
The helper uses TLS verification and a fixed endpoint. It is terminated after a
20-second wall deadline, including DNS/connect/read/write, with bounded cleanup.
Socket operations also have 10-second timeouts. The response is capped at 256 KiB.
Exceptions are reduced to fixed categories without messages or tracebacks.
Provider errors, including 401/403, 429 (rate limit **or** exhausted credits),
5xx, redirects and network failures retain the hold. There are **zero retries**.

Requests explicitly set `store=false`, `background=false`, `stream=false`,
`prompt_cache_retention=in_memory`, default service tier, disabled truncation,
`tools=[]`, `tool_choice=none` and no parallel calls. Provider abuse monitoring
and project/account retention policies still apply; `store=false` is not a
claim of Zero Data Retention. No hosted tool, file, image, audio, Batch, Flex,
priority processing, conversation continuation or reasoning replay is enabled.
Unexpected response fields or new pricing dimensions fail closed and retain the
reservation until reviewed. Model output cannot become a command.

## Accounting and limitations

All amounts are integer nano-USD (1 USD = 1,000,000,000 units). The versioned
pricing example records standard text rates per token: input 50, cached input 5,
output 400 nano-USD ($0.05/$0.005/$0.40 per million tokens). Review provider prices
and model availability immediately before activation; no pricing fetch or update
occurs automatically. An operator-supplied price table is trusted configuration,
not provider billing evidence. Stale/incorrect prices invalidate the cost bound.

Before dispatch, reserve **400,000 input tokens at the uncached rate plus the
maximum output at the output rate**, even though the actual prompt is tiny.
This uses the full documented context as a conservative upper bound and avoids
estimating tokenization or protocol overhead. Connectivity reserves **20,102,400 nano-USD ($0.0201024)** for 256 output tokens;
a synthetic 64-token request reserves $0.0200256. Actual cost uses `(input-cached)*input_rate
+ cached*cached_rate + output*output_rate`. Reasoning tokens are a subset of
output and are not charged twice. Unsupported modalities, tools, models and
pricing dimensions are rejected, never guessed. This overreservation deliberately
reduces availability in exchange for a simple upper bound.

Default daily ceiling is $10; lifetime is $100. Configuration may lower them;
raising either beyond these reviewed limits requires a code review. One unresolved
request blocks all new requests. A single request ID binds the complete prompt,
model settings, price version and broker identity; completed identical requests
return a sanitized receipt without dispatch. Conflicting/unknown duplicates fail.
Connectivity uses a new ID per explicit invocation, never as a retry mechanism.

`BEGIN IMMEDIATE`, SQLite FULL synchronous commits, private protected files,
exclusive initialization and filesystem directory fsync provide process concurrency
and local crash durability. Use a reliable local filesystem, one fixed ledger,
trusted controller code/configuration, protected OS account and correct clock.
Do not use NFS, clone operational ledgers, restore stale backups, delete a ledger,
change its path or start a second independent controller ledger. Those actions
would undermine local accounting. OS users that can modify controller storage are
trusted; hash bindings do not defend against a compromised controller account.
Disk/SQLite failures block requests. Partial initialization requires manual recovery,
not reinitialization. Policy/timezone changes refuse an existing ledger and need
an explicit reviewed migration preserving every row and unresolved hold.

The operating timezone defaults to `America/Los_Angeles`, persisted in metadata.
A reservation belongs to the local calendar date at admission. Completed charges
stay on that original date, even if the response/reconciliation arrives after
midnight. The daily spent bucket changes at local midnight (including DST); no
rows are reset or removed. **Every unresolved hold encumbers every subsequent
day** as well as lifetime until reconciled. Backward clock movement behind the
last audit timestamp blocks operations. Reliable OS time remains an assumption.

These are project-local operational safeguards, **not an organization-wide hard
billing limit**. They cannot stop API charges elsewhere in `fort-custer-agents`,
price changes, taxes/currency effects, provider accounting discrepancies or a
compromised operator. The prepaid balance and disabled recharge are externally
managed; no top-up, balance management or refill endpoint exists here.

## Read-only inspection and first installation

From the automation checkout, these commands do not load a key or use the network:

```sh
python3 -m src.api_controller readiness
python3 -m src.api_controller status --config ~/fort-custer-local/api-controller.json
python3 -m src.api_controller audit --config ~/fort-custer-local/api-controller.json
```

For a **new installation only**, the operator copies
`config/api-controller.example.json` to `~/fort-custer-local/api-controller.json`,
reviews all paths, timezone and prices, ensures a private 0700 directory and
0600 config/key permissions, then runs:

```sh
python3 -m src.api_controller init-budget --config ~/fort-custer-local/api-controller.json
```

The credential and budget stay outside this checkout and every worker/QA source
or scratch tree. Keep `connectivity_enabled=false`. Never initialize a replacement
ledger after losing state. Read-only inspection refuses missing files rather than
creating them. Audit output contains only IDs, hashes, integer amounts and events.

## One-request operator activation — do not run from Codex or CI

After reviewing the PR and pricing, the operator may set `connectivity_enabled`
to `true` in the external config and explicitly run **once**:

```sh
python3 -m src.api_controller connectivity --operator-connectivity \
  --config ~/fort-custer-local/api-controller.json
```

Both configuration and the explicit flag are required. The helper reads
`~/fort-custer-local/openai-api-key`; no shell command should print or export it.
This sends only the fixed harmless prompt, reserves budget, writes a sanitized
receipt and executes no tools or source changes. It does not authorize coding.
Return `connectivity_enabled` to `false` afterward. A successful receipt reports
status, token usage and estimated cost. A blocked/unknown result means inspect
status/audit and preserve the hold. Do not invoke again to test whether a timeout
was successful. The command has not been run during development.

## Recovery

Stop controller dispatch before investigating. Preserve the ledger and its SQLite
sidecars consistently; establish that the trusted helper has terminated. Match
the request audit ID, dispatch time, price version and project billing evidence.
Do not infer a zero charge from an absent response or from a local timeout.
For an unknown request, retain the full reservation until the operator has billing
and termination evidence. An evidence document must contain no credentials.
Record its SHA-256 and the actual integer nano-USD cost, then explicitly run:

```sh
python3 -m src.api_controller reconcile --config ~/fort-custer-local/api-controller.json \
  --request-id REQUEST_HEX32 --actual-nano-usd ACTUAL_INTEGER \
  --evidence-sha256 EVIDENCE_HEX64
```

Reconciliation cannot exceed the reservation or run twice. If billing exceeds
the bound, stop operations and investigate pricing/protocol assumptions; do not
release the hold. The command records the evidence digest and returns an
operator-reconciled receipt. It cannot redispatch the original request. A hash
records the operator's evidence; it does not independently authenticate billing.

## Broker/tool/QA/publication path

Current integration is **synthetic only**: the actual Sprint 6.9–6.11 `Broker`
checks its immutable approved task, fresh source revision/manifest, principal,
claim token/generation, deadline and STOP before reservation and dispatch and
before delivering the sanitized receipt. Prompt, model, prices, empty tools,
authorization and claim hashes bind the durable budget reservation. The same
checks run on duplicate receipt access. If STOP arrives during the request,
account usage but refuse delivery. No new grant or model approval can be minted.
The budget and grant ledgers are separate; an interrupted admission conservatively
leaves a hold. This is not a live atomic broker migration.

`api_tools.py` defines an explicit strict `propose_file(path, content)` contract.
The synthetic receiver validates JSON without duplicate keys, manifest and exact
allowlisted relative paths, argument names/types and content bounds. It only
returns a proposal digest; it never reads/writes a file or starts a process.
Every executable receiver request is refused, including caller-supplied isolation
receipts. This schema is not advertised to the live connectivity model.

The required future path is: independent operator task/source/tool approval →
authoritative live broker single-use fenced claim → budget reservation bound to
that claim and exact reviewed prompt/model/tool configuration → trusted API
request → strict untrusted function-call validation → independently verified
credential-free isolated receiver using broker-owned source manifest/allowlist →
external independent QA on a reconstructed candidate and trusted oracle → broker
finalization → separately human-authorized draft publisher. Each external side
effect must commit its dispatch intent before invocation and use its own replay,
expiration, STOP and recovery protections. Existing synthetic evidence cannot
substitute for live admission, OS isolation, watchdog or publication evidence.

## Connectivity diagnostics and the unresolved first request

The first operator attempt, local request `33f477e596b0473b9c020ef32d69a505`,
reserved **20,006,400 nano-USD ($0.0200064)** and produced no settlement.
This development change does not open, migrate, reconcile or retry the operator's
ledger/request. Leave that hold intact. The old `blocked-or-unknown` receipt plus
one reservation cannot establish whether the POST reached the provider. Dashboard
zero usage after several minutes is insufficient evidence to release it.

A confirmed compatibility defect was found in the response validator: the
current official Responses reasoning item schema includes nullable `content` and
`encrypted_content`, with encrypted content documented as returned by default.
The old validator rejected both fields. The first correction accepted empty/null
reasoning content and bounded opaque encrypted strings. The current validator
also validates and discards documented reasoning text and summaries; see
[response validation](API-RESPONSE-VALIDATION.md). It
never decrypts, persists, forwards or reuses them. Documented message `phase` is
accepted only with its defined enum values. Unknown fields, malformed usage and
executable output still fail closed. This defect
is a plausible cause of the original failure, **not a retrospective diagnosis**;
the original sanitized receipt did not retain the required evidence.

Request review confirms the documented Responses endpoint, pinned GPT-5 nano
snapshot, `reasoning.effort=minimal`, `max_output_tokens=16`, text input, disabled
tools/storage/background/streaming, default tier and `in_memory` retention.
At the time of that investigation the generic payload builder enforced 16–64 output
tokens. The connectivity request then used 16 tokens. That historical request and its
maximum reservation are unchanged. There is no automatic parameter removal,
model substitution or fallback retry if an account rejects a parameter.

References checked October 23, 2026:

- [Responses creation contract](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Official generated reasoning item schema](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_reasoning_item.py)
- [GPT-5 minimal reasoning example](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_new_params_and_tools)
- [Model-specific cache retention](https://developers.openai.com/api/docs/guides/prompt-caching)

### Diagnostic meanings

Future failures print the local request ID and a fixed-vocabulary `diagnostic`:
`category`, `phase`, `dispatch`, `http_status` (integer or null), and `parameter`
(reviewed parameter name or null). The controller appends a
`request_failed_hold_retained` audit event when possible; `audit_recorded=false`
means that evidence could not be persisted. Diagnostic failure cannot release
budget or redispatch. Existing ledgers need no schema migration. Historical
requests without diagnostics remain unknown; new code does not backfill guessed
failure records for them.

| Evidence | Meaning / accounting action |
| --- | --- |
| `credential_unreadable` / `credential_format`, `not_attempted` | Protected file checks or local decoding failed before HTTP creation; no POST attempted; retain the reservation for explicit operator reconciliation |
| `local_request_invalid`, `not_attempted` | Offline request contract rejected; no helper/network invocation; retain hold |
| `connect_failed`, `connect_timeout`, `tls_verification_failed`, `not_attempted` | Explicit connection/TLS failed before POST; retain hold |
| `request_rejected`, HTTP 400 | Provider returned a request rejection; raw body/message is discarded; retain hold |
| `unsupported_parameter`, HTTP 400 | Bounded error JSON contains an allowlisted unsupported-parameter code; only a reviewed parameter name can be reported; retain hold |
| HTTP 401/403/404/429/5xx/3xx | Fixed authentication/permission/model-or-endpoint/rate-limit-or-exhaustion/provider/redirect category with exact status; no redirect or retry; retain hold |
| `response_json_invalid` / `response_schema_invalid`, HTTP 200 | An HTTP success body was received, but cannot be safely reconciled; potentially billed, retain full hold |
| `transport_timeout` / `transport_failure`, `may_have_been_sent` | Failure during POST or while awaiting response; chargeable outcome unknown, retain hold |
| `response_too_large` / `credential_echo` / body read failure, HTTP 200 | Response was received but cannot be accepted; retain hold |
| `helper_deadline` / lost helper / invalid IPC | Missing reliable phase evidence; treat as ambiguous, retain hold |

`response_received` proves an HTTP status was observed, **not a billing amount**.
A 5xx response can still have an uncertain chargeable outcome. A 429 alone cannot
distinguish throttling from exhausted credits. Error parsing never emits raw
messages, unreviewed codes, arbitrary parameter strings, auth headers or response
bodies. HTTP error-body parsing is bounded to 8 KiB; an unreadable/oversized body
does not erase an already observed status. TLS verification, the fixed endpoint,
20-second helper deadline, 10-second socket bounds and zero automatic retries
remain enforced. An explicit connection is made before POST; implicit reconnects
are disabled. An unknown top-level controller failure stays ambiguous.

### Recovery for the existing uncertain request — no retry authorized

1. Keep `connectivity_enabled=false`. Do not invoke connectivity, change ledger
   paths, initialize a replacement, delete rows, reset dates, or create a new
   request ID. No retry is authorized by this fix or by manual reconciliation.
2. Use only the read-only `status` and `audit` commands above. Preserve a
   consistent protected backup of the ledger and any SQLite sidecars. Record the
   exact deployed code revision, reservation ID/time/amount, selected model and
   pricing version. Confirm the trusted helper is no longer running. Never copy
   the key or include it in evidence, support requests or screenshots.
3. Check the **fort-custer-agents** project in the operator's OpenAI Usage and
   Billing views. Verify organization/project and service-account/key filters,
   time range, timezone (including the adjacent UTC calendar day), selected model,
   and both token usage and costs. Allow reporting to finalize; several minutes
   of zero usage is not a nonbilling attestation. Export matching finalized
   usage/cost records when available. This local UUID is not a provider response
   ID, and `store=false` means a response-retrieval probe is not a recovery method.
4. Correlate finalized billing evidence with the attempt window. If the evidence
   cannot rule out an accepted/billed request, keep the full hold and ask the
   provider to resolve the uncertain attempt using nonsecret project/time/model
   information. Do not invent an HTTP status from the absence of usage.
5. Only after helper termination and sufficient evidence establish the actual
   charge, the operator may explicitly reconcile it. Hash the protected,
   nonsecret evidence document with SHA-256. Review the actual integer nano-USD
   amount, which may be zero **only when supported by evidence**, then use the
   existing manual `reconcile` command with the original local request ID:

```sh
python3 -m src.api_controller reconcile --config ~/fort-custer-local/api-controller.json \
  --request-id 33f477e596b0473b9c020ef32d69a505 \
  --actual-nano-usd REVIEWED_ACTUAL_INTEGER --evidence-sha256 REVIEWED_EVIDENCE_HEX64
```

This is an operator procedure, not an instruction for Codex/CI to execute now.
Amounts above the reservation require an accounting/pricing investigation; the
command must continue to refuse them. Reconciliation records evidence and never
resends the request. Any future connectivity attempt requires separate explicit
operator authorization after review. Live coding remains disabled.


The second HTTP-200 validation investigation and exact compatibility policy are
documented in [API-RESPONSE-VALIDATION.md](API-RESPONSE-VALIDATION.md). Its new
fixed `validation_section` and `validation_rule` labels contain no provider
fields, values, text or identifiers. Existing unresolved reservations remain held.

The complete 2026-10-23 [top-level Responses envelope inventory](RESPONSES-ENVELOPE-SCHEMA.md) pins both OpenAPI and SDK revisions, documents discarded metadata and unsupported settings, and defines fixed-name unknown-field diagnostics. Raw provider names and values must never be logged.

