# Sprint 6.12 connectivity diagnostic investigation

No real API request, credential access, retry or operational-ledger access was
performed. The operator's request `33f477e596b0473b9c020ef32d69a505` and its
20,006,400 nano-USD unresolved reservation remain untouched. Tests using that ID
use newly created disposable SQLite fixtures only.

Baseline: merged Sprint 6.12 main `860ccdc7127e12b17b65049bfb0f80f809797a5a`,
tree `4def6bc904c768f137862b96f907363e9384ac9f`. The local checkout exactly matches
that tree. The new draft PR is parented to actual main, not to the reconstructed
local Git history.

Inspection covered `_http_child`, `ResponsesTransport.send`, `payload`, `receipt`,
`Controller._request`, CLI exception handling and reservation/reconciliation.
The previous CLI suppressed every failure into the same message. It cannot now
be established whether the historical attempt failed locally, received an HTTP
rejection, timed out after dispatch or received an incompatible success schema.
Zero dashboard usage after minutes is not sufficient billing evidence.

Official generated schema blobs inspected:

- Request parameters `90154795ba355792269f9b51d860b7058d55cd68`.
- Reasoning item `8744204522b660d0ec5bb1506ee2b983ba7b88de`.
- Message item `d041df641539525582f8e4ddcaa861bb88e81695`.

The Responses request uses supported GPT-5 nano minimal reasoning and standard
text-only fields; the fixed 16-token request is within the documented minimum.
The generic builder previously permitted unsupported limits below 16 and now
rejects them offline. No fallback, parameter removal, model change, increased
budget/output limit or additional inference is introduced.

A concrete response compatibility defect is repaired: documented empty/null
reasoning content and opaque encrypted reasoning fields were rejected by the
old strict allowlist. Those known fields are now type-checked and discarded;
nonempty visible reasoning, unknown fields, tools and invalid usage remain
rejected. This explains a possible failure path, not the actual cause of the
historical operator attempt. All raw provider output and sensitive exception
strings remain private to the trusted process and are never logged or audited.

Diagnostics distinguish credential/local preflight and explicit pre-POST connect
failures, confirmed HTTP statuses/rejections, response JSON/schema validation and
ambiguous transport/helper failures. Only finite diagnostic enums, HTTP integers
and allowlisted parameter names can cross diagnostic IPC or reach CLI/audit.
HTTP 400 unsupported-parameter metadata is parsed from at most 8 KiB without
copying its message, arbitrary code, raw body or headers. HTTP status survives
an unreadable error body. No error path settles, deletes or retries a reservation.
Diagnostic recording appends evidence only; it does not alter request rows.

Offline verification at the initial diagnostic checkpoint: **35 tests pass**,
zero skips, **4.059 seconds**. Coverage includes malformed credential bytes,
private files, 400 unsupported parameters, 401/403/404/429/5xx/redirect statuses,
connect/TLS failures, request disconnects, timeouts before/after observed HTTP
200, helper launch/loss/deadline, invalid IPC diagnostics, malformed JSON and
unknown response fields, known reasoning metadata, redaction, exact reservation
row preservation and refusal to dispatch while an existing hold remains.
Final local and hosted checks are reported in the draft PR validation outcome.

[API-CONTROLLER.md](API-CONTROLLER.md) contains the operator-only recovery
procedure. It requires finalized matching project/time/model billing evidence
and helper termination before explicit manual reconciliation. The current
operational hold is not retroactively classified or released. Live broker
admission, executable tools, live coding, automatic approval, merging and
deployment remain disabled.

Final targeted suite: **37/37 pass**, zero skips, normal **4.464 s**, optimized
**5.543 s**. Additional tests prove that a broken diagnostic pipe cannot surface
an active sensitive exception as a child traceback, and distinguish helper
construction failure from an ambiguous start attempt. Infrastructure lint,
compileall and diff whitespace checks pass.
