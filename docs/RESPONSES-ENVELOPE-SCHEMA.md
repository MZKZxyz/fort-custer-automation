# Responses envelope review — 2026-10-23

## Scope and evidence

The third operator attempt reported HTTP 200, `response_schema_invalid`,
`envelope/unknown_fields` (local request `b698398ad4604d02865dcc62a45929c3`).
That establishes that at least one top-level name was outside the old allowlist.
It does **not** identify the name. No provider response, credentials, operator
ledger, or live API was inspected. The existing reservation remains unresolved;
this change neither retries nor reconciles it. Connectivity and autonomous
coding remain disabled. The recovery procedure in [API-CONTROLLER.md](API-CONTROLLER.md)
still requires independent billing verification before manual reconciliation.

Reviewed immutable sources:

- [Official OpenAPI JSON](https://github.com/openai/openai-openapi/blob/0938b0f003300cd4c6ec39191532df81b04dfae1/openapi.json),
  commit `0938b0f003300cd4c6ec39191532df81b04dfae1`, published 2026-10-23,
  API info version **2.3.0**, OpenAPI **3.1**; publisher source revision **1299002**.
  Git blob `52d608b9443f92275187047dc6cb3b74cc2727d8`.
  Reviewed `POST /responses` HTTP-200 `application/json` schema `Response`,
  recursively resolving `allOf` and `$ref` through `ModelResponseProperties`
  and `ResponseProperties` (not the create-request field list).
- [Generated Python SDK Response](https://github.com/openai/openai-python/blob/d622f28ad5cb3f947541936c0c139891211a42c5/src/openai/types/responses/response.py),
  commit `d622f28ad5cb3f947541936c0c139891211a42c5`, blob
  `3ec1fd01f5230d7770db34ecdb442a5a70f5d6f4`.
  Compared every annotated `Response` field and the `output_text` property.

The OpenAPI envelope defines **37 properties**. The SDK defines **36 serialized
fields**, all in that set, plus the computed `output_text` property. The prior
allowlist covered all 36 serialized fields and the legacy `store` echo, but
omitted `output_text`. OpenAPI explicitly describes `output_text` as SDK-only
convenience text, nullable; the SDK computes it from message content. We now
validate string-or-null and discard it even if encountered in a wire envelope.
It is never an alternative to `output`, never usage evidence, never executed,
and never persisted. This closes a documented gap; it does **not** prove that
this was the field returned in the failed operator attempt. No other new
response field was found in this pinned comparison.

## Complete top-level inventory

All 37 OpenAPI properties are listed individually below. `?` means nullable or
optional in at least one reviewed source; absence is tolerated under the
existing receipt policy except where needed for identity, completion, usage,
and output. The table describes accepted **response echoes**, not request
permissions. Nested policies remain in [API-RESPONSE-VALIDATION.md](API-RESPONSE-VALIDATION.md).
Only sanitized receipt counters/configuration are retained. Metadata contents,
IDs, text, reasoning, and cache diagnostic contents are discarded.

| Field | Official shape | Classification | Receipt policy |
| --- | --- | --- | --- |
| `access_programs` | object? (`cyber` enum) | Access / execution | Absent or null only; effective access programs unsupported |
| `background` | boolean? | Execution | Absent, null, or false only |
| `completed_at` | number? | Response-only timestamp | Finite nonnegative number or null; discard |
| `conversation` | object? (`id`: string) | Retention / state | Absent or null only |
| `created_at` | number | Response-only timestamp | If present, finite nonnegative number; discard |
| `error` | error object? | Completion | Null/absent only; provider errors reject |
| `id` | string | Response-only identifier | If present, string; discard |
| `incomplete_details` | object? (`reason` enum) | Completion | Existing completion/reason checks |
| `instructions` | string / input-item array / null | Model configuration | String, null, or empty array only; discard; nonempty item arrays unsupported |
| `max_output_tokens` | integer? | Execution / budget bound | Nonnegative strict integer matching request when nonnull |
| `max_tool_calls` | integer? | Tool configuration | Nonnegative strict integer or null; does not enable tools |
| `metadata` | string-to-string object? | User metadata / retention echo | Null or typed string map; discard contents |
| `model` | model ID string | Pricing / model configuration | Exact pinned GPT-5 nano snapshot only |
| `moderation` | input/output tagged objects? | Execution / modalities | Absent or null only |
| `object` | literal `response` | Envelope identity | Required exact literal |
| `output` | output-item array | Generated content / tools / modalities | Required bounded array; existing nested text/reasoning-only checks |
| `output_text` | string? (SDK convenience property) | Response-only content duplicate | **New:** string or null only; discard; never a fallback for nested output |
| `parallel_tool_calls` | boolean | Tool configuration | If present, exact false |
| `previous_response_id` | string? | Retention / state | Absent or null only |
| `prompt` | prompt-template object? | Model configuration / state | Absent or null only |
| `prompt_cache_diagnostics` | tagged union? | Response-only cache observations | Existing exact tagged shapes, finite enums and nonnegative strict counters; discard; not accounting evidence |
| `prompt_cache_key` | string? | Caching / routing identifier | String or null; discard |
| `prompt_cache_options` | object (`mode`, `ttl`, optional comparison ID) | Retention / cache policy | Absent or null only; new-model cache configuration unsupported |
| `prompt_cache_retention` | `in_memory` / `24h` / null (deprecated) | Retention | Absent, null, or `in_memory` only |
| `reasoning` | reasoning configuration object? | Model configuration | Existing finite config subset; no execution authority |
| `safety_identifier` | string? | Safety / routing identifier | String or null; discard |
| `service_tier` | service-tier enum? | Pricing / execution | Absent, null, or `default` only |
| `status` | six-state enum | Completion / execution | Required `completed` or `incomplete`; other states unsupported |
| `temperature` | number? | Model configuration echo | Finite nonnegative number or null; discard; never applied to requests |
| `text` | text-format configuration object? | Modality / model configuration | Existing plain-text format and finite verbosity only |
| `tool_choice` | enum / tool-selection object | Tool configuration | If present, exact `none` only |
| `tools` | tool array | Tools / billing / execution | If present, exactly empty |
| `top_logprobs` | integer? | Model configuration | Nonnegative strict integer or null; does not permit content logprobs |
| `top_p` | number? | Model configuration echo | Finite nonnegative number or null; discard; never applied to requests |
| `truncation` | `auto` / `disabled` / null | Execution / input accounting | Absent, null, or `disabled` only |
| `usage` | usage object? | Billing | Required fully validated nonnull usage; no guessed counters or unknown pricing dimensions |
| `user` | string? (deprecated) | Safety / caching identifier | String or null; discard |

Additionally, `store` is in the official response **example** and CreateResponse,
but not the resolved Response properties or SDK serialized field declarations.
Its existing legacy compatibility remains: if present it must be exactly false.
It is retention-sensitive, not harmless metadata. This gives **38 accepted
names**, all with existing or explicitly reviewed validation paths.

Fields deserving particular attention in current schema reviews include
`access_programs`, `completed_at`, `conversation`, `moderation`,
`prompt_cache_diagnostics`, and `prompt_cache_options`. All were reviewed here;
none was missing from the prior allowlist. This review does not claim an
introduction date for them. In particular, cache options specify a minimum TTL
and are not equivalent to the deprecated retention maximum. Nonnull cache
options remain unsupported, including on newer models. Adding a name to the
inventory never grants permission to use its feature.

## Fixed-vocabulary unknown-field diagnostics

`envelope/unknown_fields` now adds two fields:

- `unrecognized_fields`: sorted unique list selected only from the fixed reviewed
  names in `api_response_envelope.DIAGNOSTIC_FIELDS`.
- `other_unrecognized_fields`: boolean indicating that at least one name was
  outside that vocabulary. No such name, value, hash, identifier, or exception
  string is serialized.

The vocabulary includes the 38 reviewed names and five official CreateResponse
names deliberately **not** accepted in responses: `context_management`,
`include`, `input`, `stream`, `stream_options`. These can be named safely if
injected, but are rejected even with null or empty values. This distinction also
lets a future reviewed name be diagnosed without granting acceptance. A
regression simulates the old allowlist to check that `output_text` is safely
named. Arbitrary provider-controlled names never become diagnostic labels.
The same whitelist, exact shape, sorted uniqueness, and strict boolean checks
apply across helper IPC and budget audit records. Older five-field and seven-field
diagnostics remain valid. These additions do not disclose which field occurred
in a historical response whose diagnostic lacked names.

## Deliberately unsupported and unchanged limits

Unknown envelope properties always reject, including unknown financial,
retention, execution, or model settings. Unsupported documented configurations
remain rejected as listed above. Executable tools and non-text modalities,
unknown nested fields, annotations/logprobs, nonzero cache writes, new usage
counters (even zero/null), absent/null/malformed usage, and unexpected pricing
tiers remain rejected. Reasoning tokens remain a validated subset of output
tokens; no double billing. Nested checks have not been relaxed.

The $10/day and $100 lifetime ceilings, full-context reservation, broker guard,
credential isolation, no retries, unresolved-hold behavior, and live gates are
unchanged. HTTP 200 alone still cannot settle a request without validated usage.
No inference about real billing is made. If a future unsupported response is
encountered by a separately authorized operator action, review only the fixed
safe diagnostic and public schema; never enable raw-body logging to investigate.

## Offline evidence

`envelope-all-fields.json` is hand-authored synthetic data exercising every
accepted name; it is not a provider capture. Regressions cover absent/null/text
metadata, malicious instruction-looking text, invalid metadata types, all
request-only diagnostic names, unknown-name injection, mixed known/unknown names,
malformed diagnostic IPC, nested tool/modality and usage rejections, unpriced
cache writes, and a disposable unresolved reservation with one dispatch and no
retry. Existing cross-platform CI runs this suite normally and with `python -O`.
Final test counts and all six workflow outcomes are recorded in the draft PR.
