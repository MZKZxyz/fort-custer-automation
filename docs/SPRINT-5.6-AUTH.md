# Sprint 5.6 authentication investigation and blocked architecture

Inspected 2026-10-22. Automation base: `d3bd430ce543e0373c93579de78aa59bb524b87e`,
tree `e4361c7bde46de2a5589365b6368029a592526d1`. The retrieved source tree was
reconstructed through the GitHub connector and verified with `git write-tree`.
The preexisting local checkout was Sprint 5.2 and was left intact.

**Live subscription integration remains unimplemented and blocked.** This sprint
adds an offline boundary experiment, not an OAuth implementation or deployment.
No login, auth-cache read, live app-server process, model turn, paid usage or
client/server write was performed. Existing `chatgpt_subscription` selection,
disabled profiles, API financial policy and operational planning ledger are unchanged.

## Evidence and unresolved documentation

All five requested official pages were attempted through the managed network on
2026-10-22. Every request failed before HTTP with `URLError: Operation not permitted`;
`curl` also reported that the configured proxy at port 8080 was unreachable.
No page contents were retrieved. The runtime reports restricted networking and
network policy state `unknown`, not verified enforcement. These failures prove
an environment access limitation, not an OpenAI feature restriction.

Required follow-up sources:

- [Sign in with ChatGPT quickstart](https://developers.openai.com/siwc/quickstart)
- [Registered application / Codex app-server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Workload identity federation](https://developers.openai.com/api/docs/guides/workload-identity-federation)
- [Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform)

Sprint 5.5's [subscription evidence](SUBSCRIPTION-EVIDENCE.md) is historical context,
not a substitute for reading current eligibility/preview restrictions. Registration
availability, allowed deployments, scopes, callback rules, offline/refresh grants,
revocation semantics, SDK/runtime versions and subscription-only billing behavior
remain **unverified** for this application. No invented OAuth URL, grant or scope
is used. No claim is made that registered-app support is universally unavailable.

Local non-inference commands were `codex --version` and
`codex app-server generate-json-schema --out /tmp/fc56-schema`. Installed CLI:
**0.163.0**. Generated schema fixtures and SHA-256 manifest are committed in
`tests/fixtures/app-server-0.163.0/`. Six public sentinel protocol messages were
validated against these schemas with the locally available `jsonschema` package;
CI has standard-library fixture integrity/required-field regressions and no
runtime Codex dependency. The simulator is not a full protocol conformance suite.

A material finding in `LoginAccountParams.json`: the `chatgptAuthTokens` variant
is explicitly described as **“[UNSTABLE] FOR OPENAI INTERNAL USE ONLY - DO NOT
USE.”** Presence of fields in a generated schema does not establish permission
to use them. This variant and its refresh mechanism are not used. Future official
registered-app documentation may specify a different supported runtime/path;
review and pin that path before implementation.

## Four mechanisms, separate authority

| Mechanism | Entitlement / principal | Process holding credentials | Deployment conclusion |
|---|---|---|---|
| Official Codex ChatGPT login | Codex subscription sign-in, distinct from an API key; installed schema exposes `chatgpt` and device-code variants | Trusted official Codex process and its protected auth store | Potential unattended work after explicit human login depends on current account/client policy. Running authenticated Codex in an untrusted coding VM violates this project's credential rule. Headless support alone does not resolve isolation. |
| Sign in with ChatGPT for eligible applications | Application registration, operator OAuth consent and application-specific eligibility must be established | Future trusted registered-app broker/secret manager only | Candidate path; exact supported grant/scopes/callback/runtime and preview/deployment eligibility unverified. No activation or token-sharing workaround. |
| API billing | Separate API credentials and separately billed usage | Future trusted API model broker | Existing `api_billing` profile remains disabled, with $10/day and $3/task requirements unchanged. Never a subscription fallback. |
| Workload/workspace identity federation | Workload identity trust/configuration and resource authorization, where officially supported | Federated workload/identity agent for its explicitly authorized resource | No evidence it grants this operator's ChatGPT subscription. Treat as a separate integration; verify issuer/audience/principal/resource and billing in current docs. |

A normal ChatGPT login never establishes arbitrary third-party Responses API
authority. Neither an API key nor federation proof establishes subscription
eligibility. Login success or quota snapshots do not prove paid-refill prohibition.

## Required future trust topology

Human authorization -> trusted eligible application broker -> supported Codex
app-server control channel. The broker alone may read its secret-manager tokens.
The controller sends one authenticated, approved task binding. Coding and QA VMs
receive neither OAuth/API credentials nor general network/provider endpoints.
GitHub App identities and dispatch/QA/publication approval identities stay separate.

The broker must validate authorization state, consent, issuer/audience, expiry,
account/workspace identity and exact applicable scopes using the supported flow;
rotate tokens atomically and bind refresh to the same account. Revoke sessions and
cancel/fence execution on expiry, revocation, unknown refresh outcome or account
change. Never put token responses, auth URLs with sensitive parameters or raw
provider errors in logs, worker output, CI artifacts or repository files.

A future narrow tool channel must derive the worker VM principal from authenticated
vsock/mTLS; bind execution/task/repo/source, a reviewed model and operation allowlist,
fixed scope, one concurrent turn and the original 2400-second deadline. It must
route bounded tool requests to the isolated coding VM, validate paths and output
sizes, reject secret access/network/general shell in the broker, and preserve
cancellation/kill-switch state across restart. QA remains a fresh independent VM
at the exact candidate SHA. App-server local repository shell/filesystem execution
inside the credential holder is prohibited. Merely declining approval prompts is
not proof that all local tool paths are disabled.

No supported remote-only tool transport meeting this topology has been verified.
Accordingly **no authenticated app-server is launched**, no local repository code
runs in a credential holder, and no live bridge factory can return a transport.
Independent token-isolation and transport receipts remain mandatory, along with
the preexisting VM, watchdog, QA, GitHub, approval and release gates.

## Offline experiment and subscription stops

`subscription_harness.py` accepts only exact fake OAuth/provider classes. Its public
sentinel credential and `fixture:codex` scope are **invented test fixtures**, not real
OAuth tokens or claimed official scopes. It models consent/state/account/expiry,
rotation/revocation, one approved execution and one bounded investigation turn.
No URL, HTTP client, subprocess, OAuth exchange or real token parser exists.
Only fixed metadata/zero synthetic usage are stored in its separate SQLite audit;
raw worker input and app-server text/tool requests are never returned or logged.

A pending/uncertain admission survives controller or broker restart and keeps its
exclusive hold, even after deadline or cancellation. Replays fail. Revocation,
deadline or cancellation during a response cannot report success. The synchronous
fake does not implement real process interruption: independent provider cancellation,
host watchdog and wall-clock termination remain deployment blockers.

The existing usage monitor recognizes `usageLimitExceeded` and exhausted rate-limit
windows. Unknown errors, malformed/mismatched messages and unexpected tool or text
requests stop. Exhaustion never buys credits, consumes reset credits, enables paid
refills, switches provider/profile or retries automatically. No subscription quota
is described as a guaranteed per-task dollar ceiling. Production usage/audit
collection and subscription-only account controls remain unverified; synthetic zero
usage is not a billing record or a readiness receipt.
