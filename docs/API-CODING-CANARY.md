# Supervised Sol Low coding canary

The first canary is restricted to adding comments immediately above `compile()`
in `tools/maze-analyzer/solver.js` at source commit
`c4f480abb309a7a4d141b20ab462552a868ef0e3`. The implementation has no model tools,
filesystem receiver, GitHub credentials, publication receiver or automatic retry.
It does not use the observation classifier. Installation and tests send no API
requests. Shipped examples are disabled.

## Real capture and offline replay

`tests/fixtures/coding/real_sol_low_comment.json` is the uploaded Experiment 8
sanitized capture, preserved byte for byte. Its SHA-256 is
`af0f2f5c66f10b5763de321f35486d11eb59f9c530d435c03e43ef647f9ed211`.
The fixture's model/effort, source commit, permitted file, completed status and
request profile are checked. The exact `old` text occurs once in the pinned
source; its `new` text adds one comment and preserves every executable byte.
The fixture is user-attested real-model evidence, not a cryptographic proof of
provider origin. Its `capture_sha256` references an unavailable original capture;
we cannot independently recompute that digest. We pin the supplied sanitized
file separately and do not alter or silently reinterpret that provenance field.

`source-objects.json.gz` contains the complete 33-file source tree, its tree
objects, and original signed commit, retrieved read-only through GitHub. Every
object is verified against its Git SHA before import into a temporary repository.
The root tree is `9015875cca2b85a845f7168ba237c5935e86445c`; the reconstructed
commit is the exact source SHA above. A shallow boundary excludes unavailable
parent history. Tests require no network, downloaded dependencies or API key.
The working application repository is never changed.

Run the real capture through the same coding receiver and independent QA used
by live execution, with a deterministic mock Responses envelope:

```sh
python3 -m unittest discover -s tests -p 'test_coding*.py' -q
python3 -O -m unittest discover -s tests -p 'test_coding*.py' -q
```

The saved edit and usage are real; the outer Responses envelope in tests is
explicitly synthetic. Fixture metadata never grants authority. Tests separately
prepare and approve a fresh task using the existing runner and obtain a separate
coding authorization with a mocked terminal. Production has no such bypass.
Transport, helper, socket connection and publisher calls are fenced in these tests.

## Authority and execution

The existing catalog grammar now recognizes exactly one additional resource
profile: `supervised-sol-low-one-request`, with `api_spend_cents=531`, the exact
source/file/instructions above and exactly the existing syntax/analyzer checks.
It requires a new task and terminal approval. Historical subscription tasks keep
their original zero-spend meaning and cannot enter this paid coding receiver.
The subscription CLI rejects the new resource profile; there is no fallback.
The source-edit allowlist is unchanged.

`CodingBroker` uses a separate append-only `grant-broker-v3-live-coding` ledger.
It reads the existing approved task without rewriting its approval record. The
separate terminal challenge binds the full coding prompt, source manifest,
principal, model parameters, API configuration digest, pricing and reservation.
Only one canary may ever be authorized in this installation. Revoke, expiry,
failure and restart never make its task/execution reusable. Existing broker
protocols and their grants cannot be imported or used here.

A durable `dispatched` event precedes budget reservation and transport. A crash
at any subsequent point consumes the attempt even if no network request was
sent. Fresh guards check the task, policy, source HEAD/manifest, principal, STOP,
API configuration and deadline before admission, reservation, transmission,
delivery and finalization. Request IDs derive from the claim identity; neither
the claim token nor credentials enter the model prompt.

Edits must be exactly `old` and `new` strings. Validation requires a unique exact
match, the pinned full-source manifest and the one-file allowlist. Candidates
must preserve all original bytes except 1–16 standalone `//` comment lines
immediately above `compile`. Multiline comments and indentation-preserving
replacements work. Unicode line escapes, executable changes, added files and
mode changes are rejected.

The trusted runner reconstructs the candidate in a fresh disposable QA workspace
and runs diff validation, pinned Node syntax checking, the unmodified analyzer
suite, and a controller-owned compile regression covering dimensions, endpoints,
items/fire bit masks and invalid input. No model-produced test report is trusted.
The existing supervisor limits duration/output, terminates descendants and uses
an allowlisted environment without credentials. The model itself receives only
text through the API; all executable application/test bytes are pinned and
unchanged. This is local trusted-source QA, not a new general-purpose sandbox
for arbitrary model-generated executable code. It must not be extended to such
code without independent execution-isolation review.

## Reviewed API profile and accounting

Reviewed against official OpenAI documentation on October 23, 2026:

