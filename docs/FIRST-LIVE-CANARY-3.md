# Separate first-live-canary checklist — server issue #3

All boxes are initially unchecked. This checklist is not dispatch authorization.
Sprint 5.6 must not run a live model or create a client/server PR.

- [ ] Current official eligibility/registration and supported subscription runtime
      verified; explicit human consent recorded; correct account/scopes/expiry and
      rotation/revocation tested. No internal-only authentication workaround.
- [ ] Subscription-only controls independently verified: no API fallback, no
      credit purchase/reset-credit consumption or paid refill. No dollar ceiling
      inferred from subscription quotas. API profile remains separately disabled.
- [ ] Reviewed live broker and narrow VM tool transport operational; independent
      proof that coding/QA VMs, logs and artifacts contain no OAuth/API tokens.
- [ ] Worker VM provider, signed requests, no host mounts, deny-egress, cleanup,
      independent watchdog, controller/host failure fencing and persistent kill
      switch independently verified. One live agent, original 40-minute deadline.
- [ ] Authoritative ledger/legacy holds inventoried without reset; backup/restore
      and uncertain-turn restart fencing verified. Subscription usage audit ready.
- [ ] Complete independently verified offline server assets available; full unit,
      integration, analyzer, smoke, syntax and protected-file QA pass in a fresh
      isolated QA VM. Dependency-free subset is insufficient.
- [ ] Scoped GitHub Apps, branch protections and distinct authenticated dispatch,
      QA and draft-publication approvers deployed and tested.
- [ ] Exact source `c4f480abb309a7a4d141b20ab462552a868ef0e3` and tree
      `9015875cca2b85a845f7168ba237c5935e86445c` revalidated. If stale, stop for a
      separately reviewed source/scope grant; never silently substitute latest main.
- [ ] Issue [server #3](https://github.com/MZKZxyz/fort-custer-server/issues/3)
      rechecked. Scope remains investigation using existing analyzer/tests; edits
      limited to `docs/maze-generation-rejections.md` and
      `tools/maze-analyzer/README.md`. No generator/API/auth/database changes.
- [ ] All mandatory readiness receipts bind current software/policy/mode/task;
      independent security review and separately reviewed activation code release
      complete. Sprint 5.6's unconditional release block is still in place today.
- [ ] Operator issues a separate authenticated approval for this exact task/source.
      Labels and checklist completion do not authorize model usage.
- [ ] During the later authorized run: record bounded usage, stop on exhaustion or
      ambiguity, honor cancellation/deadline, retain uncertain holds. No automatic
      fallback, purchase, refill or retry after exhaustion.
- [ ] Independent QA authorizes the exact candidate SHA after fresh-VM full QA.
      Revalidate protected files and source/candidate before publication.
- [ ] Obtain a separate authenticated publication approval for that candidate.
      Publish a draft only; no auto-merge, production deploy or automatic promotion.
