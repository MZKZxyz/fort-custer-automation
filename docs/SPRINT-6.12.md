# Sprint 6.12 — Trusted API and budgeted execution

Delivers a bounded Responses REST client, durable local accounting, fake-transport
broker integration, strict synthetic tool contract, and disabled-by-default
operator connectivity command. No real API request, key inspection or live coding
is part of development or CI. See [controller operations](API-CONTROLLER.md) and
[exact evidence](SPRINT-6.12-EVIDENCE.md).

| Requirement | Delivered / boundary |
| --- | --- |
| Trusted client | Fixed official Responses endpoint, reviewed GPT-5 nano snapshot, trusted credential helper, hard deadline and zero retries |
| Budget | $10/day, $100 lifetime, one unresolved request; atomic local SQLite reservations and explicit operator reconciliation |
| Grant bindings | Actual existing synthetic Broker checks task, principal, source, fence, STOP and expiry; hashed prompt/config/tools and reservation provenance |
| Function interface | Strict manifest-bound synthetic file proposal only; all executable receivers refused |
| Activation | Two explicit operator switches, fixed harmless prompt, 16-token limit, sanitized receipt |
| CI | Fake HTTPS and synthetic responses, spawn-process races/crash recovery, normal and optimized tests on Linux/macOS |
| Coding canary | Same server revision/task/allowlist and independent direction-vector oracle; no application edits |
| Live integration | Incomplete and explicitly blocked; zero live workers, no legacy bypass |

The model cannot grant execution authority. No new approval, publication,
merge or deployment path is enabled. The connectivity exception is strictly
non-executable and cannot be used with task prompts or tools. The production
coding integration requires separately reviewed authoritative live broker
admission/migration, isolated tool receiver, isolated independent QA,
external termination watchdog and human-authorized publisher intake.

Operational assumptions include trusted OS/controller/configuration, protected
external credentials and durable ledger, correct time, current reviewed pricing
and exclusive use of one operational ledger. This is not an organization-wide
billing limit. Configuration does not refill credits or enable automatic top-ups.

All command examples and recovery semantics are in [API-CONTROLLER.md](API-CONTROLLER.md).
Read-only readiness is `python3 -m src.api_controller readiness`.
