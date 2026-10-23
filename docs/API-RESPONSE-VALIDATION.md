# Second Responses validation investigation

The operator reports HTTP 200 and `response_schema_invalid` for local request
`afa8d02e954e4214aef599bd25365d02`. The POST reached OpenAI and a response
was received. This is different from a pre-dispatch failure, but **does not
establish the charge or exact rejected field**. The prior diagnostic collapsed
all nested checks into one category. No raw operator response, key or ledger is
available or needed for this offline change. The existing operational reservation
is not opened, reconciled, replaced, deleted or retried.

The new draft change is based on merged main
`5751a6635c63d84c44b2a349ed18c50a44b5e008`, verified tree
`7a3f12656dbece9df7ce0a5e903ec4c16d246fd5`.

## Official contract review and plausible mismatches

Every check in `_receipt` and its nested helpers was reviewed against the
[official generated Responses types](https://github.com/openai/openai-python/tree/main/src/openai/types/responses),
[reasoning configuration](https://github.com/openai/openai-python/blob/main/src/openai/types/shared/reasoning.py),
and [prompt-cache pricing/control documentation](https://developers.openai.com/api/docs/guides/prompt-caching).
Exact schema blob hashes and synthetic fixture provenance are in
[the fixture README](../tests/fixtures/responses/README.md).

The strongest concrete candidate is the now-documented
`usage.input_tokens_details.cache_write_tokens` field. The old exact-key test
rejected it even at zero. The reviewed usage schema defines it as an integer.
This field's presence could explain the observed HTTP-200 failure, but no
historical section/value evidence exists to confirm that it did.

Other plausible incompatibilities were explicit null metadata (particularly
`service_tier` and `background`), valid nonempty reasoning summaries/text,
and partially completed output items under a terminal incomplete response.
Conversely, missing/null usage details or nullable tokens are **not** accepted:
the usage schema requires integer counters and the accounting model cannot
safely reconstruct them from model text or absent fields.

## Exact policy and compatibility changes

| Section | Current accepted subset | Still refused / reason |
| --- | --- | --- |
| Envelope | JSON object, `object=response`, exact reviewed GPT-5 nano model, documented top-level fields | Oversize, duplicate/nonfinite JSON, unknown fields/model; no provider IDs are copied |
| Metadata | Documented nullable string/numeric/config echoes, dictionary of string metadata, plain-text instructions, plain-text format, typed reasoning config and cache diagnostics; all discarded | Invalid types, paid tiers, pro reasoning mode, nonempty conversation/prompt/access/tool state, new-model cache options or extended retention |
| Nullable execution echoes | `service_tier=null` and `background=null` mean unspecified response echoes; the original request still explicitly fixes default tier and `background=false` | `priority`/`flex`/other tiers or `background=true`; no inference from a response can override the request |
| Completion | Terminal `completed` or `incomplete`, `error=null`; optional/null incomplete details or reviewed reason enum | Failed/cancelled/queued/in-progress/null response status or provider error; HTTP 200 alone cannot authorize settlement |
| Usage | All five required fields; integer input/output/total; exact sum; input and output ceilings unchanged | Missing/null/malformed details, booleans/floats/strings, negative/excess tokens, inconsistent totals, unknown usage keys |
| Cached input | Required integer `cached_tokens` in `[0,input]`; optional documented integer `cache_write_tokens=0` | Nonzero cache writes lack reviewed pricing and retain the hold; unknown dimensions fail even at zero/null |
| Reasoning tokens | Required integer subset `[0,output]`; already included in output charge | Missing/null/wrong-type/excess reasoning tokens or extra output usage dimensions; no double charging or guessing zero |
| Output items | Bounded list of assistant messages and reasoning items; empty list allowed with complete usage | Function/custom/hosted/shell/computer/MCP tools, image/audio/other modalities and unknown item types |
| Item status | Documented nullable reasoning status; completed/incomplete items; `in_progress` only when outer response is terminal incomplete | Null message status or a partial item under a completed response; omitted nonfinancial IDs/status retain legacy compatibility |
| Message content | String output text or refusal, optional/null/empty logprobs; typed fields discarded | Missing/wrong-type text, annotations requiring unenabled tools, nonempty unrequested logprobs, new content types or unknown fields |
| Reasoning output | Typed `summary_text` summaries, optional/null typed `reasoning_text` lists, nullable/string ciphertext | Unknown nested shapes/fields or wrong types; all accepted content is discarded, never decrypted, replayed, displayed, audited or executed |

Recognizing zero cache writes is not a new price assumption: zero contributes
no charge. Nonzero writes require a separate reviewed price model and are
explicitly rejected. Unknown pricing dimensions are never silently ignored.
Actual cost remains `(input-cached)*input_rate + cached*cached_rate +
output*output_rate`; reasoning is a subset of output. Success receipts contain
only the prior sanitized usage, estimated cost, reviewed model/pricing and fixed
status/retry/tool-execution fields. No model response content or provider ID is
returned. There is no change to the request, max output, reservation formula,
$10/day budget, $100 lifetime ceiling, credential helper or broker guards.

This is a reviewed text-only profile, not acceptance of every Responses API
capability. For example, an API-valid response containing images, tool calls,
unknown billing dimensions or stateful continuation still fails closed.

## Safe section diagnostics

The existing category/phase/dispatch/HTTP-status diagnostic now optionally adds
**paired, fixed-vocabulary** `validation_section` and `validation_rule` labels:

```json
{
  "category": "response_schema_invalid",
  "phase": "response_validation",
  "dispatch": "response_received",
  "http_status": 200,
  "parameter": null,
  "validation_section": "cached_tokens",
  "validation_rule": "cache_write_not_priced"
}
```

Sections include envelope, metadata, completion, usage, cached tokens, reasoning
tokens, output, message, content and reasoning. Examples are
`usage/total_mismatch`, `reasoning_tokens/token_bounds`, and
`output/item_type`. Unexpected validator implementation errors use
`internal/unexpected_validation_error` without printing an exception. Section
and rule values are **never constructed from provider keys, values, item indices,
identifiers, raw usage values, text, reasoning, ciphertext or credentials**.
No raw response hash or debug dump is added. The preexisting local budget request
ID remains separate for local audit correlation; provider identifiers never enter
these additions.

The IPC and budget audit validators accept both prior five-field diagnostics
and the new seven-field form. Unpaired/unknown section labels cannot reach the
audit. New validation errors append the sanitized diagnostic through the existing
`request_failed_hold_retained` event; they never settle or modify a reservation.
An existing old audit record cannot retroactively identify which field failed.
No budget schema migration or reset is needed. Missing audit-write evidence
continues to produce `audit_recorded=false` and preserves the hold.

## Offline evidence and boundaries

Four hand-authored schema-derived JSON fixtures exercise completed, nullable
metadata, incomplete and reasoning output structures. They are **not captures**
of operator traffic. All fixture text, IDs, timestamps and ciphertext are
synthetic. Regression mutations cover every section, malformed counters,
nonzero/unknown charge dimensions, unexpected tools/modalities and data-leakage
attempts. They also prove structured IPC/audit propagation and exact unresolved
hold preservation in a disposable fixture using the operator-supplied UUID.
No real operator ledger is accessed.

Initial targeted verification: **21/21 validation tests pass**, zero skips,
**0.034 s**; existing **37/37 API controller tests pass**, zero skips,
**3.979 s**. Normal and optimized validation tests run on both hosted Linux and
macOS in the existing broker workflow. Combined API suites also pass **58/58**, zero skips, normal **4.436 s** and
optimized **6.458 s**. Infrastructure lint, compilation and whitespace checks
pass. Full regressions and all six workflow results are recorded in the draft
PR's final validation report.

No credentials or live API requests are used in Codex or CI. Connectivity and
live coding remain disabled. The real request remains held. Preserve its audit,
verify finalized billing for the correct project/model/time window and establish
helper termination before separately authorized manual reconciliation, following
[the operator recovery procedure](API-CONTROLLER.md). Do not infer zero cost from
HTTP 200 or a temporarily empty usage dashboard. Reconciliation does not
authorize a retry, and none is performed by this change.

Remaining uncertainty: without the historical response or section labels, the
exact cause of this particular rejection cannot be proven from the reported
category. The known schema mismatches are fixed offline; actual live compatibility
is not claimed. A future separately authorized request, after proper resolution
of the hold, will expose only the safe section/rule if another incompatibility
remains. Nonzero cache writes, new pricing dimensions, new metadata capabilities,
unsupported modalities and nonterminal/missing usage remain blocked for review.
