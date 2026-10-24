# Sol coding response cache compatibility

The Sprint 6.14 `_metadata()` check permits a nonnull deprecated
`prompt_cache_retention` only when `request['model'] == MODEL`, where `MODEL`
is the GPT-5 nano snapshot. Consequently Sol `in_memory` echoes fail with
`metadata/cache_policy`. Sol already accepts the exact `prompt_cache_options`
object `{"mode":"implicit","ttl":"30m"}`. The correction permits `in_memory`
for the exact dedicated Sol coding payload and bounds the existing options
exception to that same profile, replacing the overly broad `model != MODEL`.
Absent/null metadata remains accepted; `24h`, longer TTLs, explicit caching,
comparison IDs, unknown nested keys and malformed values remain rejected.
This response compatibility does not add request cache controls or change pricing.

The reported execution `d4d25e5cc5574e70a0ce7651b7e76517` reached HTTP 200
and failed at metadata/cache_policy. That diagnostic identifies the rejecting
rule, not the returned value. All new response cases are synthetic; none is a
capture of the consumed response. We do not know its actual cache retention,
usage, provider response ID or final billable amount.

## Parser and authority review

The response model must exactly match a reviewed request model. Sol uses its
own context limit, required cache-write counters, bounded usage and reviewed
pricing; nano keeps its original limits and rejects nonzero cache writes.
Reasoning effort accepts a finite subset (including Sol low), and output remains
text/reasoning only. Unknown top-level fields are discarded by the existing
projection; authoritative nested structures remain strict. No other parser
contract is relaxed here. Unsupported future model echoes can still fail closed.

`Controller._request` validates the receipt before settlement and delivery.
Schema failure retains the hold and raises before `visible_edit` or contract
application. A valid incomplete response may be billed, but `visible_edit`
requires completed response/message status and no incomplete details before
returning an edit. The canary applies the narrow comment contract and runs
independent QA before recording `validated`. Guards still check terminal
authorization, STOP, expiry, principal and source binding. Dispatch consumes the
single coding attempt; failure and reconciliation do not authorize another.
Regressions fence patch application on invalid/incomplete responses and verify
the second grant remains blocked.

## Existing budget evidence and recovery limitation

This review inspected ledger implementation, not production ledger files.
`Budget.reserve` records local request ID, binding, maximum, pricing, model
configuration, prompt digest and execution provenance. `record_failure` appends
only the fixed diagnostic. HTTP 200 plus a local reservation is not usage or
billing evidence. The transport returns response bytes without retaining provider
request/response identifiers; `_metadata` discards response IDs and invalid
receipts never reach settlement. The append-only audit therefore cannot recover
the rejected response's usage or independently link it to a provider bill.
The reported 5,310,000,000 nano-USD is a conservative reservation, not actual cost.

Safe manual reconciliation requires independently retained provider evidence
linking this local execution/request and its dispatch time to the correct
provider account/project and request/response ID, plus final billed usage or
charge (including cached input, 30m/12h cache writes, output/reasoning inclusion,
service tier, model, pricing and long-context multipliers). A verified provider
no-charge outcome is also evidence; a validation failure alone is not. Any
external evidence digest must identify a retained, reviewable artifact, not an
invented receipt. If request-level linkage is unavailable, obtain provider
confirmation; do not infer zero cost or use aggregate account usage alone.

The existing operator reconciliation interface can record an amount and evidence
digest, but cannot verify their provider origin or sufficiency itself. No new
recovery command, ledger migration, hold release, settlement or grant bypass is
introduced. Keep the unresolved reservation and consumed coding attempt intact.
No inference request, replay, production ledger access, application code
publication or deployment was performed for this change.
