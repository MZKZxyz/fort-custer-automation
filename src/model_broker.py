"""Task-scoped broker protocol and durable synthetic implementation.

No HTTP forwarding, provider key, arbitrary URL, tools, streaming, background
request or live provider implementation exists here. Worker authority is an
execution-bound authenticated transport identity, not a provider credential.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
from trust import canonical, digest, require_live


class SyntheticProvider:
    synthetic = True
    def respond(self, request, cancelled):
        if cancelled():
            raise ValueError('Cancelled')
        return dict(text='Synthetic maze investigation response', provider_request='synthetic:'+request['request_id'],
                    usage=dict(input_tokens=10, output_tokens=8), cost=dict(kind='synthetic', cents=0))


class ModelBroker:
    """Exclusive ledger owns durable admissions; ambiguous holds survive restart.

    Production mTLS/vsock transport must derive principal independently of worker
    JSON. Live entry is gated even if someone supplies a custom provider object.
    Synthetic initialization is explicit and rejects any existing database.
    """
    def __init__(self, path, provider, clock, *, initialize=False):
        self.path, self.provider, self.clock = Path(path), provider, clock
        if not isinstance(provider, SyntheticProvider):
            require_live()
        if initialize:
            fd = __import__('os').open(self.path, __import__('os').O_CREAT | __import__('os').O_EXCL | __import__('os').O_WRONLY, 0o600)
            __import__('os').close(fd)
            with sqlite3.connect(self.path) as db:
                db.executescript('''CREATE TABLE executions (id TEXT PRIMARY KEY, task TEXT NOT NULL, principal TEXT NOT NULL,
                    deadline INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE requests (id TEXT PRIMARY KEY, execution TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL, response TEXT);
                    CREATE TABLE audit (id INTEGER PRIMARY KEY, at INTEGER NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL);''')
        with self.tx() as db:
            db.execute('SELECT * FROM executions LIMIT 0')

    @contextmanager
    def tx(self):
        with sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True, timeout=5) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            yield db

    def event(self, db, event, payload):
        db.execute('INSERT INTO audit(at,event,payload) VALUES (?,?,?)', (int(self.clock()), event, canonical(payload)))

    def register(self, execution, task, principal, deadline):
        # Called by trusted controller after durable reservation. Never exposed
        # on the worker request transport. This broker supports synthetic CI only.
        if (not re.fullmatch('[a-f0-9]{32}', execution) or not task or not principal
                or type(deadline) is not int or not self.clock() < deadline <= self.clock()+2400):
            raise ValueError('Invalid execution registration')
        with self.tx() as db:
            if db.execute('SELECT 1 FROM executions WHERE revoked=0 AND deadline>?', (self.clock(),)).fetchone():
                raise ValueError('One execution maximum')
            db.execute('INSERT INTO executions VALUES (?,?,?,?,0)', (execution, task, principal, deadline))
            self.event(db, 'registered', dict(execution=execution, task=task, deadline=deadline))

    def revoke(self, execution):
        with self.tx() as db:
            db.execute('UPDATE executions SET revoked=1 WHERE id=?', (execution,))
            self.event(db, 'revoked', dict(execution=execution))

    def active(self, db, execution, principal, task):
        e = db.execute('SELECT * FROM executions WHERE id=?', (execution,)).fetchone()
        if not e or e['revoked'] or e['deadline'] <= self.clock() or e['principal'] != principal or e['task'] != task:
            raise ValueError('Unknown, expired, cancelled or mismatched execution')

    def request(self, principal, raw):
        if not isinstance(raw, bytes) or len(raw) > 32768:
            raise ValueError('Broker request size limit')
        request = json.loads(raw)
        if (not isinstance(request, dict) or set(request) != {'execution', 'task', 'request_id', 'model', 'operation', 'input', 'max_output_tokens'}
                or request['model'] != 'synthetic-codex' or request['operation'] != 'investigate'
                or not isinstance(request['input'], str) or len(request['input'].encode()) > 24000
                or not isinstance(request['request_id'], str) or not re.fullmatch('[a-f0-9]{32}', request['request_id'])
                or type(request['max_output_tokens']) is not int or not 1 <= request['max_output_tokens'] <= 1024):
            raise ValueError('Broker allowlist or response limit rejected')
        # Durable one-request admission works across multiple broker processes.
        with self.tx() as db:
            self.active(db, request['execution'], principal, request['task'])
            prior = db.execute('SELECT * FROM requests WHERE id=?', (request['request_id'],)).fetchone()
            if prior:
                if prior['fingerprint'] != digest(request) or prior['state'] != 'complete':
                    raise ValueError('Ambiguous or conflicting request; retain hold and reconcile')
                return json.loads(prior['response'])
            if db.execute("SELECT 1 FROM requests WHERE state='pending'").fetchone():
                raise ValueError('One model request maximum; unresolved in-flight hold')
            db.execute('INSERT INTO requests VALUES (?,?,?,?,NULL)',
                       (request['request_id'], request['execution'], digest(request), 'pending'))
            self.event(db, 'request_reserved', dict(execution=request['execution'], request=digest(request), synthetic=True))
        def cancelled():
            try:
                with self.tx() as db:
                    self.active(db, request['execution'], principal, request['task'])
                return False
            except ValueError:
                return True
        # Failure or controller crash intentionally leaves pending record.
        result = self.provider.respond(request, cancelled)
        if (len(canonical(result).encode()) > 16384 or not isinstance(result.get('text'), str)
                or len(result['text'].encode()) > request['max_output_tokens']*4
                or result.get('cost', {}).get('kind') != 'synthetic'
                or result.get('usage', {}).get('output_tokens', 1025) > request['max_output_tokens']):
            raise ValueError('Provider response rejected; reservation retained')
        with self.tx() as db:
            self.active(db, request['execution'], principal, request['task'])
            db.execute("UPDATE requests SET state='complete', response=? WHERE id=?", (canonical(result), request['request_id']))
            self.event(db, 'response', dict(execution=request['execution'], request=request['request_id'],
                                         provenance=result, billed=False))
        return result


def live_broker(*args, **kwargs):
    require_live()
