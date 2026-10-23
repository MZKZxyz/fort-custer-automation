# Draft: observed Responses compatibility and supervised 256-token connectivity

The operator-observed HTTP 200 incomplete response was rejected because the
reviewed envelope omitted `frequency_penalty`, `presence_penalty`, and
`tool_usage`. Accept finite penalty echoes and the exact reviewed zero-only
image-generation/web-search metadata, then discard them. Unknown categories,
unknown nested dimensions, malformed counters, and nonzero activity fail closed.
No tool execution or additional billable usage is inferred from metadata.

The synthetic observed-response fixture passes the production receipt validator
with incomplete status, zero usage, zero estimated charge and no persisted model
content or reasoning. It contains no real IDs, timestamps or provider ciphertext.
This test is not independent provider billing evidence.

The operator-only fixed connectivity profile uses 256 output tokens and reserves
20,102,400 nano-USD ($0.0201024). The synthetic worker limit remains 64 tokens.
The pinned model, `Reply with OK.`, minimal reasoning, no tools, `store=false`,
no retries, $10/day, $100 lifetime, and one outstanding request are preserved.
STOP, grants, credential isolation and disabled live execution gates are unchanged.

Validation: targeted API tests, full normal and optimized regression suites,
lint and whitespace checks. Exact counts, skips and CI results are recorded in
`RESPONSES-COMPATIBILITY-TEST-RESULTS.md`. Existing regressions retain strict
usage/pricing checks, hostile metadata rejection and durable reservation recovery.

Live API connectivity has not been validated. No live inference, existing-request
access, reconciliation, retry, merge or deployment occurred. A future operator
connectivity test requires separate authorization and proper reconciliation of
outstanding holds. See `RESPONSES-OBSERVED-COMPATIBILITY.md` for the runbook,
limitations and security assumptions.
