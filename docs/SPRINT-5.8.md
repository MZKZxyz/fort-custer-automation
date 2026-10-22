# Sprint 5.8 — manual local Codex development

`local_codex_development` is an opt-in, POSIX-only operator tool. It is separate
from `chatgpt_subscription` and `api_billing`, their configuration, production
readiness, operational ledger and daily scheduler. The example is disabled.
Neither production profile is enabled or changed. There is no dispatch hook,
GitHub write client, push, PR publication, merge, deployment, purchase, refill,
provider retry or API fallback path in the local runner.

**Do not launch the first real controller-managed task in Sprint 5.8.** The
procedure below is for the later operator-approved experiment. Implementation
validation uses a generated fake executable, never a real authenticated CLI.

## Trust boundary and limits

Use only trusted, locally reviewed code and tasks on a development host with no
production access. The official CLI process uses the operator's existing ChatGPT
login. This tool never opens credential files, copies credentials, initiates login
or exports authentication state. Only official `login status` is invoked. Do not
use an operator home or host with production credentials/services accessible to
repository code. Review account subscription controls, disable paid refills and
paid credit consumption before proceeding; CLI flags do not establish account
billing settings. Usage telemetry is not a hard task-level financial cutoff.

The adapter builds an allowlisted environment without API keys, cloud identities,
GitHub tokens, arbitrary `CODEX_HOME`, Node options or inherited provider settings.
It preserves only proxy/CA settings needed by the official client. It pins the CLI
binary's SHA-256 and version `0.163.0`, checks supported flags, requires ChatGPT
login status, ignores user configuration and repository rules, forces the OpenAI
provider and ChatGPT login method, and sets workspace-write with approval `never`,
network access false and temporary-directory writes excluded. Unknown diagnostics,
protocol events, usage fields, quota or auth failures stop without retry/fallback.
A newer CLI requires a separately reviewed version/contract change.

**Codex CLI sandboxing does not make a host safe against arbitrary malicious
code.** Coding and QA run locally as the operator. Process separation is not VM
isolation, and QA executes candidate JavaScript. Process-group cancellation covers
ordinary descendants; a hostile process that escapes its session is outside this
local trust model. Use a reviewed, credential-free dedicated development host;
do not use this mode for untrusted tasks or as a production isolation substitute.
The watchdog uses a separate process and keepalive pipe to terminate the worker
group if the controller dies or the original deadline elapses. Killing the whole
host or guardian is outside this local mechanism's availability guarantees.

## Preparation (no inference)

1. Review `config/local-development.example.json`, then copy it to an
   operator-controlled path outside the disposable scratch directory. Keep it
   disabled during preparation. Fill **absolute** paths for an existing trusted
   local server source, the native official Codex binary (resolve symlinks first),
   the trusted Node binary, operator home, one persistent state directory, and an
   empty dedicated scratch parent. Record SHA-256 digests of the two binaries.
   No dependency installation runs during a task; analyzer tests use Node directly.
2. Review and set the exact 40-character server source SHA and branch label.
   The commit object is verified and every file is exported directly from Git
   blobs, without source hooks/configuration, remotes, shared Git objects or
   submodule processing. The branch is an informational source label; the exact
   SHA is authoritative. Source links, Git metadata/configuration, Git attributes,
   submodules, `.codex`, and likely environment-secret files fail closed.
3. Scratch must be outside the source repository, controller checkout and
   `~/fort-custer-canary`, and must contain no secrets. Mark
   `scratch_reviewed_no_secrets` true only after reviewing that parent and its
   host access. Policy and state must live outside scratch. Use one policy and
   its one persistent state directory; do not create competing policies/state
   stores to bypass the single-execution lock.
4. Read server issue #3 and save its current read-only GitHub JSON response to an
   operator-owned `issue-3.json`. Include `number`, `state`, `html_url`, title/body
   and any other relevant issue fields. The runner accepts only the exact server
   #3 URL, open issue identity, and fixed trusted maze-fix specification. Issue
   text is displayed and hashed as data, never substituted into the task prompt.
   Preparation is intentionally offline; the operator is responsible for checking
   that the saved issue is current. A policy or source change requires a new task.

