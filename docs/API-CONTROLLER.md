# Trusted Responses API controller

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
The controller accepts at most 2,048 UTF-8 input bytes and 64 generated tokens,
including reasoning. Connectivity requests use the fixed prompt `Reply with OK.`,
16 output tokens and minimal reasoning. An incomplete response is a valid billed
outcome, not permission to retry. Empty reasoning summaries are accepted; no raw
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
priority processing, conversation continuation or reasoning payload is enabled.
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
estimating tokenization or protocol overhead. Connectivity reserves $0.0200064;
a 64-token request reserves $0.0200256. Actual cost uses `(input-cached)*input_rate
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
