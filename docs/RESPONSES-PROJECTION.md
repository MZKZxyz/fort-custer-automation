# Projection-based Responses validation

HTTP 200 responses repeatedly failed because the controller required every
top-level name to appear in a purported complete provider schema. The latest
operator diagnostic reports another unknown name, but does not identify it.
This patch does not guess that name or inspect the private response.

The controller now projects the bounded decoded JSON object onto explicitly
reviewed receipt and security fields. Unfamiliar top-level names and values
are discarded without interpretation or recursive processing beyond the JSON
decoder. They never affect authorization, request construction, execution,
pricing, accounting, receipts, diagnostics or audit events. The historical
OpenAPI/SDK inventory is no longer an envelope rejection allowlist.

## Fields that remain authoritative

- `object` and exact pinned `model`; terminal status, error and incomplete details.
- Required `usage`, exact token arithmetic and bounds, cached/reasoning subsets,
  and the reviewed zero cache-write dimension. Unknown nested pricing/usage
  dimensions fail even when zero or null.
- `output` and its reviewed message/reasoning shapes, roles, content types and
  resource bounds. Tool calls, unknown output types/fields, unsupported modalities
  and executable output remain rejected. Accepted content is discarded.
- Known tools, tool choice, parallel calls, storage, background execution, service
  tier, cache policy, conversation/state, reasoning/text configuration, finite
  penalty echoes and other previously reviewed metadata retain existing checks.
- Known `tool_usage` must retain the exact reviewed shape and integer-zero
  counters. Nonzero activity, malformed counters or unknown dimensions reject.
- Known request-only configuration (`context_management`, `include`, `input`,
  `stream`, `stream_options`) remains forbidden even when null or empty.

An unknown top-level object that resembles a tool call is inert data. Only the
strictly checked `output` path can describe output, and that path rejects tool
calls. Unknown metadata cannot replace missing usage or rescue conflicting
known configuration. Future features require explicit review before they can
contribute to a receipt or authorize any action.

Maximum response bytes, duplicate-key rejection, nonfinite JSON constant
rejection and parser/resource failure handling are unchanged. Malformed JSON
still fails globally, including when malformed content is in an unknown field.
Historical fixed-name diagnostics remain decodable for existing records; new
unknown metadata does not generate diagnostic labels or presence indicators.

## Operator runbook and limitations

Retain the pinned `gpt-5-nano-2025-08-07`, fixed `Reply with OK.` prompt, 256-token
supervised limit, minimal reasoning, `store=false`, no tools/streaming/background,
zero retries, $10/day and $100 lifetime ceilings, and single unresolved request
limit. The synthetic worker limit, reservation formula, STOP, grants, credential
helper/process isolation and approval gates are unchanged. Live coding stays off.

Do not access, copy, reconcile, release, delete, modify or retry the operator's
latest unresolved reservation. Its billing reconciliation belongs to the operator.
Tests use disposable synthetic ledgers, never the operator ledger, API key or raw
response. Do not initialize a replacement operational ledger. No inference,
merge, deployment or autonomous activation is authorized by this patch.

This policy deliberately stops detecting arbitrary provider additions as schema
errors. It assumes the reviewed request restrictions, known security echoes,
required token usage and reviewed pricing remain sufficient for the estimate.
An unfamiliar top-level financial-looking object is not pricing authority or
independent provider billing evidence. The controller cannot establish complete
provider invoice semantics from ignored metadata. New execution features,
modalities or pricing models require separate review; unknown nested output or
usage dimensions continue to fail closed.

The PR #25 fixture is reused with synthetic null, numeric, string, nested-object,
array, instruction-looking, dummy-credential and tool-like metadata. Regressions
compare exact receipts for zero and nonzero usage, scan receipts/audits/database
bytes and captured logs, and test mixed unknown metadata plus authoritative
failures. Exact local and CI results are recorded in the draft PR.