Run from the automation checkout, replacing the example absolute paths:

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state prepare --issue 3 --repo fort-custer-server --issue-file /operator/issue-3.json
```

The returned JSON shows the repository, source branch/SHA, complete prompt, issue
snapshot, allowed files, controller QA commands, input content hash, policy hash,
authorization digest, task ID, history and ten-minute expiry. Only
`tools/maze-analyzer/solver.js` and `test/analyzer.test.js` may change; both must
change. No API/auth/MongoDB/deployment edits are permitted. The existing production
canary investigation scope remains separate and unchanged.

## Later first run (not authorized by this document)

After human review authorizes this separate local experiment, set only the local
policy's `enabled` field true **before preparing a new task**. This invalidates
all earlier prepared approvals. Leave all production configuration disabled.

Inspect the exact task, then approve it through a controlling terminal:

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state inspect TASK_ID
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state approve TASK_ID
```

The approval command prints the full specification and reads `/dev/tty`. Type
`APPROVE ` followed by the complete displayed 64-character binding. There is no
`--yes`, stdin approval or command-line token. Approval is single use, expires
with the pending task, and binds the complete prompt, issue snapshot, policy,
files, tests, repository and exact source SHA. Local state is trusted operator
state, not a cryptographically authenticated multiuser approval service.

Execute the approved task manually:

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state execute TASK_ID
```

A transaction consumes the approval and acquires the sole active claim before
any model process starts. Each task gets unique coding and QA directories under
the reviewed parent. Neither the ordinary source nor canary checkout is modified.
The original maximum 2400-second budget includes CLI checks, coding and QA; it
cannot be renewed by heartbeats or retries. Cancellation is checked while each
process runs; every process group is killed and the immediate child reaped,
including lingering children after parent exit.

The controller inventories all output files, modes and bytes, including hidden
and ignored files; links, hardlinks and extra/removed files fail. QA rematerializes
the exact candidate in a fresh directory, creates controller-owned input and
candidate revisions, and checks the candidate content hash. It runs Git diff
checks, both JS syntax checks, all analyzer tests, and a separate controller-owned
regression probe for invalid directions (including inherited object properties)
and a valid right move. It verifies that QA leaves the candidate unchanged.
No worker claims of successful testing are accepted as evidence.

The JSON report and SQLite record retain source SHA, input/candidate SHA-256
manifests, candidate Git revision/tree, complete binary patch, changed files,
QA commands/stdout/stderr/exit codes, sanitized token counts and approval history.
Candidate revisions are local QA identities, not commits in the source repository.
Disposable directories are removed on normal completion/failure; the patch in the
report preserves the result. A hard controller crash can leave scratch directories;
inspect and remove them only after independently verifying process termination.
Review and apply it manually in a later workflow. Nothing is pushed or published.
Raw model/auth output is never retained. QA output is retained in full within the
bounded output limit; only trusted tests without secrets belong in this mode.

## Emergency cancellation and restart

```sh
python3 -m src.local_runner --policy /operator/local-policy.json --state /operator/local-state cancel
```

This creates a persistent `STOP` file. It blocks approval/execution across restart
and requests cancellation of the active group. If policy parsing is broken, create
`STOP` directly in the known persistent state directory. A stopped or failed task
cannot reuse approval. After controller death, the guardian terminates the current
group and the durable `running` record retains an exclusive uncertain hold.
Inspect it after restart; do not delete/reset the ledger or automatically retry.
This sprint provides fail-closed restart inspection, not automatic reconciliation.
A trusted operator must independently reconcile host process absence and state
before any separately reviewed recovery. There is deliberately no force-unlock
or kill-switch-reset command. Never use a new state store to evade that hold.

## Offline validation

```sh
python3 -m unittest discover -s tests -v
```

`tests/test_local_runner.py` generates its own fake CLI and temporary Git source.
It covers execution/QA, binding/expiry, issue and commit changes, duplicate launch,
kill switch/restart fencing, process cancellation, ordinary child termination,
timeout, missing/unsupported CLI, key removal, auth/quota/protocol failures,
extra files/symlinks, failed QA, and absence of remote-write commands. Existing
production regression tests and readiness checks remain required and unchanged.
