"""Separate append-only coding authority; no observation grant import or publisher."""
from pathlib import Path
import time
import uuid
from src import orchestration_evidence as e, coding_api as profile
from src.grant_broker import Broker, PROTOCOL as SYNTHETIC
from src.concurrency_coordinator import authorization, stopped
from src.local_runner import terminal_challenge
from src.coding_diagnostics import diagnostic, validate as validate_diagnostic
from src.coding_contract import prompt
from src.source_observation import source_files
from src import api_controller as api

PROTOCOL = 'grant-broker-v3-live-coding'


def coding_prompt(a):
    from src.coding_canary import reviewed
    reviewed(a)
    policy, _, _ = e.catalog(a['policy_path'])
    files = source_files(policy['repositories'][a['spec']['repo']]['source'], a['source'], a['allowed'])
    return prompt(a['spec'], files)


class CodingBroker(Broker):
    """Separate append-only protocol. No legacy grant import or execution method."""
    protocol = PROTOCOL

    def __init__(self, config, clock=time.time):
        c = e.decode(e.canonical(config))
        self.api_config = e.regular(c.pop('api_config'))
        e.require(c.get('schema') == PROTOCOL and c.get('mode') == 'coding-only',
                  'Separate coding configuration required')
        c['schema'] = SYNTHETIC
        c['mode'] = 'synthetic-only'
        super().__init__(c, clock)
        self.config_digest = e.digest(config)

    def _rows(self, db):
        rows = {}
        e.require(db.execute('SELECT COUNT(*) FROM grants').fetchone()[0] <= self.c['max_tasks'],
                  'Coding ledger ceiling')
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
                      a['model'] == profile.MODEL and a['pricing'] == profile.PRICING and
                      a['prompt_digest'] == e.digest(a['coding_prompt']) and
                      a['source_manifest'] == a['reviewed']['source_manifest'] and
                      a['maximum_nano_usd'] == profile.MAXIMUM_CHARGE,
                      'Invalid coding authorization')
            rows[r['execution']] = dict(authorization=a, claim=c, state=None, events=[], terminal_failure=None)
        last = None
        for r in db.execute('SELECT * FROM events ORDER BY seq'):
            e.require(r['execution'] in rows and e.finite(r['at']) and
                      (last is None or last <= r['at']), 'Invalid coding chronology')
            last = r['at']; row = rows[r['execution']]; d = e.decode(r['document'])
            state = r['state']
            if state in {'qa_check', 'validated'}:
                e.require((row['state'] == 'dispatched' or state == 'qa_check' and
                           row['state'] == 'revoked') and row['terminal_failure'] is None,
                          'Invalid coding evidence transition')
                e.require(isinstance(d, dict) and set(d) == {'digest', 'evidence'} and
                          d['digest'] == e.digest(d['evidence']), 'Coding evidence integrity')
                row['events'].append(dict(at=r['at'], state=state, **d))
                if state == 'validated': row['state'] = state
                continue
            if state == 'diagnostic':
                e.require(row['state'] in {'dispatched', 'revoked', 'validated'} and
                          any(event['state'] == 'dispatched' for event in row['events']) and
                          row['terminal_failure'] is None, 'Invalid coding diagnostic transition')
                row['terminal_failure'] = validate_diagnostic(d)
                row['events'].append(dict(at=r['at'], state=state, diagnostic=row['terminal_failure']))
                continue
            e.require((state == 'authorized' and row['state'] is None or
                       state == 'dispatched' and row['state'] == 'authorized' or
                       state == 'revoked' and row['state'] in {'authorized', 'dispatched'}) and
                      d == {'token':row['claim']['token']}, 'Invalid coding transition')
            row['state'] = state
            row['events'].append(dict(at=r['at'], state=state))
        e.require(all(r['state'] is not None for r in rows.values()), 'Missing authorization event')
        return rows

    def review(self, policy, execution, task, principal):
        e.require(isinstance(principal, str) and 0 < len(principal) <= 64, 'Principal required')
        a = authorization(policy, execution, task, self.clock(), self.c)
        prompt = coding_prompt(a)
        profile.payload(prompt)
        config, prices, budget = api.configuration(self.api_config)
        e.require(prices == profile.PRICING and config['connectivity_enabled'] is False,
                  'Reviewed dedicated coding API configuration required')
        policy_value, _, _ = e.catalog(policy)
        protected = [Path(self.c['scratch']).resolve(),
                     *[Path(r['source']).resolve() for r in policy_value['repositories'].values()]]
        stores = [self.path.resolve(), budget.path.resolve(), Path(config['credential_file']).resolve()]
        e.require(len(set(stores)) == 3 and all(not p.is_relative_to(root)
                  for p in stores for root in protected), 'Protected coding API stores overlap')
        return dict(protocol=PROTOCOL, execution=execution, task=task, principal=principal,
            reviewed=a, coding_prompt=prompt, source_manifest=a['source_manifest'], prompt_digest=e.digest(prompt),
            api_config_digest=e.digest(config),
            model_config={k:v for k,v in profile.payload(prompt).items() if k != 'input'},
            model=profile.MODEL, pricing=profile.PRICING,
            maximum_nano_usd=profile.MAXIMUM_CHARGE)

    def authorize(self, policy, execution, task, principal):
        e.require(self.c['enabled'] and not stopped(self.c), 'Coding disabled or STOP')
        token = uuid.uuid4().hex
        review = dict(self.review(policy, execution, task, principal), claim_identity=e.digest(token))
        # No response argument, pipe, environment flag or noninteractive bypass.
        print(e.canonical(review))
        challenge = 'AUTHORIZE ONE CODING REQUEST '+e.digest(review)
        e.require(terminal_challenge(challenge) == challenge, 'Interactive authorization required')
        with self.tx(True) as db:
            rows = self._rows(db)
            e.require(not rows, 'First coding canary already authorized; no replacement grant')
            e.require(self.review(policy, execution, task, principal) ==
                      {k:v for k,v in review.items() if k != 'claim_identity'}, 'Review changed')
            now = self.clock()
            a = dict(review, approved_at=now, expires=min(
                now+900, now+review['reviewed']['spec']['limits']['timeout_seconds'], review['reviewed']['expires']))
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
                  {k:v for k,v in a.items() if k not in {'approved_at','expires','claim_identity'}}, 'Coding binding changed')

    def guard(self, claim, principal, states):
        with self.tx() as db:
            row = self._owned(db, claim, states)
            self._guard(claim); self._fresh(row['authorization'])
            e.require(principal == claim['worker'] and self.c['enabled'], 'Coding principal/enable mismatch')
            return row['authorization']

    def admit(self, claim, principal):
        with self.tx(True) as db:
            row = self._owned(db, claim, {'authorized'})
            self._guard(claim); self._fresh(row['authorization'])
            e.require(principal == claim['worker'] and self.c['enabled'], 'Coding disabled/principal mismatch')
            self._event(db, claim, 'dispatched', dict(token=claim['token']))
            self._guard(claim)

    def revoke(self, claim):
        with self.tx(True) as db:
            self._owned(db, claim, {'authorized','dispatched'})
            self._event(db, claim, 'revoked', dict(token=claim['token']))

    def inspect(self):
        with self.tx() as db: rows = self._rows(db)
        return dict(schema=PROTOCOL, stop=stopped(self.c), enabled=self.c['enabled'],
                    tasks=rows, coding=True, publication=False)

    def evidence(self, claim, state, value):
        e.require(state in {'qa_check', 'validated'}, 'Unsupported coding evidence')
        with self.tx(True) as db:
            self._owned(db, claim, {'dispatched', 'revoked'} if state == 'qa_check' else {'dispatched'})
            if state == 'validated': self._guard(claim)
            self._event(db, claim, state, dict(evidence=value, digest=e.digest(value)))

    def record_failure(self, claim, phase):
        """One append-only diagnostic; never changes authority or accounting.

        Do not revalidate freshness here: STOP, expiry and source changes are
        precisely failures that must remain diagnosable after dispatch.
        """
        value = diagnostic(phase)
        with self.tx(True) as db:
            row = self._owned(db, claim, {'dispatched', 'revoked', 'validated'})
            e.require(any(event['state'] == 'dispatched' for event in row['events']),
                      'Diagnostic requires consumed coding')
            if row['terminal_failure'] is None:
                self._event(db, claim, 'diagnostic', value)

    def claim_synthetic(self, *args, **kwargs):
        raise ValueError('Coding grants cannot authorize workers')

    start_synthetic = prepare_worker_synthetic = prepare_qa_synthetic = claim_synthetic
    capture_synthetic = validate_synthetic = dispatch_live = claim_synthetic
    hold = sweep = recover = capture_codex_synthetic = claim_synthetic
