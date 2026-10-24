"""Operator-only one-request observation. No worker, coding or publication receiver."""
import argparse
from dataclasses import asdict, replace
from pathlib import Path
import os
import pwd
import time
import uuid

from src import orchestration_evidence as e
from src import api_controller as api
from src.grant_broker import Broker, PROTOCOL as SYNTHETIC
from src.concurrency_coordinator import authorization, stopped
from src.observation_planning import Planner, Decision, SCHEMA, observation_prompt, _legacy_observation_prompt
from src.local_runner import terminal_challenge
from src.observation_diagnostics import diagnostic, validate as validate_diagnostic

PROTOCOL = 'grant-broker-v2-live-observation'


class ObservationBroker(Broker):
    """Separate append-only protocol. No legacy grant import or execution method."""
    protocol = PROTOCOL

    def __init__(self, config, clock=time.time):
        c = e.decode(e.canonical(config))
        e.require(c.get('schema') == PROTOCOL and c.get('mode') == 'observation-only',
                  'Separate observation configuration required')
        c['schema'] = SYNTHETIC
        c['mode'] = 'synthetic-only'
        super().__init__(c, clock)
        self.config_digest = e.digest(config)

    def _rows(self, db):
        rows = {}
        e.require(db.execute('SELECT COUNT(*) FROM grants').fetchone()[0] <= self.c['max_tasks'],
                  'Observation ledger ceiling')
        for r in db.execute('SELECT * FROM grants'):
            a, c = e.decode(r['authorization']), e.decode(r['claim'])
            e.require(c == dict(protocol=PROTOCOL, execution=r['execution'], task=r['task'],
                      worker=a['principal'], token=c['token'], authorization=e.digest(a),
                      started=a['approved_at'], deadline=a['expires']) and e.sha(c['token'], 32) and
                      a['protocol'] == PROTOCOL and a['task'] == r['task'] and
                      a['execution'] == r['execution'] and
                      a['claim_identity'] == e.digest(c['token']) and
                      e.finite(a['approved_at']) and e.finite(a['expires']) and
                      a['approved_at'] < a['expires'] <= min(a['approved_at']+900, a['reviewed']['expires']) and
                      a['model'] == api.MODEL and a['pricing'] == api.DEFAULT_PRICING and
                      a['prompt_digest'] in {e.digest(observation_prompt(a['reviewed'])),
                                             e.digest(_legacy_observation_prompt(a['reviewed']))} and
                      a['source_manifest'] == a['reviewed']['source_manifest'] and
                      a['maximum_nano_usd'] == api.maximum_charge(a['pricing'], api.OBSERVATION_OUTPUT),
                      'Invalid observation authorization')
            rows[r['execution']] = dict(authorization=a, claim=c, state=None, events=[], terminal_failure=None)
        last = None
        for r in db.execute('SELECT * FROM events ORDER BY seq'):
            e.require(r['execution'] in rows and e.finite(r['at']) and
                      (last is None or last <= r['at']), 'Invalid observation chronology')
            last = r['at']; row = rows[r['execution']]; d = e.decode(r['document'])
            state = r['state']
            if state == 'diagnostic':
                e.require(row['state'] in {'dispatched', 'revoked'} and
                          any(event['state'] == 'dispatched' for event in row['events']) and
                          row['terminal_failure'] is None, 'Invalid observation diagnostic transition')
                row['terminal_failure'] = validate_diagnostic(d)
                row['events'].append(dict(at=r['at'], state=state, diagnostic=row['terminal_failure']))
                continue
            e.require((state == 'authorized' and row['state'] is None or
                       state == 'dispatched' and row['state'] == 'authorized' or
                       state == 'revoked' and row['state'] in {'authorized', 'dispatched'}) and
                      d == {'token':row['claim']['token']}, 'Invalid observation transition')
            row['state'] = state
            row['events'].append(dict(at=r['at'], state=state))
        e.require(all(r['state'] is not None for r in rows.values()), 'Missing authorization event')
        return rows

    def review(self, policy, execution, task, principal):
        e.require(isinstance(principal, str) and 0 < len(principal) <= 64, 'Principal required')
        a = authorization(policy, execution, task, self.clock(), self.c)
        prompt = observation_prompt(a)
        api.observation_payload(prompt)
        return dict(protocol=PROTOCOL, execution=execution, task=task, principal=principal,
            reviewed=a, source_manifest=a['source_manifest'], prompt_digest=e.digest(prompt),
            model=api.MODEL, pricing=api.DEFAULT_PRICING,
            maximum_nano_usd=api.maximum_charge(api.DEFAULT_PRICING, api.OBSERVATION_OUTPUT))

    def authorize(self, policy, execution, task, principal):
        e.require(self.c['enabled'] and not stopped(self.c), 'Observation disabled or STOP')
        token = uuid.uuid4().hex
        review = dict(self.review(policy, execution, task, principal), claim_identity=e.digest(token))
        # No response argument, pipe, environment flag or noninteractive bypass.
        print(e.canonical(dict(task=review['reviewed']['spec']['task'],
            execution=execution, principal=principal, source_manifest=review['source_manifest'],
            source=review['reviewed']['source'], prompt_digest=review['prompt_digest'],
            claim_identity=review['claim_identity'],
            model=review['model'], maximum_nano_usd=review['maximum_nano_usd'])))
        challenge = 'AUTHORIZE ONE OBSERVATION '+e.digest(review)
        e.require(terminal_challenge(challenge) == challenge, 'Interactive authorization required')
        with self.tx(True) as db:
            rows = self._rows(db)
            e.require(execution not in rows and len(rows) < self.c['max_tasks'], 'Observation already authorized')
            e.require(self.review(policy, execution, task, principal) ==
                      {k:v for k,v in review.items() if k != 'claim_identity'}, 'Review changed')
            now = self.clock()
            a = dict(review, approved_at=now, expires=min(now+900, review['reviewed']['expires']))
            e.require(now < a['expires'], 'Expired review')
            c = dict(protocol=PROTOCOL, execution=execution, task=task, worker=principal,
                     token=token, authorization=e.digest(a), started=now, deadline=a['expires'])
            db.execute('INSERT INTO grants VALUES (?,?,?,?)', (execution, task, e.canonical(a), e.canonical(c)))
            self._event(db, c, 'authorized', dict(token=c['token']))
            self._guard(c)
        return c

    def _fresh(self, a):
        r = a['reviewed']
        e.require(self.review(r['policy_path'], a['execution'], a['task'], a['principal']) ==
                  {k:v for k,v in a.items() if k not in {'approved_at','expires','claim_identity'}}, 'Observation binding changed')

    def guard(self, claim, principal, states):
        with self.tx() as db:
            row = self._owned(db, claim, states)
            self._guard(claim); self._fresh(row['authorization'])
            e.require(principal == claim['worker'] and self.c['enabled'], 'Observation principal/enable mismatch')
            return row['authorization']

    def admit(self, claim, principal):
        with self.tx(True) as db:
            row = self._owned(db, claim, {'authorized'})
            self._guard(claim); self._fresh(row['authorization'])
            e.require(principal == claim['worker'] and self.c['enabled'], 'Observation disabled/principal mismatch')
            self._event(db, claim, 'dispatched', dict(token=claim['token']))
            self._guard(claim)

    def revoke(self, claim):
        with self.tx(True) as db:
            self._owned(db, claim, {'authorized','dispatched'})
            self._event(db, claim, 'revoked', dict(token=claim['token']))

    def inspect(self):
        with self.tx() as db: rows = self._rows(db)
        return dict(schema=PROTOCOL, stop=stopped(self.c), enabled=self.c['enabled'],
                    tasks=rows, coding=False, publication=False)

    def record_failure(self, claim, phase):
        """One append-only diagnostic; never changes authority or accounting.

        Do not revalidate freshness here: STOP, expiry and source changes are
        precisely failures that must remain diagnosable after dispatch.
        """
        value = diagnostic(phase)
        with self.tx(True) as db:
            row = self._owned(db, claim, {'dispatched', 'revoked'})
            e.require(any(event['state'] == 'dispatched' for event in row['events']),
                      'Diagnostic requires consumed observation')
            if row['terminal_failure'] is None:
                self._event(db, claim, 'diagnostic', value)

    def claim_synthetic(self, *args, **kwargs):
        raise ValueError('Observation grants cannot authorize workers')

    start_synthetic = prepare_worker_synthetic = prepare_qa_synthetic = claim_synthetic
    capture_synthetic = validate_synthetic = dispatch_live = claim_synthetic
    hold = sweep = recover = capture_codex_synthetic = claim_synthetic


