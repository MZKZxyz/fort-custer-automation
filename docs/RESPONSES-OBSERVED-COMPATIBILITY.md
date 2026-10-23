# Evidence-based compatibility review

The operator reports an HTTP 200 incomplete response from the pinned model,
with `max_output_tokens=16`, encrypted reasoning, zero reported usage, and
three previously unrecognized fields: `frequency_penalty`, `presence_penalty`,
and `tool_usage`. Envelope rejection after HTTP 200 leaves the reservation
unresolved. A separate raw diagnostic request cannot settle that request.

## Reviewed observed metadata

`observed-incomplete.json` reproduces the reported fields, status, types and
zero usage with synthetic IDs and ciphertext and no timestamps. Its `tool_usage`
object uses the exact operator-supplied structure: `image_gen` has input/output/
total token counters and input/output detail objects with `image_tokens` and
`text_tokens`; `web_search` has `num_requests`. Every object has an exact key
set. Every leaf must be a nonnegative integer (booleans are rejected), and all
must be zero under this tools-disabled profile. Missing fields, unknown
categories, unknown nested pricing dimensions and nonzero activity fail closed.
An absent optional `tool_usage` preserves documented response compatibility;
if present it must have the complete reviewed shape, never null or partial.

Penalty echoes must be finite numbers. All validated tool and penalty metadata
is discarded and never changes requests, pricing, receipts or audit events.
There is no reviewed tool pricing model and no additional tool charge is
inferred. The production validator safely settles the reported zero usage and
discards encrypted reasoning. This synthetic fixture is not independent
provider billing evidence; it does not establish whether the provider billed
anything or whether its reported zero usage was incorrect.

## Supervised connectivity runbook

The operator-only command uses 256 output tokens with `Reply with OK.`. The
request validator accepts the larger limit only with that exact profile:
pinned model, minimal reasoning, tools disabled, `store=false`, no background
processing, streaming, or retries. The generic synthetic worker builder retains
its 16–64-token limits. No live workers or autonomous coding are enabled.

Reservation: `400000 * 50 + 256 * 400 = 20102400` nano-USD (**$0.0201024**).
The $10/day and $100 lifetime ceilings, durable holds, one outstanding request
maximum, STOP, grants, and credential isolation are unchanged. Valid incomplete
responses are accounted for using reported usage without requiring visible text.
Estimated usage charge is not a provider invoice.

Keep connectivity disabled during development and review. Do not run real
inference, merge, deploy, or enable workers. Live API connectivity has not been
validated. No operator ledger or raw response was accessed.

Preserve request `6d578df6efee40f89ef377c88df0c91b` and the separate diagnostic
request. Do not access, modify, reconcile, delete, migrate, or retry either in
this task. This validator does not retroactively settle old holds. A future
operator-only connectivity test requires separate review, authorization, and
proper reconciliation of outstanding reservations under existing recovery
procedures. Never initialize a replacement ledger.

## Security assumptions and remaining limits

Strict pricing dimensions, usage arithmetic, executable-tool rejection,
unsupported-modality rejection, and conflicting configuration checks remain.
Documented optional metadata preserves existing validation. New nested pricing
dimensions require review. Bounds depend on the reviewed pricing and context
limit; the local ledger accounts only for this controller. Tests use synthetic
transports, temporary ledgers, and dummy credential files, with no real
credentials or inference. Existing CI uses offline tests and synthetic
rehearsals; no inference or credential provisioning step was added. The daily
planner is a separate dispatch-only workflow and must not be triggered here.
