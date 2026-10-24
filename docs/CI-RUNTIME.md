# Sprint 6.16 CI coverage and runtime

The `offline-security` Ubuntu/macOS matrix owns PR-wide unittest coverage. Each
OS runs **one complete standard discovery** followed by the reviewed
`tests/ci_security.json` selection in a fresh **Python `-O`** process. The check
names remain unchanged. All existing checks, including this matrix, should remain
required during review; artifact jobs do not replace the matrix.

## Duplicate execution removed

Previously, each matrix job ran eight targeted standard modules, six targeted
optimized modules, a standalone broker demo, the complete standard suite via
`make lint test`, and the complete suite again under `-O`.

The eight standard modules were catalog activation, live observation,
observation planning, API controller, API response validation, grant broker,
activation readiness and executor boundary tests. Every case also occurred in
full standard discovery. The six optimized targets were the same list excluding
grant broker and executor boundary; every case also occurred in full optimized
discovery. The broker demo calls the same `demonstration()` exercised by
`SyntheticEndToEndTests.test_socket_claim_reconstruction_qa_and_separate_review`.
These repeated standard invocations and the standalone duplicate demo are removed.
The pinned executor is still installed and exported before full discovery, so
its actual offline probe remains exercised. The age prerequisites remain too.

Five other Linux PR workflows also repeated full standard discovery, and three
of those repeated full optimized discovery. PR-wide unit coverage is centralized
in the OS matrix. Those five jobs retain their independent checks:

| Workflow | Retained check |
| --- | --- |
| Activation contracts | Lint, activation rehearsal, default and mode-specific readiness failures, evidence artifacts |
| Infrastructure | Lint, checksum-pinned gVisor, image builds and real isolated offline container rehearsal |
| Trusted canary | Credential-free synthetic rehearsal and its report |
| Execution simulation | Synthetic execution report |
| Verify planner | Isolated sample-source planning and plan artifacts |

The operator-triggered `daily-planner.yml` still runs its own standard preflight.
It has no PR trigger and can write the planning state branch after explicit
operator invocation; retaining its self-contained preflight is intentional.
`make test` remains the ordinary local full-suite command.

## Optimized security coverage

Every standard test remains in full discovery. Full optimized discovery is
replaced by the explicit manifest, with a purpose for every selection group.
The runner rejects empty selections, missing names and duplicate test IDs.

* All six previously targeted optimized modules remain in full, preserving
  their authorization, schema validation, accounting, STOP, expiry, source
  binding, failure diagnostics and no-retry cases.
* Paid Sol profile/pricing, sanitized evidence, restricted edit grammars, legacy
  reservation protection, peer authentication and executor admission modules
  remain covered under `-O`.
* Legacy signed grants, budget ceilings, cancellation, independent QA,
  publication separation, subscription boundaries, catalog approvals and
  promotion/publication authorization modules receive optimized coverage.
* The manifest explicitly selects durable restart/duplicate-authority fences,
  STOP/source/policy rejection, shared historical holds, daily/lifetime limits,
  external reconciliation rejection, QA failure and termination proof, legacy
  grant preservation, and proven pre-dispatch recovery.
* Additional local-runner, coordinator, publication and VM identity/cleanup
  checks cover their separate security boundaries.

Cases outside the manifest run in standard mode. This removes repeated expensive
Sol success/replay permutations and ordinary planning/report cases under `-O`.
The full positive multi-job and real-source QA lifecycle still runs on **both**
OSes; optimized selections also retain real-source QA/failure and continuation.
The exact selectors are reviewable in the JSON manifest rather than inferred
from names or timing thresholds. No timing-based selection or new skip is used.

Current controller guards predominantly use explicit exceptions, not Python
assert statements. Optimized execution verifies that fail-closed behavior also
survives assertion removal and protects against future accidental conversion of
security checks into `assert`. Unittest's `assert*` methods continue checking
results under `-O`.

## Measured bottleneck and safe scope

A local Python 3.13.5/Linux cProfile run of
`DurableTests.test_two_distinct_successes_same_ledgers` took **44.000 seconds**.
It made **27,115 subprocess calls**. Fresh `source_observation.source_files`
verification ran **741 times**, accounting for **39.911 seconds**; Git process
calls accounted for about **40.396 seconds**. Trusted source fixture creation
itself took **0.0966 seconds** (less than 0.3% of that test).

