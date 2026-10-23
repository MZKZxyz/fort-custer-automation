# Sprint 6.11 — authentication boundary blocker

This sprint chooses the objective's **documented technical-blocker outcome**.
The [architecture decision](CODEX-AUTHENTICATION-ARCHITECTURE.md) evaluates A,
rejects B's same-UID credential assumption and specifies C's simplest supported
alternative. No live adapter, grant migration, QA service or publisher intake is
claimed. Those acceptance items remain blocked, rather than passed by fixtures.

The concrete implementation is a bounded diagnostic adapter for official Codex
0.163.0 exec-server over stdio. It uses only fresh synthetic storage, an invalid
auth marker, fixed `/bin/cat`, filesystem reads/writes and one unknown RPC.
It validates both CLI and handshake versions, supplies no authentication,
closes inherited descriptors, bounds RPC waits/output and kills its own process
group on exit. It exposes no arbitrary command/config/auth CLI input.

The diagnostic proves same-UID credential readability and the danger of omitted
sandbox policies using the real transport. Platform sandbox denial probes use
positive read **and write** controls. Helper failure is reported unavailable;
it never counts as a denied-read success. This cloud's nested sandbox prevents
the positive control from starting; deployment OS isolation is unverified.
Hosted Linux also fails helper preparation of the exact-file writable profile,
including a `Not a directory` panic. CI tests the fail-closed diagnostic result;
the separate strict operator invocation still rejects unavailable enforcement.

`CodexWorker.run`, authoritative `Broker.dispatch_live`, coordinator and legacy
entrypoints continue to fail closed before execution. Readiness now includes
the explicit architecture result and missing requirements. Diagnostic output,
version validation, a passing test, or caller-supplied receipt cannot authorize
dispatch. Approved synthetic claims and their durable evidence remain entirely
separate from live authority. No second admission ledger or orchestration layer
was introduced.

Independent source/candidate reconstruction, approved QA commands, token and
generation binding, exhaustion/unknown holds, STOP, deadline checks, single-use
claims and one-slot fencing remain covered by the regression suite. Worker
claims cannot approve QA or publication. Live external QA and publisher intake
are still missing; the [Mac runbook](LIVE-CANARY-RUNBOOK.md) states the exact stop.

The low-risk maze direction-vector task remains proposed, unapproved and
unlaunched. Source was refreshed and the defect reproduced without changing
the source. See [exact observations and test results](SPRINT-6.11-EVIDENCE.md).

No API billing, login, credential copying, privileged provisioning, service
installation, firewall change, scheduling, automatic publication, merge or
deployment is performed. No hard dollar cap or complete hostile-process
termination guarantee is claimed.
