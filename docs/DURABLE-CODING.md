# Durable supervised coding (Sprint 6.16)

The v4 controller runs catalog coding jobs sequentially on the existing trusted,
credential-free QA host. It has no scheduler, model tools, retry loop, publisher,
merge or deployment capability. Every attempt needs an independent task approval
and a separate controlling-terminal paid-request approval. Each has a fresh
execution, token and request ID. Reusing the same catalog entry creates a new
preparation; it never resets an earlier execution or grant.

## Installation and schema review

Use the existing protected v3 coding broker configuration, existing broker file,
API configuration and shared budget file. Do not initialize or copy a replacement
production ledger. Preserve a verified backup using the existing operator backup
procedure before any separately reviewed production upgrade. This sprint does
not perform that procedure or open production state.

```sh
python3 -m src.durable_coding upgrade --broker /protected/coding-broker.json --maximum-jobs 1000
```

Review and type the complete `UPGRADE EXISTING CODING LEDGER <digest>` challenge
on the controlling terminal. Upgrade verifies the existing v3 history and API
configuration, then atomically adds `coding_upgrade`, `coding_jobs` and
`coding_events`, plus `coding_legacy_closures`, with UPDATE/DELETE rejection triggers. The v3 metadata, grants,
events, task uniqueness and consumed authorizations remain untouched and use
the original v3 verifier on every v4 transaction. The added upgrade record pins
the existing configuration, API/budget path, capacity, operator and legacy digest.
The reviewed upgrade also appends a permanent coding-authority binding to the
shared budget audit and adds immutability triggers for budget metadata/events,
request identities and settled receipts. Existing budget rows remain unchanged;
first settlement still uses the established v1 accounting fields plus an
append-only settlement event. Another broker file cannot acquire that budget, and old
v3 dispatch paths cannot bypass the binding. If a crash occurs between the two
ledger commits, retry the same upgrade against the same files; the binding is
idempotent and no dispatch is enabled before the schema upgrade commits.
There is no implicit migration or downgrade; the old v3 controller refuses the
extended schema. Stop the old controller before installing the reviewed upgrade.
A second upgrade fails closed.

The configured storage ceiling still applies, including legacy data. Queue
capacity is separately reviewed at upgrade because an original v3 installation
may have `max_tasks=1`. The extension never changes that historical limit.
If storage fills, preserve evidence and stop; do not truncate history.

## Routine workflow

`BROKER` below is the existing protected coding broker configuration. These are
foreground operator commands; none starts unattended inference.

```sh
python3 -m src.durable_coding list --broker "$BROKER"
python3 -m src.durable_coding prepare --broker "$BROKER" --policy "$POLICY" --task "$TASK"
python3 -m src.durable_coding approve --broker "$BROKER" --execution "$EXECUTION"
python3 -m src.durable_coding authorize --broker "$BROKER" --execution "$EXECUTION"
python3 -m src.durable_coding dispatch --broker "$BROKER" --execution "$EXECUTION"
python3 -m src.durable_coding inspect --broker "$BROKER" --execution "$EXECUTION"
```

Preparation returns the new execution ID and an immutable source/policy binding.
Approve reviews the task on the terminal. Authorize prints the full reviewed
model configuration, source, instructions, pricing, principal and maximum spend:
5,310,000,000 nano-USD ($5.31). It requires the separate
`AUTHORIZE ONE CODING REQUEST <digest>` challenge. The maximum is a conservative
reservation ceiling; it is not a prediction of the bill. Daily and lifetime
capacity and every unresolved reservation apply across all jobs.

Queueing and preparation do not authorize spending. Multiple tasks may wait;
the operator chooses the next queued task. Only one task may hold paid authority
or have an active/indeterminate request. Every dispatch checks the current
principal, STOP, expiration, exact source HEAD, task approval, policy and API
configuration again. A settled ordinary output/QA failure permits a separately
authorized independent job. An authorized but undispatched job can be cancelled:

```sh
python3 -m src.durable_coding cancel --broker "$BROKER" --execution "$EXECUTION"
```

Task approvals retain the existing ten-minute preparation expiry; paid grants
also respect the reviewed task timeout and expire within fifteen minutes.
Expired entries remain visible. Cancel and prepare a new execution; never extend
an old approval. The queue does not refresh revisions or policies automatically.
A crash between local preparation and queue insertion leaves a visible local
preparation. After inspection, explicitly attach that original preparation:

```sh
python3 -m src.durable_coding enqueue --broker "$BROKER" --policy "$POLICY" --execution "$EXECUTION" --task "$TASK"
```

If local task approval committed but queueing was interrupted, `queue --execution`
verifies that approval and records it. Neither command can mint paid authority.

## State and recovery rules