class LivePlanner(Planner):
    def _authority(self, broker, claim, principal):
        e.require(type(broker) is ObservationBroker and
                  type(self.controller.transport) is api.ResponsesTransport and
                  self.controller.prices == api.DEFAULT_PRICING, 'Trusted live observation controller required')
        def guard():
            return broker.guard(claim, principal, {'authorized','dispatched'})['reviewed']
        return guard(), guard

    def _bound(self, broker, claim, principal):
        provenance, binding, request, guard = super()._bound(broker, claim, principal)
        a = broker.guard(claim, principal, {'authorized','dispatched'})
        request = api.observation_payload(request['input'])
        provenance = replace(provenance, authorization=e.digest(a))
        binding.update(receiver='live-observation-only', authorization=e.digest(a))
        policy, _, _ = e.catalog(a['reviewed']['policy_path'])
        protected = [Path(r['source']).resolve() for r in policy['repositories'].values()]
        paths = [self.controller.budget.path.resolve(),
                 Path(self.controller.transport.credential_file).resolve()]
        e.require(all(not p.is_relative_to(root) for p in paths for root in protected),
                  'API stores must be outside application repositories')
        e.require(e.digest(request['input']) == a['prompt_digest'] and
                  api.maximum_charge(self.controller.prices, request['max_output_tokens']) == a['maximum_nano_usd'],
                  'Observation request changed')
        return provenance, binding, request, guard

    def observe(self, broker, claim, principal):
        claim = e.decode(e.canonical(claim))
        provenance, binding, request, guard = self._bound(broker, claim, principal)
        broker.admit(claim, principal)  # Durable single-use intent precedes budget/network.
        phase = 'internal'
        def progress(value):
            nonlocal phase
            phase = diagnostic(value)['phase']
        try:
            classification = self.controller._request(provenance.request_id, request, binding, guard,
                                                       _observation=True, _phase=progress)
            phase = 'final_verification'
            guard()
            decision = Decision(SCHEMA, provenance, classification)
            return self.verify(decision, broker, claim, principal)
        except Exception:
            self._failure(broker, claim, phase)
            raise

    @staticmethod
    def _failure(broker, claim, phase):
        try:
            broker.record_failure(claim, phase)
        except Exception:
            # Storage failure cannot authorize redispatch, undo settlement or
            # replace the safe CLI failure with sensitive exception output.
            pass

    def verify(self, decision, broker, claim, principal):
        try:
            return super().verify(decision, broker, claim, principal)
        except Exception:
            self._failure(broker, claim, 'final_verification')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['readiness','init-broker','review','authorize','run','revoke','audit','status'])
    parser.add_argument('--broker', type=Path)
    parser.add_argument('--api-config', type=Path)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--execution')
    parser.add_argument('--task')
    parser.add_argument('--principal')
    args = parser.parse_args()
    try:
        if args.command == 'readiness':
            result = dict(schema=PROTOCOL, enabled_by_default=False, interactive_authorization=True,
                          model=api.MODEL, maximum_nano_usd=api.maximum_charge(api.DEFAULT_PRICING, api.OBSERVATION_OUTPUT),
                          max_output_tokens=api.OBSERVATION_OUTPUT, tools=[], coding=False, publication=False)
        else:
            broker = ObservationBroker(e.decode(e.regular(args.broker).read_bytes()))
            if args.command == 'init-broker':
                broker.initialize(); result = dict(status='initialized', schema=PROTOCOL)
            elif args.command in {'review','authorize'}:
                e.require(args.principal == pwd.getpwuid(os.getuid()).pw_name,
                          'Current controller OS principal required')
                if args.command == 'review':
                    r = broker.review(args.policy, args.execution, args.task, args.principal)
                    result = dict(task=r['reviewed']['spec']['task'], source_manifest=r['source_manifest'],
                                  source=r['reviewed']['source'], prompt_digest=r['prompt_digest'],
                                  model=r['model'], maximum_nano_usd=r['maximum_nano_usd'],
                                  principal=r['principal'], execution=r['execution'])
                else:
                    claim = broker.authorize(args.policy, args.execution, args.task, args.principal)
                    result = dict(status='authorized', execution=claim['execution'], expires=claim['deadline'])
            elif args.command == 'audit':
                rows = broker.inspect()
                result = dict(schema=PROTOCOL, enabled=rows['enabled'], stop=rows['stop'], tasks=[
                    dict(execution=k, task=r['claim']['task'], state=r['state'], events=r['events'],
                         terminal_failure=r['terminal_failure'],
                         authorization=e.digest(r['authorization'])) for k,r in rows['tasks'].items()])
            elif args.command == 'revoke':
                rows = broker.inspect()['tasks']
                e.require(args.execution in rows, 'Unknown observation')
                broker.revoke(rows[args.execution]['claim']); result = dict(status='revoked')
            else:
                c, prices, budget = api.configuration(args.api_config)
                # Reuse the EXISTING controller budget; never initialize/reset it here.
                e.require(prices == api.DEFAULT_PRICING and broker.path != budget.path and
                          broker.path != Path(c['credential_file']).expanduser().absolute(), 'Distinct reviewed stores required')
                if args.command == 'status': result = budget.status()
                else:
                    rows = broker.inspect()['tasks']
                    e.require(args.execution in rows, 'Unknown observation')
                    claim = rows[args.execution]['claim']
                    e.require(args.principal == pwd.getpwuid(os.getuid()).pw_name,
                              'Current controller OS principal required')
                    planner = LivePlanner(api.Controller(budget, api.ResponsesTransport(c['credential_file']), prices))
                    decision = planner.observe(broker, claim, args.principal)
                    try:
                        with budget.tx() as db:
                            receipt = e.decode(db.execute('SELECT receipt FROM requests WHERE id=?',
                                              (decision.provenance.request_id,)).fetchone()[0])
                        planner.verify(decision, broker, claim, args.principal)
                        result = dict(decision=asdict(decision), receipt=receipt)
                    except Exception:
                        planner._failure(broker, claim, 'final_verification')
                        raise
        print(e.canonical(result)); return 0
    except Exception:
        print(e.canonical(dict(status='blocked-or-unknown', retry=False,
              instruction='inspect observation audit and existing budget status/audit; preserve holds; do not retry')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

