# Spending controls: inspected 2026-10-22

Scope: the dollar ceilings and financial reconciler below apply to `api_billing`.
The separately disabled `chatgpt_subscription` profile uses official ChatGPT
entitlements only in a future reviewed integration, never paid refills/API fallback.
Subscription quotas do not prove a per-task cutoff, a dollar cap or final charges.
See [subscription investigation and blockers](SUBSCRIPTION-EVIDENCE.md). Existing
ledger holds are preserved; no subscription event can finalize them as a zero bill.

## Sprint 5.5 documentation update

The current [project management documentation](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform)
now describes monthly organization/project spend limits with an enforce option.
It explicitly describes non-instantaneous enforcement and possible overshoot.
This updates the earlier API-schema-only capability assessment below: absence
of a budget endpoint in the inspected schema does **not** establish absence of
dashboard enforcement. The documented monthly control still does not establish
the required strict $10 per Los Angeles day or $3 per task bound.

The [prepaid billing documentation](https://help.openai.com/en/articles/8264644-setting-up-and-managing-prepaid-api-billing)
describes delayed cutoff and possible negative balance. Prepaid credit and
auto-recharge limits cannot provide the required instantaneous financial bound.
The [Usage/Costs API reference](https://platform.openai.com/docs/api-reference/usage)
distinguishes token activity from invoice-reconciling Costs, with paginated
time buckets/project attribution. It is a reconciliation input, not a spending
cutoff or per-execution atomic invoice. No billing/admin credentials were used.

Observed 2026-10-22. No account-specific contract, bounded overshoot guarantee,
strict daily/task hard cap, finality SLA or fully attributed financial reconciler
was established. The financial readiness gate remains blocked. No policy values
were changed and no paid request was invoked.

**Live dispatch remains unconditionally blocked.** No paid API was called and no
provider account settings were changed. The strongest arrangement established in
this sprint is the existing transactional $3 reservation / $10 daily accounting,
one active task, two retries, nonrenewable 40-minute deadline, retained unresolved
holds, and the unconditional `require_live()` gate. This enforces zero live spend
through this system. It does not enforce a provider dollar cap after activation.

## Evidence inspected

The public [OpenAI API schema](https://github.com/openai/openai-openapi/blob/main/openapi.json)
was retrieved on 2026-10-22 (Git blob `8a37b0686d16cc9d007c97b8353f89d1923791d5`,
file SHA-256 `5d916f45a719670bd5de24ce2b26bce22b0caffce4402e7ed21589d8ccd67531`).
This is API capability evidence, not an assertion about account-specific contracts.

- `GET /organization/costs` requires an admin API key and supports daily buckets,
  project/API-key grouping and pagination. It offers aggregate cost reporting;
  its schema provides neither a task-level final invoice nor an atomic dollar
  cutoff. An admin key belongs only in a dedicated billing reconciler.
- `GET /organization/usage/completions` offers usage aggregation. The Codex CLI's
  `turn.completed.usage` is token telemetry. Neither is a final bill.
- `POST /organization/projects/{project_id}/rate_limits/{rate_limit_id}` supports
  requests/minute, tokens/minute, some requests/day, and other model-specific
  throughput limits. The inspected request schema has no dollar-limit field.
  RPM/TPM quotas are useful defense in depth, but are not the configured $3/$10 cap.
- No budget mutation / hard dollar cutoff endpoint was found in this schema.
  A dashboard budget, prepaid balance or billing alert must not be assumed to
  stop charges exactly at the configured ceiling. No account-specific guarantee
  was available in this environment. Provider documentation/account terms must
  be checked by the operator before accepting any stronger claim.

## Four distinct accounting records

| Record | Meaning | Can release a live hold? |
|---|---|---|
| Local estimate | Versioned price × predicted/observed tokens | No |
| Reported token usage | Collector-attested provider execution counters | No |
| Confirmed billable usage | Authoritative complete attributed financial record | Only after a reviewed reconciler exists |
| Provider-enforced spending limit | Atomic provider refusal or audited bounded broker controlling every request | Prerequisite for activation; not supplied here |

A future broker must exclusively hold model authority, atomically reserve each
request's conservative worst-case billable charge before sending it, cover input,
cached/reasoning/output/tool/failed-request charges, disallow unknown-price models,
limit output and retries, persist ambiguous in-flight holds through crashes, and
ensure all access routes use the broker. Reconciliation must bind execution IDs,
project/key attribution, currency, pricing version, pagination, complete time
windows and finality. A self-reported `verified: true` field is insufficient.
Do not implement a token polling loop as a substitute for these guarantees.

Activation needs a separately reviewed provider contract or audited broker proof
that bounds each task to $3 and all tasks to $10 per America/Los_Angeles day,
including cross-midnight unresolved holds and delayed billing. Until then the
live verifier in `metering.py` rejects all evidence. Synthetic rehearsal billing
is explicitly labelled and accepted only by a synthetic ledger.