Task events are append-only:
`prepared → approved → queued → authorized → dispatched → response_received →
accounting_settled → qa_running → validated`, with `failed`, `blocked`,
`cancelled` and explicit `adjudicated`/`undispatched_closed` closure transitions. A durable claim event
binds paid authorization before `authorized`. QA check events do not advance
state. `dispatched` means committed intent, so a crash at that boundary is fenced
conservatively even if no bytes were actually sent.

The shared budget audit separately records reservation, dispatch intent,
untrusted response observation, diagnostic and validated settlement or operator
reconciliation. Inspection reports task state, provider state and billing state
separately. HTTP rejection does not establish no charge. A locally rejected
response retains its full reservation until verified reconciliation. An
incomplete but strictly validated response may settle billing but never reaches
patch application. A successful API receipt is not successful independent QA.

Restart before dispatch can consume the existing unexpired authorized claim
once. Restart after durable dispatch cannot call the provider again. A crash
after settlement but before final QA is indeterminate; response bytes are not
retained for replay. There is no resume/retry of that attempt. Close it with
external evidence, then prepare and approve a new execution.

For unresolved billing, retain a provider request export or provider support
confirmation and a separate protected JSON manifest with exactly these fields:

```json
{
  "schema": "provider-billing-evidence-v1",
  "request_id": "LOCAL_32_HEX_REQUEST_ID",
  "execution": "LOCAL_32_HEX_EXECUTION_ID",
  "provider_request_id": "req_PROVIDER_ID",
  "provider_response_id": "resp_PROVIDER_ID",
  "account_project": "VERIFIED_ACCOUNT_AND_PROJECT",
  "source": "provider-support-confirmation",
  "reference": "https://help.openai.com/RETAINED_SUPPORT_REFERENCE",
  "artifact_sha256": "SHA256_OF_SEPARATE_RETAINED_PROVIDER_ARTIFACT",
  "actual_nano_usd": 300000,
  "currency": "USD",
  "final": true,
  "provider_terminal": true,
  "outcome": "billed",
  "model": "gpt-6.1-sol",
  "service_tier": "default",
  "pricing_version": "sol-standard-global-2026-10-23-v1",
  "usage": {
    "input_tokens": 100,
    "cached_input_tokens": 0,
    "cache_write_tokens": 0,
    "output_tokens": 10,
    "reasoning_tokens": 0
  }
}
```

This is a schema example, not billing evidence or a suggested charge. For a
provider-confirmed zero charge use `actual_nano_usd: 0` and
`outcome: "confirmed-no-charge"`. At least one provider request/response ID is
required; use null for the other if unavailable. The billed manifest needs all
usage dimensions. The reference and artifact must allow independent verification
in the correct provider account/project. Do not use model text, local validation
failure, an arbitrary digest, or account aggregate usage as evidence.

```sh
python3 -m src.billing_reconciliation --api-config "$API_CONFIG" --manifest "$MANIFEST" --artifact "$PROVIDER_ARTIFACT"
python3 -m src.durable_coding adjudicate --broker "$BROKER" --execution "$EXECUTION" --evidence "$MANIFEST" --artifact "$PROVIDER_ARTIFACT"
```

The first command requires `VERIFIED EXTERNAL PROVIDER BILLING <digest>` on the
terminal. It validates completeness, the retained artifact hash, reservation,
execution and any locally observed provider IDs. Billed usage must reproduce
the final amount under the reviewed pricing, including cache-write and
long-context rates; unsupported adjustments or tiers remain unresolved. The operator independently
verifies authenticity, final usage, pricing and amount in the provider channel;
the controller cannot authenticate an exported support document itself.
The amount must fit the reservation or the hold remains unresolved for review.
The second command separately requires `CONFIRM PROVIDER TERMINAL AND ALL QA STOPPED NO REPLAY
<digest>`, checks the final outcome against settled accounting and closes the
attempt without replay authority. The same process closes legacy v3 consumed
attempts using an explicit v4 closure record, leaving every original record unchanged. New v4 work proven never dispatched has a separate pre-dispatch closure:

```sh
python3 -m src.durable_coding close-before-dispatch --broker "$BROKER" --execution "$EXECUTION" --evidence "$LOCAL_TERMINATION_ARTIFACT"
```

Review retained supervisor/administrator evidence that the old controller and all
helpers/descendants terminated before provider dispatch. The command requires
`CONFIRM NO PROVIDER DISPATCH AND ALL PROCESSES TERMINATED <digest>` on the
terminal, checks the execution and shared budget again atomically with closure,
and preserves the consumed grant. With no reservation, accounting is unchanged.
For a **new v4 reservation**, absence of the durable transport marker, or a trusted
`not_attempted` diagnostic with no response observation, proves the provider was
not called. After terminal review this cancels that reservation, preserves its
original maximum, and appends `reservation_released_before_dispatch`; it records
no provider usage or fabricated billing receipt. The budget fences late transport
startup after cancellation. A cross-ledger crash can complete the same closure
without another financial change.

