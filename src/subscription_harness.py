"""Offline-only subscription boundary experiment, never a live transport.

No socket, subprocess, URL, token parser or real OAuth endpoint is implemented.
The fake provider models consent lifecycle, NOT a claimed supported OAuth grant.
Only public sentinel credentials are accepted. Durable ambiguous admissions remain
held after controller/broker restart. The operational planning ledger is unused.
"""
import json
from pathlib import Path
import re
import sqlite3
from contextlib import contextmanager
from execution_modes import SubscriptionUsageMonitor
from trust import canonical, require_live


class FakeOAuth:
    """Public fixture state; fields/scopes are simulator policy, not OAuth spec."""
    def __init__(self):
        self.eligible = True
        self.consent = True
        self.state = 'fixture-state'
        self.account = 'fixture-account'
        self.scopes = {'fixture:codex'}
        self.expires = 3400
        self.revoked = False
        self.generation = 1
        self.credential = 'PUBLIC-FAKE-OAUTH-SENTINEL'

    def verify(self, now):
        if (self.eligible is not True or self.consent is not True or self.revoked is not False
                or self.state != 'fixture-state' or self.account != 'fixture-account'
                or self.scopes != {'fixture:codex'} or type(self.expires) is not int
                or now >= self.expires or self.credential != 'PUBLIC-FAKE-OAUTH-SENTINEL'):
            raise ValueError('Fixture authorization rejected')
        return self.generation

    def rotate(self, now, *, account='fixture-account'):
        self.verify(now)
        if account != self.account:
            raise ValueError('Fixture refresh account mismatch')
        self.generation += 1
        self.expires = now + 2400


class FakeAppServer:
    """Deterministic public protocol notifications; no real executable starts."""
    def __init__(self, outcome='complete'):
        self.outcome = outcome
        self.calls = 0

    def turn(self):
        self.calls += 1
        if self.outcome == 'crash':
            raise RuntimeError('Synthetic process loss')
        if self.outcome == 'tool':
            # Even approval-style requests cannot authorize local tool execution.
            return {'id': 7, 'method': 'item/commandExecution/requestApproval', 'params': {}}
        if self.outcome == 'exposure':
            return {'method': 'item/agentMessage/delta', 'params': {'delta': 'PUBLIC-FAKE-OAUTH-SENTINEL'}}
        error = None
        if self.outcome != 'complete':
            error = dict(message='Synthetic failure', codexErrorInfo=(
                'usageLimitExceeded' if self.outcome == 'quota' else 'other'), additionalDetails=None)
        return dict(method='turn/completed', params=dict(threadId='fixture-thread', turn=dict(
            id='fixture-turn', items=[], status='completed' if error is None else 'failed', error=error)))


