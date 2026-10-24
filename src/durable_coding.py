"""Operator-driven persistent sequential coding queue, additive broker schema v4.

The v3 metadata/grants/events remain byte-for-byte historical evidence. Upgrade
adds separate tables; v3 grants are always verified with their original parser.
Nothing here initializes a replacement broker or budget ledger.
"""
import argparse
import contextlib
import os
from pathlib import Path
import pwd
import sqlite3
import uuid

from src import orchestration_evidence as e, api_controller as api, coding_api as profile
from src.coding_broker import CodingBroker, PROTOCOL as LEGACY
from src.concurrency_coordinator import stopped, authorization
from src.local_runner import Runner, terminal_challenge

SCHEMA = 'durable-coding-v4'
TABLES = {'metadata', 'grants', 'events', 'coding_upgrade', 'coding_jobs', 'coding_events', 'coding_legacy_closures'}
TERMINAL = {'validated', 'failed', 'cancelled'}
TRANSITIONS = {
    'prepared': {None}, 'approved': {'prepared'}, 'queued': {'approved'},
    'authorized': {'queued'}, 'dispatched': {'authorized'},
    'response_received': {'dispatched'}, 'accounting_settled': {'response_received'},
    'qa_running': {'accounting_settled'}, 'validated': {'qa_running'},
    'failed': {'dispatched', 'response_received', 'accounting_settled', 'qa_running'},
    'blocked': {'dispatched', 'response_received', 'accounting_settled', 'qa_running'},
    'adjudicated': {'blocked', 'dispatched', 'response_received', 'accounting_settled', 'qa_running'},
    'cancelled': {'prepared', 'approved', 'queued', 'authorized'},
    'claim': {'queued'}, 'qa_check': {'qa_running'},
}