Legacy reservations, received responses and uncertain dispatches reject this
route. Absence of a marker in an old ledger is never reinterpreted as no dispatch;
the historical $5.31 hold cannot be released this way. A missing provider ID or a
failed response validation alone is not proof of no dispatch. If the controller stopped in
`qa_running` (or a legacy dispatch has no terminal failure diagnostic), also
provide `--qa-termination /protected/retained-local-termination-evidence`. The
operator must independently establish that the old controller and every QA
process/descendant have stopped; a provider receipt does not prove local process
termination. Its digest is recorded with closure. STOP remains in force throughout;
inspection and accounting review do not clear it, and no closure grants spending.

The older budget digest-only reconciliation command remains a legacy trusted
operator interface. Use the manifest/artifact workflow above for this queue;
releasing a hold alone cannot close an uncertain task or grant a new request.

## Original unresolved $5.31 reservation

Execution `d4d25e5cc5574e70a0ce7651b7e76517` is permanently consumed. The reported
5,310,000,000 nano-USD is a reservation, not a proven charge. HTTP 200 and
`metadata/cache_policy` do not establish usage or cost. Nothing in this sprint
reads, resets, reconciles or copies the operator's actual ledger.

Keep that reservation unresolved until provider evidence links the local request,
execution and dispatch time to the correct account/project and provider
request/response ID and proves the final billed amount or no-charge outcome.
For usage-based verification include input, cached input, cache-write TTL/rates,
output (with reasoning included), model, service tier, pricing version and
long-context multipliers. If the original request-level linkage cannot be
established from independently retained records, obtain provider support
confirmation. Aggregate usage and a failed local parser are insufficient.
The additive upgrade does not release the historical hold; the shared budget
fences new work even if task IDs, execution IDs or broker instances change.
Never change budget paths or provision substitute ledgers to evade the hold.

## Edit contracts and evidence

The original pinned Sol comment canary stays available as a regression. Reviewed
catalog entries can also use `supervised-sol-low-reviewed-edit-v1`, with the same
531-cent ceiling and an explicit `edit_contract`:

```json
{"schema":"bounded-replacement-v1","path":"test/analyzer.test.js",
 "old":"EXACT_UNIQUE_REVIEWED_ANCHOR","maximum_new_bytes":1024,
 "validation":"throws-test-v1","symbols":["compile"]}
```

The independently reviewed policy pins repository, source revision, complete
source manifest, one existing allowed JavaScript file, the replacement anchor,
new-byte ceiling, validation grammar, reviewed symbols, instructions and syntax/test commands. Only an `old`/`new` JSON
replacement is accepted. File creation/deletion, mode changes, model tools and
model-selected QA commands are unavailable. The trusted runner reconstructs all
source files, applies only the permitted replacement, runs independent checks,
and verifies the candidate afterward. Executable edits must pass a finite grammar before QA: `throws-test-v1` permits
one assertion using a reviewed callable and canonical JSON data, while
`numeric-expression-v1` permits arithmetic over reviewed operands without calls,
properties, statements, comments or increment operators. These grammars support
new catalog tasks and revisions without granting arbitrary JavaScript execution.
The policy author must review callable safety and numeric operand context in the
trusted source. Other edit shapes need a separately reviewed contract extension.
The existing trusted QA-host security boundary still applies; this feature adds
no sandbox or general shell interface. The included second fixture adds an
executable missing-exit regression test, distinct from a comment insertion.

Before response validation, the budget audit durably captures a bounded
untrusted projection: execution/local request linkage, provider IDs when present,
HTTP status, finite completion/model/tier values, bounded token dimensions,
pricing version and response hash. Arbitrary metadata, prompts, code, raw
responses, credentials and exception strings are excluded from this diagnostic
projection. The validated settlement separately records calculated charge and
trusted schema-checked usage. Finite validation section/rule diagnostics remain
available on rejection. Observed usage never settles a request by itself.

## Verification and limitations

`tests/test_durable_coding.py` exercises real broker, controller, shared accounting,
restricted receiver and trusted QA on disposable protected stores with synthetic
transports. It covers sequential distinct jobs, failed validation and verified
recovery, independent QA failure, restart fences, duplicate authority, STOP,
expiry, source/policy drift, sanitized evidence, incomplete output, legacy history,
budget ceilings and repeated catalog preparations. Existing suites retain the
original Sol comment regression and optimized fail-closed coverage.

CI runs the full suite and lifecycle regressions on Linux and macOS. Local
verification in this environment is Linux only; macOS execution requires the CI
runner. No provider API call is part of these checks. No production upgrade or
billing reconciliation is performed by CI. Provider artifact authenticity remains
an explicit human verification step. Cross-ledger operations intentionally fail
closed across crashes; they do not provide distributed exactly-once execution or
automatic continuation. Missing stores, changed bindings and exhausted capacity
require operator review rather than initialization or reset.