- [Sol model specifications](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [API pricing](https://developers.openai.com/api/docs/pricing)
- [Prompt caching and write billing](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Reasoning and output billing](https://developers.openai.com/api/docs/guides/reasoning)
- [Responses request parameters](https://developers.openai.com/api/reference/resources/responses/methods/create)

The profile uses `gpt-6.1-sol`, low reasoning, 4,000 maximum output tokens,
`store/background/stream=false`, no tools, `tool_choice=none`, no parallel tool
calls, disabled truncation and explicit `service_tier=default`. The last field
pins the documented standard tier; all other fields match Experiment 8.
Prompt input is capped at 24,000 UTF-8 bytes and the serialized request at 32 KiB.
The model context ceiling is 1,050,000 tokens; its output ceiling is 128,000.
No inference was used to verify documentation.

Standard global rates per million tokens: input $2, cached input $0.10,
default 30-minute cache writes $2.50, output $10. Above 272,000 input tokens,
input/cache rates double and output is multiplied by 1.5 for the entire request.
Reasoning tokens are already included in output usage and are never charged a
second time. Cache writes replace the ordinary input rate rather than adding a
surcharge. With no cache controls/breakpoints requested, the documented implicit
cache lifetime is 30 minutes. Twelve-hour writes, unknown usage dimensions or
unsupported tier/cache metadata fail closed with the full hold retained.

Admission reserves **$5.31**: the full model context at the long-context 30-minute
write rate, plus 4,000 output tokens at the long-context output rate. This
conservative bound avoids tokenizer estimates and does not assume cache hits or
short-prompt rates. The saved 517-input/43-output response costs **$0.001464** under
these rates. This reuses the existing Budget reserve/settle/failure controller
and existing budget ledger. Do not initialize, replace or reset that ledger.

Validated usage is settled before edit validation and before rechecking an
in-flight STOP, expiry or revocation. Invalid/incomplete visible output remains
billable. Unknown/invalid envelopes, transport uncertainty, interrupted execution
or unavailable usage retain the unresolved reservation. A settled request cannot
be replayed through the coding receiver. Recheck current pricing before operation;
changed rates/profile require code review and new authorization, not historical
record edits.

## First live operator procedure

Do not execute this procedure as part of development or CI.

1. Review/merge the implementation separately. Inspect the three disabled examples:
   `config/coding-task.example.json`, `coding-api.example.json` and
   `coding-broker.example.json`. Author protected installation files outside the
   application checkout. Use a fresh task identifier and fresh coding ledger;
   preserve every historical policy, task, approval, grant and ledger. Include
   both existing and new installation STOP files. Use the existing API budget
   path with its exact timezone/daily/lifetime policy. Do not run `init-budget`.
   Ensure the protected credential file and all stores are outside source/QA
   scratch. Verify pinned Node/source and an empty, reviewed scratch parent.
2. Independently review and enable the new task policy and coding broker config
   before first initialization. Record the chosen installation paths permanently.
   Configuration is ledger-bound: changing it after initialization blocks access;
   never create replacement ledgers to recover a consumed attempt. Run:

   ```sh
   python3 -m src.coding_canary readiness
   python3 -m src.coding_canary init-broker --broker /absolute/private/coding-broker.json
   python3 -m src.local_runner --policy /absolute/private/coding-task.json --state /absolute/new-task-state task-list
   python3 -m src.local_runner --policy /absolute/private/coding-task.json --state /absolute/new-task-state task-prepare sol-low-compile-comment
   ```

3. Inspect the entire prepared task and approve its exact binding on the controlling
   terminal with the existing runner `inspect RUN_ID` and `approve RUN_ID` commands.
   The task expressly authorizes up to 531 API cents. Check existing API budget
   status/audit and every other execution ledger for holds; do not evade a hold by
   selecting another installation. Confirm no existing worker or publication is
   active. Review the exact profile, current official prices and source pin.
4. Review, then separately authorize one request on the controlling terminal:

   ```sh
   python3 -m src.coding_canary review --broker /absolute/private/coding-broker.json --policy /absolute/private/coding-task.json --execution RUN_ID --task sol-low-compile-comment
   python3 -m src.coding_canary authorize --broker /absolute/private/coding-broker.json --policy /absolute/private/coding-task.json --execution RUN_ID --task sol-low-compile-comment
   ```

   Read the full displayed review and type its exact `AUTHORIZE ONE CODING REQUEST`
   challenge. There is no command-line response, `--yes`, environment override or
   automatic authorization. The current OS principal owns execution. The deadline
   is bounded by the task timeout, original approval expiry and 15 minutes.
5. Dispatch once, within that deadline:

   ```sh
   python3 -m src.coding_canary live --broker /absolute/private/coding-broker.json --execution RUN_ID
   ```

6. Inspect `coding_canary audit --broker ...` and existing API budget status/audit.
   Each completed QA check is persisted before subsequent checks, including
   failures and interrupted/STOP outcomes where storage remains available.
   Finite stage diagnostics and API validation/transport diagnostics contain no
   raw provider response, exception text or credentials. Accepted patches and
   trusted pinned-test stdout/stderr are retained as bounded QA evidence.
   A controller crash can leave only the consumed dispatch intent and budget
   hold; diagnose/reconcile manually, never retry. No output is a publication grant.
7. Stop after validated QA. Do not create a downstream PR, merge or deploy.
   Publication requires a separate reviewed authorization and receiver; this
   coding path deliberately has none.

## Sprint 6.14 focused verification

- Coding tests: 31 passed in normal Python (66.563s) and optimized Python (77.395s).
- Existing catalog tests: 12 passed; Responses validation: 43 passed; API controller:
  37 passed; live observation: 34 passed.
- `make lint` and staged `git diff --check` passed.
- The exact accepted candidate manifest is
  `f24e4325d47096b0387f1866d193f773d63010bb9380c3e26ff3b95a6a4aa560`.
- No real inference, production credential read, operational state modification,
  downstream application PR, merge, deployment, CI polling or workflow rerun.

The foundation PR #33 was still unmerged, so this integration updates that same
single draft. Its unchanged upstream controller/catalog/runner bases were compared
before publishing; no unrelated upstream changes are replaced.