class DurableBroker(CodingBroker):
    @property
    def authority(self):
        return e.digest(dict(ledger=str(self.path), config=self.config_digest, schema=SCHEMA))

    def initialize(self):
        raise ValueError('Upgrade the existing broker; never create a replacement')

    @contextlib.contextmanager
    def tx(self, write=False):
        e.regular(self.path)
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF'); db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            if not write: db.execute('PRAGMA query_only=ON')
            else: db.execute(f"PRAGMA max_page_count={self.c['max_storage_bytes']//db.execute('PRAGMA page_size').fetchone()[0]}")
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            e.require([tuple(r) for r in db.execute('SELECT * FROM metadata')] ==
                      [(LEGACY, self.config_digest)], 'Original broker binding changed')
            e.require({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == TABLES,
                      'Explicit reviewed v4 upgrade required')
            e.require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and
                      not db.execute('PRAGMA foreign_key_check').fetchall(), 'Broker integrity failure')
            upgrade = [e.decode(r[0]) for r in db.execute('SELECT document FROM coding_upgrade')]
            e.require(len(upgrade) == 1 and upgrade[0]['schema'] == SCHEMA and
                      upgrade[0]['config'] == self.config_digest and
                      upgrade[0]['api_config'] == e.digest(e.decode(e.regular(self.api_config).read_bytes())),
                      'Upgrade/API budget binding changed')
            self._budget().check_coding_authority(self.authority, required=True)
            self.maximum_jobs = upgrade[0]['maximum_jobs']
            e.require(type(self.maximum_jobs) is int and 1 <= self.maximum_jobs <= 10000,
                      'Invalid queue capacity')
            # Keep the original parser, including consumed grants and diagnostics.
            CodingBroker._rows(self, db)
            yield db
            if write: db.commit()
        finally: db.close()

    def upgrade(self, maximum_jobs=1000):
        old = CodingBroker.__new__(CodingBroker)
        old.__dict__.update(self.__dict__)
        config, prices, budget = api.configuration(self.api_config)
        budget.status()  # Existing shared store required; an unresolved hold is preserved.
        with old.tx() as db:
            legacy = CodingBroker._rows(old, db)
        e.require(type(maximum_jobs) is int and 1 <= maximum_jobs <= 10000, 'Invalid capacity')
        e.require(all(r['authorization']['api_config_digest'] == e.digest(config)
                      for r in legacy.values()), 'Legacy API budget binding changed')
        review = dict(schema=SCHEMA, config=self.config_digest, api_config=e.digest(config),
                      budget_extension='api-budget-v1-append-only-coding-binding',
                      budget_file=str(budget.path), maximum_jobs=maximum_jobs,
                      legacy_digest=e.digest(legacy), legacy_count=len(legacy),
                      operator=pwd.getpwuid(os.getuid()).pw_name, at=self.clock())
        print(e.canonical(review))
        challenge = 'UPGRADE EXISTING CODING LEDGER '+e.digest(review)
        e.require(terminal_challenge(challenge) == challenge, 'Terminal schema review required')
        budget.bind_coding_authority(self.authority)
        with old.tx(True) as db:
            e.require(e.digest(CodingBroker._rows(old, db)) == review['legacy_digest'], 'History changed')
            e.require(e.digest(e.decode(e.regular(self.api_config).read_bytes())) == review['api_config'],
                      'API configuration changed')
            for sql in [
                'CREATE TABLE coding_upgrade(document TEXT NOT NULL)',
                'CREATE TABLE coding_jobs(execution TEXT PRIMARY KEY, document TEXT NOT NULL)',
                'CREATE TABLE coding_legacy_closures(execution TEXT PRIMARY KEY REFERENCES grants(execution), document TEXT NOT NULL)',
                'CREATE TABLE coding_events(seq INTEGER PRIMARY KEY, execution TEXT NOT NULL REFERENCES coding_jobs(execution), at REAL NOT NULL, state TEXT NOT NULL, document TEXT NOT NULL)',
            ]: db.execute(sql)
            db.execute('INSERT INTO coding_upgrade VALUES (?)', (e.canonical(review),))
            for table in ('coding_upgrade', 'coding_jobs', 'coding_events', 'coding_legacy_closures'):
                for op in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable coding evidence'); END")
        return review

    def _append(self, db, execution, state, document=None):
        now = self.clock()
        last = db.execute('SELECT MAX(at) FROM coding_events').fetchone()[0]
        e.require(e.finite(now) and (last is None or now >= last), 'Queue clock regression')
        raw = e.canonical({} if document is None else document)
        e.require(len(raw.encode()) <= 4*1024*1024, 'Queue evidence ceiling')
        db.execute('INSERT INTO coding_events(execution,at,state,document) VALUES (?,?,?,?)',
                   (execution, now, state, raw))

    def _rows(self, db):
        rows = {}
        for r in db.execute('SELECT * FROM coding_jobs ORDER BY rowid'):
            job = e.decode(r['document'])
            e.require(job['execution'] == r['execution'] and e.sha(r['execution'], 32) and
                      e.sha(job['spec_digest']) and e.sha(job['policy_digest']), 'Invalid queued task')
            rows[r['execution']] = dict(job=job, state=None, events=[], claim=None, authorization=None,
                                        terminal_failure=None)
        e.require(len(rows) <= self.maximum_jobs, 'Queue capacity exceeded')
        last = None
        for event in db.execute('SELECT * FROM coding_events ORDER BY seq'):
            e.require(event['execution'] in rows and e.finite(event['at']) and
                      (last is None or last <= event['at']) and event['at'] <= self.clock(), 'Invalid queue chronology')
            last = event['at']; row = rows[event['execution']]
            state, d = event['state'], e.decode(event['document'])
            e.require(state in TRANSITIONS and row['state'] in TRANSITIONS[state], 'Invalid queue transition')
            if state == 'claim':
                e.require(row['claim'] is None and set(d) == {'claim','authorization'}, 'Duplicate claim')
                c, a = d['claim'], d['authorization']
                e.require(c['execution'] == row['job']['execution'] == a['execution'] and
                          c['task'] == row['job']['task'] == a['task'] and c['authorization'] == e.digest(a) and
                          e.sha(c['token'], 32) and c['worker'] == a['principal'] and
                          c['protocol'] == SCHEMA and a['model'] == profile.MODEL and a['pricing'] == profile.PRICING and
                          a['prompt_digest'] == e.digest(a['coding_prompt']) and
                          a['maximum_nano_usd'] == profile.MAXIMUM_CHARGE and
                          c['started'] == a['approved_at'] == event['at'] and
                          c['deadline'] == a['expires'] and c['started'] < c['deadline'] <=
                          min(a['approved_at']+900, a['reviewed']['expires'],
                              a['approved_at']+a['reviewed']['spec']['limits']['timeout_seconds']) and
                          a['reviewed']['policy_digest'] == row['job']['policy_digest'] and
                          a['reviewed']['spec'] and e.digest(a['reviewed']['spec']) == row['job']['spec_digest'],
                          'Invalid paid authorization')
                row['claim'], row['authorization'] = c, a
            elif state == 'approved':
                e.require(e.sha(d.get('task_authorization_digest')) and
                          d.get('policy_digest') == row['job']['policy_digest'] and
                          d.get('spec_digest') == row['job']['spec_digest'], 'Missing independent task approval')
            elif state == 'authorized':
                e.require(row['claim'] is not None, 'Missing paid authorization')
            elif state == 'adjudicated':
                e.require(e.sha(d.get('evidence')) and d.get('retry') is False, 'Missing external adjudication')
            elif state in {'failed','blocked'}:
                from src.coding_diagnostics import validate
                row['terminal_failure'] = validate(d['diagnostic'])
            elif state == 'qa_check':
                e.require(d['digest'] == e.digest(d['evidence']), 'QA check evidence changed')
            elif state == 'validated':
                a = row['authorization']
                result = d['evidence']; checks = result['checks']
                from src.coding_contract import USAGE_POLICY
                extras = ['compile-regression'] if a['reviewed']['spec']['limits']['usage_policy'] == USAGE_POLICY else []
                e.require([q['name'] for q in checks] ==
                          ['diff', *[q['name'] for q in a['reviewed']['spec']['checks']], *extras, 'candidate'] and
                          result['source_manifest'] == a['source_manifest'] == checks[-1]['input_hash'] and
                          result['candidate_manifest'] == checks[-1]['candidate_hash'] and
                          e.sha(result['candidate_manifest']) and
                          [q['command'][1:] for q in checks[1:1+len(a['reviewed']['spec']['checks'])]] ==
                          [q['argv'][1:] for q in a['reviewed']['spec']['checks']] and
                          result['publication'] == 'separate-authorization-required', 'Incomplete independent QA receipt')
                e.require(d['digest'] == e.digest(d['evidence']) and d['evidence']['checks'] and
                          all(q['code'] == 0 and q['reason'] is None for q in d['evidence']['checks']),
                          'Incomplete trusted QA')
            row['events'].append(dict(at=event['at'], state=state, document=d))
            if state not in {'claim', 'qa_check'}: row['state'] = 'failed' if state == 'adjudicated' else state
        e.require(all(r['state'] is not None for r in rows.values()), 'Missing prepared event')
        e.require(sum(r['state'] in {'authorized','dispatched','response_received','accounting_settled','qa_running','blocked'}
                      for r in rows.values()) <= 1, 'Sequential queue violated')
        tokens = [r['claim']['token'] for r in rows.values() if r['claim'] is not None]
        e.require(len(set(tokens)) == len(tokens), 'Duplicate immutable paid identity')
        return rows

    def _budget(self):
        return api.configuration(self.api_config)[2]

    def _clear(self, db):
        e.require(self.c['enabled'] and not stopped(self.c), 'Disabled or STOP active')
        status = self._budget().status()
        e.require(status['unresolved_requests'] == 0, 'Unresolved shared API billing hold')
        e.require(status['daily_encumbered_nano_usd']+profile.MAXIMUM_CHARGE <= status['daily_limit_nano_usd'] and
                  status['lifetime_encumbered_nano_usd']+profile.MAXIMUM_CHARGE <= status['lifetime_limit_nano_usd'],
                  'Insufficient shared budget for reviewed maximum')
        rows = self._rows(db)
        e.require(not any(r['state'] not in TERMINAL | {'prepared','approved','queued'} for r in rows.values()),
                  'Active or indeterminate execution; adjudicate explicitly')
        legacy = CodingBroker._rows(self, db)
        closed = self._closures(db, legacy)
        e.require(all(r['state'] == 'validated' or k in closed for k,r in legacy.items()),
                  'Legacy coding outcome requires explicit adjudication')
        return rows

    def _closures(self, db, legacy):
        closed = {}
        for r in db.execute('SELECT * FROM coding_legacy_closures'):
            d = e.decode(r['document'])
            e.require(r['execution'] in legacy and d['execution'] == r['execution'] and
                      e.sha(d['evidence']) and e.sha(d['manifest_sha256']) and d['retry'] is False,
                      'Invalid explicit legacy closure')
            closed[r['execution']] = d
        return closed

    def prepare(self, policy, task):
        # The controller preparation is separate from approval and paid authorization.
        with self.tx() as db:
            e.require(self.c['enabled'] and not stopped(self.c), 'Disabled or STOP')
            e.require(len(self._rows(db)) < self.maximum_jobs, 'Queue full')
        state = e.decode(e.regular(policy).read_bytes())['state']
        e.regular(Path(state)/'local.sqlite')
        runner = Runner(policy, state, self.clock)
        run = runner.task_prepare(task)
        return self.enqueue(policy, run['id'], task)

    def enqueue(self, policy, execution, task):
        policy = e.regular(policy)
        p, _, specs = e.catalog(policy)
        runs, _ = e.executions(Path(p['state'])/'local.sqlite')
        e.require(execution in runs and task in specs and runs[execution]['spec'] == specs[task], 'Unknown task preparation')
        r = runs[execution]
        status, _ = e.run_state(r, specs[task], p, self.clock())
        e.require(status in {'awaiting-coding-approval', 'approved-for-coding'}, 'Preparation expired/consumed')
        job = dict(execution=execution, task=task, policy=str(policy), policy_digest=e.digest(p),
                   spec_digest=e.digest(specs[task]), expires=r['expires'], source=specs[task]['source'],
                   source_manifest=specs[task]['input_hash'], maximum_nano_usd=profile.MAXIMUM_CHARGE)
        with self.tx(True) as db:
            rows = self._rows(db)
            e.require(self.c['enabled'] and not stopped(self.c) and len(rows) < self.maximum_jobs and
                      execution not in rows and execution not in CodingBroker._rows(self, db), 'Duplicate/disabled queue entry')
            db.execute('INSERT INTO coding_jobs VALUES (?,?)', (execution, e.canonical(job)))
            self._append(db, execution, 'prepared')
        if status == 'approved-for-coding': self.queue(execution)
        return job

    def approve(self, execution):
        with self.tx() as db: job = self._rows(db)[execution]['job']
        state = e.decode(e.regular(job['policy']).read_bytes())['state']
        e.regular(Path(state)/'local.sqlite')
        runner = Runner(job['policy'], state, self.clock)
        run = runner.inspect(execution)
        print(e.canonical(run))
        challenge = 'APPROVE '+run['binding']
        e.require(terminal_challenge(challenge) == challenge, 'Task terminal approval required')
        runner.approve(execution, challenge)
        return self.queue(execution)

    def queue(self, execution):
        with self.tx(True) as db:
            row = self._rows(db)[execution]; job = row['job']
            a = authorization(job['policy'], execution, job['task'], self.clock(), self.c)
            e.require(row['state'] == 'prepared' and e.digest(a['spec']) == job['spec_digest'] and
                      a['policy_digest'] == job['policy_digest'], 'Changed or already queued task')
            self._append(db, execution, 'approved', dict(task_authorization_digest=a['authorization_digest'],
                         policy_digest=a['policy_digest'], spec_digest=e.digest(a['spec'])))
            self._append(db, execution, 'queued')
        return dict(execution=execution, state='queued', authorized=False)

    def authorize(self, policy, execution, task, principal):
        token = uuid.uuid4().hex
        with self.tx() as db:
            rows = self._clear(db)
            e.require(execution in rows and rows[execution]['state'] == 'queued', 'Queue task first')
        review = dict(self.review(policy, execution, task, principal), claim_identity=e.digest(token))
        print(e.canonical(review))
        challenge = 'AUTHORIZE ONE CODING REQUEST '+e.digest(review)
        e.require(terminal_challenge(challenge) == challenge, 'Separate terminal paid authorization required')
        with self.tx(True) as db:
            rows = self._clear(db); row = rows[execution]; job = row['job']
            e.require(row['state'] == 'queued' and task == job['task'] and
                      str(e.regular(policy)) == job['policy'] and
                      review['reviewed']['policy_digest'] == job['policy_digest'] and
                      e.digest(review['reviewed']['spec']) == job['spec_digest'] and
                      self.review(policy, execution, task, principal) ==
                      {k:v for k,v in review.items() if k != 'claim_identity'}, 'Queue review changed')
            now = self.clock()
            a = dict(review, approved_at=now, expires=min(now+900,
                     now+review['reviewed']['spec']['limits']['timeout_seconds'], review['reviewed']['expires']))
            c = dict(protocol=SCHEMA, execution=execution, task=task, worker=principal, token=token,
                     authorization=e.digest(a), started=now, deadline=a['expires'])
            self._guard(c)
            self._append(db, execution, 'claim', dict(claim=c, authorization=a))
            self._append(db, execution, 'authorized')
        return c

    def admit(self, claim, principal):
        with self.tx(True) as db:
            row = self._owned(db, claim, {'authorized'})
            self._guard(claim); self._fresh(row['authorization'])
            e.require(self.c['enabled'] and principal == claim['worker'], 'Principal/enable mismatch')
            e.require(self._budget().status()['unresolved_requests'] == 0, 'Shared billing hold')
            self._append(db, claim['execution'], 'dispatched')

    def progress(self, claim, phase):
        states = {'response_validation': ('dispatched', 'response_received'),
                  'post_settlement_authorization': ('response_received', 'accounting_settled'),
                  'independent_qa': ('accounting_settled', 'qa_running')}
        if phase not in states: return
        before, after = states[phase]
        with self.tx(True) as db:
            row = self._owned(db, claim, {before,after})
            if row['state'] == before: self._append(db, claim['execution'], after)

    def guard(self, claim, principal, states):
        # The adapter sees 'dispatched' throughout downstream processing.
        if 'dispatched' in states: states = set(states) | {'response_received','accounting_settled','qa_running'}
        return super().guard(claim, principal, states)

    def evidence(self, claim, state, value):
        with self.tx(True) as db:
            row = self._owned(db, claim, {'qa_running'})
            self._guard(claim); self._fresh(row['authorization'])
            e.require(state in {'qa_check','validated'}, 'Invalid QA event')
            self._append(db, claim['execution'], state, dict(evidence=value, digest=e.digest(value)))

    def record_failure(self, claim, phase):
        from src.coding_diagnostics import diagnostic
        with self.tx(True) as db:
            row = self._owned(db, claim, {'dispatched','response_received','accounting_settled','qa_running','blocked','failed'})
            if row['state'] in {'blocked','failed'}: return
            billing = self.billing(claim)
            # Even a settled request interrupted before terminal QA needs explicit recovery.
            state = ('failed' if billing['state'] == 'settled' or
                     billing['state'] == 'not_reserved' and phase == 'internal' else 'blocked')
            self._append(db, claim['execution'], state, dict(diagnostic=diagnostic(phase)))

    def billing(self, claim):
        ident = e.digest(claim)[:32]
        budget = self._budget()
        with budget.tx() as db:
            r = db.execute('SELECT * FROM requests WHERE id=?', (ident,)).fetchone()
            evidence = [dict(v) for v in db.execute('SELECT * FROM events WHERE request=? ORDER BY seq', (ident,))]
        kinds = {v['kind'] for v in evidence}
        provider = ('response-received' if 'response_observed_untrusted' in kinds else
                    'dispatch-intent' if 'dispatch_intent' in kinds else 'not-dispatched')
        for event in evidence:
            if event['kind'] == 'request_failed_hold_retained':
                d = e.decode(event['evidence'])
                if d.get('http_status') is not None and d['http_status'] >= 400: provider = 'known-provider-rejection'
                elif d.get('dispatch') == 'not_attempted': provider = 'failed-before-dispatch'
                elif provider != 'response-received': provider = 'uncertain-provider-outcome'
        return dict(request_id=ident, provider_state=provider, state='not_reserved' if r is None else
                    'unresolved' if r['actual'] is None else 'settled',
                    reservation=None if r is None else dict(r), audit=evidence)

    def cancel(self, execution):
        with self.tx(True) as db:
            row = self._rows(db)[execution]
            e.require(row['state'] in TRANSITIONS['cancelled'], 'Cannot cancel dispatched work')
            self._append(db, execution, 'cancelled')
        return dict(execution=execution, state='cancelled', retry=False)

    def adjudicate(self, execution, evidence_file, artifact_file, qa_termination_file=None):
        """Human reviews retained external billing AND provider completion evidence."""
        raw = e.regular(evidence_file).read_bytes()
        e.require(0 < len(raw) <= 8192, 'Bounded external evidence manifest required')
        evidence = e.decode(raw)
        from src.billing_reconciliation import FIELDS, validate_amount
        from src.api_evidence import identifier
        from urllib.parse import urlparse
        e.require(isinstance(evidence, dict) and set(evidence) == FIELDS and
                  evidence['schema'] == 'provider-billing-evidence-v1' and
                  evidence['execution'] == execution and evidence['final'] is True and
                  evidence['provider_terminal'] is True and
                  evidence['source'] in {'provider-request-export','provider-support-confirmation'} and
                  isinstance(evidence['account_project'], str) and bool(evidence['account_project']) and
                  (identifier(evidence['provider_request_id'], 'req_') is not None or
                   identifier(evidence['provider_response_id'], 'resp_') is not None),
                  'Linked final provider outcome evidence required')
        validate_amount(evidence)
        link = urlparse(evidence['reference'])
        e.require(link.scheme == 'https' and link.hostname in
                  {'platform.openai.com','help.openai.com','support.openai.com'} and
                  not link.username and not link.password and not link.query and not link.fragment,
                  'Provider-verifiable reference required')
        artifact = e.regular(artifact_file)
        e.require(0 < artifact.stat().st_size <= 8*1024*1024, 'Bounded external artifact required')
        import hashlib
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        e.require(digest == evidence['artifact_sha256'], 'External artifact digest mismatch')
        with self.tx() as db:
            rows = self._rows(db); legacy = CodingBroker._rows(self, db)
            e.require(execution in rows or execution in legacy, 'Unknown execution')
            row = rows.get(execution, legacy.get(execution))
            e.require(row['state'] in {'blocked','dispatched','response_received','accounting_settled','qa_running','revoked','authorized'},
                      'No indeterminate operation to adjudicate')
            claim = row['claim']
            reviewed_row_digest = e.digest(row)
            qa_uncertain = (row['state'] == 'qa_running' or execution in legacy and
                            row['state'] == 'dispatched' and row['terminal_failure'] is None)
        qa_digest = None
        if qa_uncertain:
            termination = e.regular(qa_termination_file)
            e.require(0 < termination.stat().st_size <= 1024*1024, 'Retained local QA termination evidence required')
            qa_digest = hashlib.sha256(termination.read_bytes()).hexdigest()
        billing = self.billing(claim)
        e.require(evidence['request_id'] == billing['request_id'], 'Request linkage mismatch')
        for item in billing['audit']:
            if item['kind'] == 'response_observed_untrusted':
                observed = e.decode(item['evidence'])
                for key in ('provider_request_id','provider_response_id'):
                    if observed.get(key) is not None:
                        e.require(evidence[key] == observed[key], 'Provider identifier conflict')
        e.require(billing['state'] == 'settled' and evidence['actual_nano_usd'] == billing['reservation']['actual'] or
                  billing['state'] == 'not_reserved' and evidence['actual_nano_usd'] == 0 and
                  evidence['outcome'] == 'confirmed-no-charge', 'Billing outcome conflicts with closure evidence')
        e.require(billing['state'] == 'settled' or billing['state'] == 'not_reserved',
                  'Reconcile shared billing reservation first')
        review = dict(execution=execution, evidence=digest, manifest_sha256=hashlib.sha256(raw).hexdigest(),
                      billing=billing['state'], qa_termination_sha256=qa_digest, retry=False,
                      operator=pwd.getpwuid(os.getuid()).pw_name)
        print(e.canonical(review))
        challenge = 'CONFIRM PROVIDER TERMINAL AND ALL QA STOPPED NO REPLAY '+e.digest(review)
        e.require(terminal_challenge(challenge) == challenge, 'External outcome review required')
        e.require(e.regular(evidence_file).read_bytes() == raw and
                  hashlib.sha256(e.regular(artifact_file).read_bytes()).hexdigest() == digest,
                  'Evidence changed during terminal review')
        if qa_digest is not None:
            e.require(hashlib.sha256(e.regular(qa_termination_file).read_bytes()).hexdigest() == qa_digest,
                      'QA termination evidence changed during review')
        with self.tx(True) as db:
            rows = self._rows(db)
            if execution not in rows:
                legacy_now = CodingBroker._rows(self, db)
                e.require(execution in legacy_now and e.digest(legacy_now[execution]) == reviewed_row_digest,
                          'Legacy outcome changed during review')
                db.execute('INSERT INTO coding_legacy_closures VALUES (?,?)', (execution, e.canonical(review)))
            else:
                e.require(rows[execution]['state'] in TRANSITIONS['adjudicated'] and
                          e.digest(rows[execution]) == reviewed_row_digest, 'Outcome changed during review')
                self._append(db, execution, 'adjudicated', review)
        return review

    def inspect(self):
        with self.tx() as db:
            rows = self._rows(db); legacy = CodingBroker._rows(self, db)
            closures = self._closures(db, legacy)
        for row in rows.values():
            if row['claim'] is not None: row['billing'] = self.billing(row['claim'])
        summary = [dict(execution=k, task=r['job']['task'], state=r['state'],
                        billing=r.get('billing',{}).get('state','not_reserved'),
                        request=r.get('billing',{}).get('provider_state','not-dispatched'),
                        expired=self.clock() >= (r['claim']['deadline'] if r['claim'] else r['job']['expires']))
                   for k,r in rows.items()]
        return dict(schema=SCHEMA, tasks=rows, summary=summary, legacy=legacy, legacy_closures=closures, stop=stopped(self.c),
                    budget=self._budget().status(), publication=False, automatic_retry=False)

    def revoke(self, claim):
        return self.cancel(claim['execution'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['upgrade','prepare','approve','queue','authorize','dispatch','list','inspect','enqueue','cancel','adjudicate'])
    parser.add_argument('--broker', required=True)
    parser.add_argument('--policy'); parser.add_argument('--task'); parser.add_argument('--execution')
    parser.add_argument('--qa-termination'); parser.add_argument('--artifact'); parser.add_argument('--evidence'); parser.add_argument('--maximum-jobs', type=int, default=1000)
    args = parser.parse_args()
    try:
        broker = DurableBroker(e.decode(e.regular(args.broker).read_bytes()))
        principal = pwd.getpwuid(os.getuid()).pw_name
        if args.command == 'upgrade': result = broker.upgrade(args.maximum_jobs)
        elif args.command == 'prepare': result = broker.prepare(args.policy, args.task)
        elif args.command == 'enqueue': result = broker.enqueue(args.policy, args.execution, args.task)
        elif args.command == 'approve': result = broker.approve(args.execution)
        elif args.command == 'queue': result = broker.queue(args.execution)
        elif args.command == 'authorize':
            with broker.tx() as db: job = broker._rows(db)[args.execution]['job']
            result = broker.authorize(job['policy'], args.execution, job['task'], principal)
        elif args.command in {'list','inspect'}:
            result = broker.inspect()
            if args.execution: result['tasks'] = {args.execution:result['tasks'][args.execution]}
            if args.command == 'list': result = {k:result[k] for k in ('schema','summary','stop','budget')}
        elif args.command == 'cancel': result = broker.cancel(args.execution)
        elif args.command == 'adjudicate': result = broker.adjudicate(args.execution, args.evidence, args.artifact, args.qa_termination)
        else:
            from src.coding_canary import run
            with broker.tx() as db: claim = broker._rows(db)[args.execution]['claim']
            config, prices, budget = api.configuration(broker.api_config)
            result = run(broker, claim, principal, api.Controller(budget, api.ResponsesTransport(config['credential_file']), prices))
        print(e.canonical(result)); return 0
    except BaseException:
        print(e.canonical(dict(status='blocked-or-indeterminate', retry=False,
                              instruction='inspect queue and shared billing audit; preserve all evidence')))
        return 1


if __name__ == '__main__': raise SystemExit(main())
