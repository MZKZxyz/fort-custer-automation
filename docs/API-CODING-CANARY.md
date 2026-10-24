# Supervised API coding canary — blocked draft

This change is a prerequisite, **not a completed live API integration**. It adds
a dedicated coding response contract and a synthetic broker-to-independent-QA
adapter. It does not route coding output through observation classification.

`python3 -m src.coding_canary readiness` reports the outstanding blockers.
`python3 -m src.coding_canary live` always exits 1 without constructing a
transport, opening credentials, initializing state or sending an API request.
There is no enable flag or environment override.

## Implemented boundary

`coding_contract` accepts exactly `{ "old": "...", "new": "..." }` as JSON.
The controller checks the pinned manifest and the exact one-file allowlist,
requires a unique source match, and reconstructs the complete candidate in
memory. The result must be identical to the original bytes except for 1–16
standalone `//` lines immediately before the unique `compile` declaration.
Multiline additions and replacements that retain indentation work. Block
comments, Unicode line-separator escapes and changes to executable bytes fail.
No model-selected path is opened. No model command is executed.

`replay_synthetic` accepts only the existing exact synthetic Broker type and
an already claimed, independently approved catalog task. It requires the narrow
comment instructions, syntax check and analyzer test suite. It consumes the
single-use startup intent before parsing a proposal, then uses the existing
handoff validation, source reconstruction and fresh disposable QA workspace.
Source, policy and approval freshness, expiry and STOP retain the existing broker
guards. Failures leave the existing startup/checking hold; there is no retry.
The structural byte-identity check is the task-specific comment regression;
the prototype-direction regression is inappropriate for this comment task.

This adapter creates only existing **synthetic** evidence. Its output never
confers live API, execution or publication authority. No operational policy,
approval, budget ledger or broker grant is changed by installation.

## Required evidence before finishing integration

The supplied checkout and shared workspace contain no saved Sol Low comment
response or exact tested request profile. The accessible prior chat exposes
experiment summaries and prototype edits, but not a successful comment response.
Do not manufacture a fixture or label a synthetic response as real-model output.

Obtain the exact model identifier and tested request parameters, reviewed pricing
and context ceiling, the successful saved comment response, and its pinned source
revision/manifest. Preserve provenance and a SHA-256 for the selected sanitized
fixture. No new inference is necessary to recover that evidence.

The following remain unimplemented and block acceptance:

- Separate terminal-authorized live coding admission and durable diagnostic events.
- Sol Low request validation and reuse of API receipt validation, budget reserve,
  settlement and ambiguous-outcome holds for that reviewed model profile.
- A replay using the saved real-model response and actual pinned analyzer source.
- Production failure evidence retaining complete safe QA diagnostics.

## Operator procedure for the first live canary

This is a gated procedure; stop at step 1 with this draft.

1. Verify that the blockers above have been resolved in a separately reviewed
   implementation and the real-response offline integration test passes. The
   current `live` entrypoint is intentionally non-operational.
2. Review the exact source SHA/manifest, one permitted solver file, comment-only
   instructions, syntax check, comment regression and existing analyzer suite.
   Use the existing catalog task preparation and controlling-terminal approval.
   Do not reinterpret historical approvals or reset single-use task identifiers.
3. Review the new coding admission's exact prompt/configuration/pricing/budget
   binding and maximum reservation. Require a separate terminal authorization
   for exactly one GPT-6.1 Sol Low request. Check every STOP path, expiry, source
   pin, unresolved execution hold and existing API budget before admission.
4. Only after that separate authorization, dispatch once through the existing
   credential-isolated controller transport. Give the model source text only:
   no tools, filesystem, credentials or publication receiver. Never automatically
   retry a consumed request, including a request with no visible response.
5. Settle validated usage even if authorization expires or STOP arrives during
   inference. Unknown accounting retains the full reservation. Reject delivery
   after STOP, expiry, source changes or revoked authorization. Preserve safe
   phase/validation diagnostics and full independent QA evidence; never log
   keys, arbitrary exceptions or sensitive raw provider responses.
6. Validate edits, rebuild in disposable execution and independent QA workspaces,
   and run syntax, comment-specific regression and the pinned analyzer suite.
   Any failure blocks completion. Audit the single consumed execution and request
   against the existing ledgers; reconcile uncertainty manually, without resets.
7. Stop after QA. Creating, merging or deploying an application PR requires its
   own separate publication authorization and is outside this canary.

## Local verification

Eleven new synthetic tests pass in normal and optimized Python. They cover
multiline comments, indentation preservation, executable edits, malformed JSON,
extra fields/files, source mismatches, STOP, expiry, failed analyzer tests,
single-use holds and the complete synthetic broker-to-QA path. API transport,
credential helper and publisher calls are fenced in integration tests.
`make lint` and `git diff --check` pass. These results do not establish the
required real-model offline replay or live API accounting integration.
