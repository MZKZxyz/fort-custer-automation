# Execution and billing modes: inspected 2026-10-22

`config/execution-modes.json` selects `chatgpt_subscription` as the intended initial
mode. Both profiles have `live_enabled:false`; the shared code gate also always
rejects live execution. Selecting a mode is an audit choice, not authentication,
entitlement verification, a deployment or authorization to consume usage.

| Mode | Authentication intent | Usage/billing control | Current blocker |
|---|---|---|---|
| `chatgpt_subscription` | Official Codex-managed ChatGPT sign-in | Stop on exhaustion/unknown failure; no purchase, paid refill or API fallback | No reviewed credential-free worker integration or subscription-only usage proof |
| `api_billing` | Separate API credential in a future trusted broker | Strict $10/Los Angeles day, $3/task, authoritative reconciliation and retained uncertain holds | Financial guarantee and live transport/reconciler unavailable |

One agent, 40 minutes, two retries maximum, independent QA and separate
dispatch/publication approvals apply to both. Exhaustion never triggers automatic
retries even within that ceiling. Existing dollar reservations are retained and
never relabeled as subscription invoices or zero-cost settlements. A future
subscription-aware ledger integration needs review.

## Official capabilities inspected

- [Authentication](https://developers.openai.com/codex/auth/): ChatGPT and API-key
  sign-in are distinct. Headless device authorization is documented, subject to
  account/workspace availability. Codex owns caching/renewal. A forced ChatGPT
  login method constrains authentication, not paid-credit consumption. Enterprise
  automation access tokens require separate permissions not assumed for this owner.
- [Non-interactive mode](https://developers.openai.com/codex/noninteractive/):
  `codex exec --json` supports headless work. ChatGPT-managed CI is an advanced
  trusted-runner path with restrictions, not a credential-free worker API.
- [SDK](https://developers.openai.com/codex/sdk/): TypeScript controls local Codex;
  Python controls local app-server with a pinned runtime. Neither makes this
  custom synthetic broker subscription-compatible.
- [App-server](https://developers.openai.com/codex/app-server/): structured usage
  errors and rate-limit observations exist. These are usage signals, not
  financial finality or a guaranteed per-task cutoff.
- Official [registered OAuth app-server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
  and [self-hosted VM](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
  guides describe their own application registration, credential/session handling
  and limitations. They do not authorize extracting a Codex login cache or sending
  its tokens through an arbitrary proxy. No registration or token transfer was attempted.

Local inspection ran only `codex --version`, `codex login --help` and
`codex app-server generate-json-schema --out TEMP_DIRECTORY`, with CLI **0.163.0**.
No login, login-status inspection, credential-file read, auth test or model turn
was performed. Public schema hashes are in the mode validation report.
Versioned [CLI event source](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/exec/src/exec_events.rs)
defines message-only `error`/`turn.failed` details; these cannot reliably identify
subscription exhaustion. The local app-server schema uses `usageLimitExceeded`
in `codexErrorInfo`, thread/turn identity fields and rate-limit windows.

## Implemented offline behavior and limits

`SubscriptionUsageMonitor` consumes supplied trusted-collector observations only.
It never connects, loads authentication, emits purchases or starts a model. It
recognizes structured app-server exhaustion and exhausted primary, secondary or
multi-bucket quota windows, and latches a stop. CLI failures, malformed data or
mismatched identities stop as unknown failures. Unknown quota never grants dispatch.
Successful turns or sub-100% snapshots do not prove entitlement, remaining task
capacity, no paid refill or a cutoff. Worker events cannot provide readiness proof.

The current worker denies credentials/network and uses a synthetic task-scoped
broker. Putting an authenticated CLI in the untrusted worker would break that
credential boundary; running repository commands beside trusted authentication
would break controller separation. No reviewed official transport connecting those
boundaries is implemented. Subscription activation stays blocked even if the owner
can log in on a trusted machine.

A future review requires official account/client support, isolated trusted Codex
execution, verified prohibition of paid-credit/refill consumption (including
pre-existing credits), no API/other-provider fallback, trusted usage/failure
collection, independent deadlines/cancellation and mode-specific ledger provenance.
Local configuration booleans are prohibitions, not proof of account billing controls.

No automated login, credit purchase, reset-credit consumption, refill, billing
enablement, credit-nudge email or API fallback is implemented. Do not copy/mount
auth caches into coding/QA guests, read tokens into this controller, set custom
OAuth bearer headers/base URLs or add subscription auth to ModelBroker.