Fresh source/policy/authorization checks are meaningful execution boundaries.
This change keeps them and the isolated fixtures intact, adds no authorization
cache, and changes no production execution code. Avoiding repeated integration
runs is the practical saving. Hosted macOS runtimes have not been measured
locally; local measurements must not be presented as hosted-runner results.

## Progress, deadlines and artifacts

`tests/ci_runner.py` starts a separate worker process for each group. It prints
`[RUN]` with the full test ID **before fixture setup**, followed by `[TIME]`
including setup, test, teardown and cleanup. It prints the ten slowest tests and
modules at completion and writes complete per-test timings. Test IDs are retained
before setup because some legacy fixtures use `self.id` for a request identifier.

| Boundary | Limit | Failure behavior |
| --- | --- | --- |
| Individual test including fixture setup | 180 seconds | Dump all thread stacks and exit nonzero, bypassing exception-catching test code |
| Full standard worker group | 1,200 seconds | Kill worker process group, return exit 124 |
| Optimized security worker group | 480 seconds | Kill worker process group, return exit 124 |
| GitHub full/security steps | 21 / 9 minutes | Outer fallback for a failed watchdog/launcher |
| Entire matrix job | 30 minutes | Existing final job bound |

A group timeout also bounds discovery/class-level setup outside an individual
test. The worker group is cleaned up on nonzero exit; existing candidate process
supervisors retain their independent termination guards. No test failure is
converted to success. The optimized step also runs after a standard failure to
collect its independent result, unless the job was cancelled. Artifact upload
runs on failure and does not change the test step's exit code.

Each OS uploads `offline-security-timings-<OS>` with:

* `<group>.jsonl`: flushed start/finish records; an unfinished start identifies
  interrupted fixture/test work even when the worker exits before its summary.
* `<group>.timings.json`: platform/Python/optimization mode, elapsed time,
  counts, slow tests and module totals on normal completion.
* `<group>.group.json`: parent elapsed time, exit code and group-timeout flag,
  including abnormal worker exits.

Superseded matrix runs on the same PR/ref are cancelled by workflow concurrency.

## Local commands

```sh
python3.13 -m unittest discover -s tests -p test_ci_runner.py -v
python3.13 tests/ci_runner.py full --output /tmp/fc616-ci-full
python3.13 tests/ci_runner.py optimized-security --output /tmp/fc616-ci-security
python3.13 tests/ci_runner.py full --names test_durable_coding.DurableTests.test_two_distinct_successes_same_ledgers --output /tmp/fc616-one-test
```

The explicit `--names` option is for local diagnosis. CI uses the complete
standard discovery and reviewed optimized manifest without overrides. Runner
regressions exercise normal/optimized mode, nonzero failure propagation, empty
selection rejection, fixture ID mutation, group termination, per-test stack
dumps, and security-selection validity.

## Verification for this update

Local host: Linux, Python 3.13.5. The two groups ran concurrently, so these are
observed group durations with CPU contention, not a sequential pipeline benchmark.

| Local check | Result | Measured worker runtime |
| --- | --- | --- |
| Complete standard suite | 712 tests; 0 failures/errors; 3 existing environment skips | 580.910 seconds |
| Reviewed optimized security selection (`optimize=1`) | 428 tests; 0 failures/errors; 2 existing environment skips | 274.741 seconds |
| CI runner regressions | 6 tests passed | 2.175 seconds |

The local skips reflect unavailable age, installed Codex probe and/or native
macOS support, as applicable to each selection. Their existing skip conditions
were not changed. CI still installs age and the pinned executor on each OS.
Native GitHub-hosted macOS performance remains unmeasured in this session.
GitHub Actions was not polled or awaited; the operator reviews those results.

The six runner regressions also passed with Python 3.12.14 (the CI minor version)
in **2.238 seconds**. All six PR workflow YAML files parsed successfully; local
validation confirmed exactly one standard and one focused optimized invocation
in the two-OS matrix. Lint and compilation passed. Production files are unchanged.
