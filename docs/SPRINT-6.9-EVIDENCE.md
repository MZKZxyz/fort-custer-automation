# Sprint 6.9 evidence

Validation performed in Linux with Python 3.12.14 and Node v24.19.0, on
October 22, 2026 (Pacific time). Base main was independently checked through
GitHub: `1b4959ce7e84df9e76a82b5bbf54d947675e00ca`, merged Sprint 6.8 #17.
No operational state, real Codex worker, application publication, merge or
deployment was used. All created repositories, approvals, sockets and worker
bytes were isolated synthetic fixtures. The requested automation draft PR is
separate from application publication, which remains disabled.

## Commands and observed results

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests -q` | 463 tests in 147.266s, OK (skipped=1) |
| `python -m unittest discover -s tests -p test_grant_broker.py -v` | 28 tests, 8.970s, OK |
| `python -O -m unittest discover -s tests -p test_grant_broker.py -q` | 28 tests, 12.675s, OK |
| `PYTHONPATH=.:tests python tests/test_grant_broker.py --demo` | Validated synthetic candidate; authenticated local peer; zero real Codex workers/publication |
| `python3 src/infrastructure.py lint` | Pinned image inputs and live gate validated |
| `python3 -m compileall -q src infra tests` | Exit 0 |
| `git diff --check` | Exit 0 |

The existing encrypted restore test skips because `age` is not installed;
encrypted backup/restore is therefore NOT verified in this environment. The
new broker suite has no skipped tests. Full-suite optimization was also run:
462 tests in 150.432s, OK (skipped=1). The final advancing-clock fix was additionally verified
by the 28-test optimized broker run above.

The default execution sandbox rejected Unix socket bind with EPERM. Successful
socket runs used the approved execution tool's broader sandbox profile, with
only temporary local AF_UNIX endpoints and inert fixtures. No public network
listener, real worker account/VM or publisher credential was provisioned.
Initial shell `git fetch` failed because its proxy endpoint was unavailable;
the connected GitHub API independently verified main and supplies draft PR
submission. This is not evidence of worker egress confinement.

## Security evidence coverage

| Requirement | Observed evidence |
| --- | --- |
| Authoritative durable consumption | Four process claimants share the same ledger; exactly one wins; duplicate task/execution rejected |
| Existing independent approval only | Pending approval and proposal/promotion/orchestration inputs rejected |
| Historical compatibility | Controller policy, local SQLite and coordinator ledger remain byte-identical after broker claim; historical approval still historical |
| No atomicity claim across old ledgers | Legacy live gate unchanged; separate broker protocol/ledger, no live migration route |
| Crash before assignment | Restart retains occupied `claimed` identity; no second admission |
| Startup crash | Actual process exits with code 19 after durable startup intent; restart reports ambiguity and rejects startup replay |
| Lost response/disconnect | `starting` holds capacity; partial/late completion rejected; explicit hold/recovery required |
| Fencing and replay | Token, generation, request hash, artifact digest, extra QA fields and replayed completion rejected |
| Expiry and STOP | Broken STOP symlink; STOP at claim/start/capture/QA/final commit; expiry sweep never infers termination |
| QA crash/uncertainty | Failed validation persistence retains `checking`; replay rejected; failed approved check never validates |
| Recovery | Exact claim challenge, named operator and external termination-evidence digest required; identity remains permanently consumed |
| Peer authentication | Actual Linux SO_PEERCRED success; wrong-identity rejection before sending request; unsupported-platform rejection |
| Narrow bytes and descriptors | Bounded/truncated/oversized/trailing frames and SCM_RIGHTS rejection; absolute transfer deadline |
| Credentials and inheritance | Mock subprocess checks environment/FD allowlists; parent credential/agent sentinels and deliberately inheritable policy FD excluded |
| Untrusted source/output | Broken source manifest; missing/extra file, unsafe mode, executable-bit change and retained wire tampering rejected |
| Trusted checks only | Fresh pinned source reconstruction, controller-selected syntax/diff checks, candidate immutability, no worker QA acceptance |
| Always-blocked readiness | Read-only broker integrity/ambiguity observation; readiness exit 1; no policy/environment activation override |
| Advancing clock | Claim timestamp equals durable event timestamp even when successive wall-clock reads differ |

[`examples/sprint-6.9-synthetic.json`](../examples/sprint-6.9-synthetic.json)
is one captured successful demo, with a synthetic source SHA, candidate and QA
digest. Fixture Git commit timestamps and random tokens can change those values
between runs. The important recorded properties are:

```json
{
  "state": "validated",
  "subprocess_mock": true,
  "authenticated_kernel_peer": true,
  "independent_qa": true,
  "historical_ledger_unchanged": true,
  "inherited_environment_and_fds_checked": true,
  "external_isolation_proven": false,
  "live_dispatch": false,
  "real_codex_workers": 0,
  "publication_performed": false,
  "publication_review": "required-separate-human-action-no-legacy-import"
}
```

## Unsupported requirements and activation blockers

This is the requested fail-closed fallback, not a restored live execution system.
No distinct-principal worker boundary was demonstrated. The mock is a separate
process under the same UID; FD/environment minimization and kernel UID checking
do not prove filesystem, network or hostile-code confinement. `IsolatedEndpoint`
refuses same UID/root, but no actual cross-user endpoint is deployed/tested.

Linux results do not prove macOS getpeereid behavior or isolation. A macOS/Linux
CI matrix is supplied in `.github/workflows/grant-broker.yml`; no unobserved
remote/macOS CI result is claimed. A real Mac deployment must prove effective
ACL denial, egress/resource limits, credential separation, independent QA VM and
external termination/recovery before activation.

Missing production components: single service-owned live ledger deployment and
reviewed migration/fresh-approval protocol; authenticated model/VM relay and
receiver-side durable fencing; actual external worker/QA isolation; isolated
publisher intake and review adapter; watchdog and hard CPU/RAM/disk/egress
controls; tested backup/restore. No new live grant can be produced from historical
approvals, synthetic claims or promotion receipts. A second arbitrary broker file
is not global authority, and the unconditional live block prevents it from
becoming a bypass. Publication review is required but not performed by the demo.

See [design and state recovery](SPRINT-6.9.md),
[macOS provisioning](WORKER-ISOLATION.md) and
[canary prerequisites](LIVE-CANARY-RUNBOOK.md). Activation needs a separate review.
