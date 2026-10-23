# Broker-bound observation planning (Sprint 6.13A)

This interface is offline and synthetic only. It cannot edit files, run tools,
approve a task, publish a PR, or dispatch a live model request. The operator-only
connectivity command and its output-isolation contract are unchanged.

## Architecture and versioned contract

`src/observation_planning.py` defines frozen, runtime-validated `Classification`,
`Provenance`, and `Decision` types. The schema is `observation-decision-v1`.
The entire model-authored JSON object must contain exactly these three fields:

```json
{"schema":"observation-decision-v1","disposition":"ready_for_review","reason_code":"review_required"}
```

The only supported pairs are:

| Disposition | Reason code |
| --- | --- |
| `ready_for_review` | `review_required` |
| `insufficient_context` | `missing_context` |
| `policy_blocked` | `policy_constraint` |
| `no_change_recommended` | `no_change_needed` |

The model may emit no other field, prose, URL, patch, file content, command,
tool argument, approval state, provenance or publication instruction. Unknown
fields, duplicate JSON keys, invalid types, unsupported versions/pairs,
incomplete/refused/fragmented responses and classifications over 256 UTF-8 bytes
are rejected. Existing controller validation rejects tool calls and unsupported
modalities before this parser is reached. Reasoning is validated and discarded.

The trusted adapter constructs a separate provenance object containing the exact
task/execution references, execution principal, claim digest, authorization digest,
source-manifest digest, task-content digest and budget request reference. Model
text cannot supply or override these fields. The typed decision pairs this
provenance with the untrusted classification; even `ready_for_review` is advisory.
`Planner.verify()` compares all provenance fields against current broker state
and rechecks authority before a trusted caller consumes an in-memory decision.
These objects are not signed interchange credentials. The controller process and
protected broker/budget stores remain trusted; a hash is not an independent grant.

The flow is:

1. Snapshot the claim; require the actual `Broker`, exact owned `claimed` state,
   matching principal, fresh approval, source revision/manifest, deadline and STOP.
2. Canonicalize the exact approved task (at most 1,024 UTF-8 bytes; reject rather
   than truncate). Keep it in `untrusted_task`, separate from fixed trusted policy.
   Do not interpolate task text into policy. The complete input is bounded by the
   existing 2,048-byte controller ceiling and existing 64-output-token profile.
   No source files or authorization records are included in model input.
3. Derive one deterministic 32-hex request ID from the exact claim and schema.
   Reserve the existing full-context worst-case budget durably, binding the exact
   request, trusted provenance and reviewed prices. Recheck authority before send.
4. Send only through an explicitly synthetic transport. Validate the existing
   strict response envelope and token accounting, then settle sanitized usage.
5. Recheck authority, parse the bounded classification through a fixed internal
   boundary, recheck authority again and construct the typed observation.

There is no generic response callback, response passthrough, model output in the
general-purpose receipt, new worker endpoint, background dispatch or CLI activation.
The adapter shares the controller's synthetic broker-authority checks and durable
reservation path. The grant and budget ledgers remain separate, conservatively
fail-closed stores; this sprint does not migrate live broker admission.

Freshness means the immutable authorized Git revision and manifest. Uncommitted
working-tree edits do not redefine that source; advancing HEAD, changing the
catalog/manifest, changing approval, losing ownership, expiry or STOP blocks
delivery. Untrusted task content cannot alter these checks.

## Accounting, retention and operator runbook

No observation is persisted. Only existing sanitized usage/cost receipts and
bounded trusted reservation references/digests enter the budget ledger. Raw input,
provider output, reasoning, credentials and task details are not stored. The
classification is in memory only, so restart cannot recover it from a receipt.

A completed duplicate is rejected without dispatch or observation replay. An
uncertain request or crash retains the durable reservation and blocks another
dispatch, including after restart. Invalid response envelopes/usage retain the
full hold. A valid envelope with an invalid observation is billed using its
validated usage but never delivered. STOP/revocation/expiry/source changes after
the response likewise allow accounting settlement and prevent observation delivery.
Never retry to recover a missing or rejected observation. Manual reconciliation
records accounting evidence only; it cannot authorize redispatch.

Use only temporary synthetic fixtures for this sprint:

```sh
python -m unittest discover -s tests -p test_observation_planning.py -v
python -O -m unittest discover -s tests -p test_observation_planning.py -v
make lint test
python -O -m unittest discover -s tests -q
```

The planning tests clear inherited credentials from the environment, forbid real
transport/helper invocation and socket connections, use local fixture sources
and isolated temporary ledgers, and supply only synthetic response bytes. Hostile
output tests allow only the existing trusted read-only Git inspection commands;
shell/commit/publication commands, model file writes and executable receivers
are fenced. Existing accounting crash/process-race tests also remain in the suite.
The broker workflow exercises the focused tests in both Python modes on Linux
and macOS. All six existing PR workflows remain applicable; the daily advisory
planner is dispatch-only and must not be activated by this sprint.

Do not run connectivity or inspect operational keys/ledgers for this demonstration.
Keep connectivity disabled and preserve existing unresolved operational holds.
Use the existing [controller recovery runbook](API-CONTROLLER.md#recovery) for
independently authorized operational accounting recovery. Neither this sprint
nor an observation authorizes that procedure or a new provider request.

## Independent requirements before any future live planning

Live planning requires a separate reviewed change and explicit operator approval
for the exact task, immutable source, permitted input data, model/pricing, request
profile, retention policy, budget and authenticated principal. A coding approval
or synthetic claim alone must not authorize live planning. Review prompt-injection
boundaries and data minimization before sending any task content externally.

Implement authoritative live broker admission with single-use dispatch intent,
fencing, STOP/freshness checks, budget coordination, restart/uncertain-response
recovery and credential isolation. Independently validate provider structured-output
compatibility and output-token sufficiency; this offline JSON-text contract is
not a claim that the pinned 64-token profile produces complete live decisions.
Require operational evidence for isolation, peer authentication, watchdog/network
controls and durable accounting before activation. Maintain the $10/day,
$100 lifetime and single-unresolved-reservation limits.

Live planning must remain observation-only. Executable tools, file editing, shell,
commits, independent QA and publication would each require their own separately
reviewed capabilities and admission controls. Manual publication approval and
disabled autonomous coding remain in force. No live inference, merge or deployment
is authorized or performed by this change.