class SubscriptionHarness:
    """Bounded single-turn simulation, with durable one-agent admission.

    principal is supplied by the test transport, never parsed from worker JSON.
    A real transport would need independently authenticated vsock/mTLS identity.
    It is deliberately impossible to select a live transport in this class.
    """
    def __init__(self, path, oauth, server, clock, *, initialize=False):
        if type(oauth) is not FakeOAuth or type(server) is not FakeAppServer:
            raise ValueError('Only exact offline fakes allowed')
        self.path, self.oauth, self.server, self.clock = Path(path), oauth, server, clock
        if initialize:
            import os
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with self.tx() as db:
                db.executescript('''CREATE TABLE execution (
                    id TEXT PRIMARY KEY, principal TEXT NOT NULL, task TEXT NOT NULL,
                    repository TEXT NOT NULL, source TEXT NOT NULL, deadline INTEGER NOT NULL,
                    state TEXT NOT NULL, generation INTEGER NOT NULL);
                    CREATE TABLE audit (id INTEGER PRIMARY KEY, at INTEGER NOT NULL,
                    event TEXT NOT NULL, payload TEXT NOT NULL);''')
        with self.tx() as db:
            db.execute('SELECT * FROM execution LIMIT 0')

    @contextmanager
    def tx(self):
        with sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            yield db

    def record(self, db, event, payload):
        # Only fixed metadata is passed; raw requests/responses are never logged.
        db.execute('INSERT INTO audit(at,event,payload) VALUES (?,?,?)',
                   (int(self.clock()), event, canonical(payload)))

    def approve(self, execution, principal, task, repository, source, deadline):
        generation = self.oauth.verify(self.clock())
        if (not re.fullmatch('[a-f0-9]{32}', execution) or principal != 'fixture-vsock:1'
                or repository != 'fixture/server' or task != 'fixture/server#3'
                or not re.fullmatch('[a-f0-9]{40}', source) or type(deadline) is not int
                or not self.clock() < deadline <= self.clock()+2400):
            raise ValueError('Fixture approval binding rejected')
        with self.tx() as db:
            # Pending/uncertain holds NEVER expire into another admission.
            if db.execute("SELECT 1 FROM execution WHERE state IN ('approved','pending','uncertain')").fetchone():
                raise ValueError('One agent; unresolved hold requires independent reconciliation')
            db.execute('INSERT INTO execution VALUES (?,?,?,?,?,?,?,?)',
                       (execution, principal, task, repository, source, deadline, 'approved', generation))
            self.record(db, 'approved', dict(execution=execution, synthetic=True))

    def stop(self, execution, reason='cancelled'):
        if reason not in ('cancelled', 'revoked', 'kill_switch'):
            raise ValueError('Unknown stop reason')
        with self.tx() as db:
            # A pending call has an uncertain outcome; keep its exclusive hold.
            db.execute("UPDATE execution SET state=CASE WHEN state IN ('pending','uncertain') THEN 'uncertain' ELSE ? END WHERE id=?",
                       (reason, execution))
            self.record(db, reason, dict(execution=execution))

    def request(self, principal, request):
        expected = {'execution', 'task', 'repository', 'source', 'model', 'operation'}
        if (not isinstance(request, dict) or set(request) != expected
                or any(not isinstance(v, str) for v in request.values())
                or len(canonical(request)) > 2048 or request['model'] != 'fixture-codex'
                or request['operation'] != 'investigate'):
            raise ValueError('No arbitrary models, tools, tokens, refill or API fallback')
        with self.tx() as db:
            e = db.execute('SELECT * FROM execution WHERE id=?', (request['execution'],)).fetchone()
            if (not e or e['state'] != 'approved' or e['deadline'] <= self.clock()
                    or e['principal'] != principal or any(e[k] != request[k] for k in ('task','repository','source'))):
                raise ValueError('Execution expired, stopped, replayed or incorrectly bound')
            generation = self.oauth.verify(self.clock())
            db.execute("UPDATE execution SET state='pending', generation=? WHERE id=?", (generation, e['id']))
            self.record(db, 'turn_reserved', dict(execution=e['id'], generation=generation))
        # Any crash leaves pending; never retry it or return potentially sensitive text.
        event = self.server.turn()
        result = SubscriptionUsageMonitor('fixture-thread', 'fixture-turn').observe(event, 'app_server')
        complete = (event.get('method') == 'turn/completed'
                    and event.get('params', {}).get('threadId') == 'fixture-thread'
                    and event['params'].get('turn', {}).get('id') == 'fixture-turn'
                    and event['params']['turn'].get('status') == 'completed'
                    and event['params']['turn'].get('error') is None)
        state = 'complete' if complete else ('exhausted' if result['state'] == 'exhausted' else 'uncertain')
        with self.tx() as db:
            current = db.execute('SELECT state,deadline FROM execution WHERE id=?', (e['id'],)).fetchone()
            try:
                self.oauth.verify(self.clock())
                valid = current['state'] == 'pending' and self.clock() < current['deadline']
            except ValueError:
                valid = False
            if not valid:
                state = 'uncertain'
            db.execute('UPDATE execution SET state=? WHERE id=?', (state, e['id']))
            self.record(db, 'turn_stopped', dict(execution=e['id'], state=state,
                        usage='synthetic_no_inference', input_tokens=0, output_tokens=0))
        return dict(synthetic=True, state=state, live_execution=False, may_dispatch=False,
                    api_fallback=False, paid_refill=False, credit_purchase=False)


def live_subscription_bridge(*args, **kwargs):
    require_live()
    raise RuntimeError('No verified eligible integration or isolated tool transport')
