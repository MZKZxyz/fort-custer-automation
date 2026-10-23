"""Versioned single-ledger grant authority, SYNTHETIC ONLY in Sprint 6.9.

No live admission/dispatch implementation exists. Legacy approvals are read-only
inputs to explicitly requested synthetic experiments, never migrated live grants.
The future service must exclusively own this ledger and all live claim requests.
"""
import contextlib
import os
from pathlib import Path
import sqlite3
import time
import uuid

from src import orchestration_evidence as e
from src import worker_handoff as wire
from src.concurrency_coordinator import authorization, stopped, validate
from src.source_observation import source_files, manifest

PROTOCOL = 'grant-broker-v1-synthetic'
ACTIVE = {'claimed', 'starting', 'received', 'checking', 'held'}
STATES = ACTIVE | {'validated', 'interrupted'}


class Broker:
    def __init__(self, config, clock=time.time):
        # Reuse strict protected-store/STOP/limits configuration, but a separate
        # protocol prevents accidentally opening the coordinator's historical DB.
        c = e.decode(e.canonical(config))
        e.require(c.pop('schema') == PROTOCOL, 'Unsupported broker configuration')
        c['schema'] = 'concurrency-coordinator-v1'
        self.c = validate(c)
        e.require(self.c['slots'] == 1, 'Broker capacity is exactly one')
        self.path, self.clock = Path(self.c['ledger']).absolute(), clock
        self.config_digest = e.digest(config)

    def initialize(self):
        # Never initialize on inspection/restart, replace lost state, or reuse an
        # alternate ledger in a deployed service. Deployment owns the fixed path.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        e.regular(self.path)
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE metadata(schema TEXT NOT NULL, config TEXT NOT NULL);
                CREATE TABLE grants(execution TEXT PRIMARY KEY, task TEXT UNIQUE NOT NULL,
                    authorization TEXT NOT NULL, claim TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY, execution TEXT NOT NULL REFERENCES grants(execution),
                    at REAL NOT NULL, state TEXT NOT NULL, document TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO metadata VALUES (?,?)', (PROTOCOL, self.config_digest))
            for table in ('metadata', 'grants', 'events'):
                for op in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable broker evidence'); END")
        fd = os.open(self.path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    @contextlib.contextmanager
    def tx(self, write=False):
        e.regular(self.path)
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            if not write: db.execute('PRAGMA query_only=ON')
            else:
                pages = self.c['max_storage_bytes']//db.execute('PRAGMA page_size').fetchone()[0]
                db.execute(f'PRAGMA max_page_count={pages}')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            e.require([tuple(r) for r in db.execute('SELECT * FROM metadata')] == [(PROTOCOL, self.config_digest)],
                      'Broker schema/configuration mismatch')
            e.require({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} ==
                      {'metadata', 'grants', 'events'}, 'Unknown broker schema')
            e.require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and
                      not db.execute('PRAGMA foreign_key_check').fetchall(), 'Broker integrity failure')
            yield db
            if write: db.commit()
        finally: db.close()

    def _event(self, db, claim, state, document):
        now = claim['started'] if state == 'claimed' else self.clock()
        last = db.execute('SELECT MAX(at) FROM events').fetchone()[0]
        e.require(e.finite(now) and (last is None or now >= last), 'Broker clock regression')
        raw = e.canonical(document)
        e.require(len(raw.encode()) <= 4*wire.MAXIMUM, 'Broker evidence ceiling')
        db.execute('INSERT INTO events(execution,at,state,document) VALUES (?,?,?,?)',
                   (claim['execution'], now, state, raw))

    def _rows(self, db):
        e.require(db.execute('SELECT COUNT(*) FROM grants').fetchone()[0] <= self.c['max_tasks'],
                  'Broker task ceiling')
        rows = {}
        for row in db.execute('SELECT * FROM grants'):
            a, c = e.decode(row['authorization']), e.decode(row['claim'])
            e.require(c['execution'] == row['execution'] == a['execution'] and
                      c['task'] == row['task'] == a['task'] and c['authorization'] == e.digest(a) and
                      a['catalog_entry_digest'] == e.digest(a['spec']['task']) and
                      c['mode'] == 'synthetic-only' and e.sha(c['token'], 32) and
                      type(c['generation']) is int and c['generation'] > 0 and
                      c['started'] < c['deadline'] <= a['expires'] and
                      c['deadline'] <= c['started']+a['spec']['limits']['timeout_seconds'] and
                      c['profile'] == 'synthetic-no-isolation-v1', 'Invalid immutable grant')
            rows[row['execution']] = dict(authorization=a, claim=c, state=None, events=[])
        transitions = {'claimed': {None}, 'starting': {'claimed'}, 'received': {'starting'},
                       'checking': {'received'}, 'validated': {'checking'}, 'held': ACTIVE, 'interrupted': {'held'}}
        last = None
        generations = set()
        for event in db.execute('SELECT * FROM events ORDER BY seq'):
            e.require(event['execution'] in rows and e.finite(event['at']) and
                      (last is None or last <= event['at']), 'Orphan or invalid broker chronology')
            last = event['at']; r = rows[event['execution']]; d = e.decode(event['document'])
            state = event['state']; c = r['claim']
            e.require(state in transitions and r['state'] in transitions[state] and
                      d['token'] == c['token'] and d['generation'] == c['generation'],
                      'Invalid broker transition or fence')
            if state == 'claimed':
                e.require(event['at'] == c['started'] and c['generation'] == event['seq'] and
                          c['generation'] not in generations, 'Invalid generation')
                generations.add(c['generation'])
            if state == 'received':
                req = wire.request(r['authorization'], c)
                e.require(d['request'] == req.decode(), 'Changed authorized request')
                captured = wire.ingest(req, d['response'].encode(), event['at'])
                e.require(set(captured) == set(r['authorization']['allowed']), 'Incomplete retained artifacts')
                if 'usage' in d:
                    u = d['usage']
                    e.require(isinstance(u, dict) and set(u) ==
                              {'input_tokens', 'cached_input_tokens', 'output_tokens'} and
                              all(type(v) is int and v >= 0 for v in u.values()) and
                              u['cached_input_tokens'] <= u['input_tokens'], 'Invalid usage evidence')
            if state == 'validated':
                e.require(d['qa_digest'] == e.digest(d['qa']) and
                          d['qa']['token'] == c['token'] and
                          d['qa']['generation'] == c['generation'] and
                          d['qa']['authorization'] == c['authorization'], 'Invalid QA receipt')
                qa = d['qa']; a = r['authorization']; checks = qa['checks']
                e.require(qa['protocol'] == PROTOCOL and qa['execution'] == a['execution'] and
                          qa['task'] == a['task'] and qa['source_manifest'] == a['source_manifest'] and
                          qa['worker_reports_trusted'] is False and
                          qa['publication'] == 'separate-human-review-required' and
                          [q['name'] for q in checks] == ['diff', *[q['name'] for q in a['checks']], 'candidate'] and
                          all(type(q['code']) is int and q['code'] == 0 and q['reason'] is None for q in checks) and
                          [q['command'][1:] for q in checks[1:-1]] == [q['argv'][1:] for q in a['checks']] and
                          checks[-1]['input_hash'] == a['source_manifest'] and
                          checks[-1]['candidate_hash'] == qa['candidate_manifest'] and
                          e.sha(qa['candidate_manifest']), 'Incomplete independent QA evidence')
            if state == 'interrupted':
                e.require(e.sha(d['termination_evidence']) and d['operator'] and d['replay_permitted'] is False,
                          'Missing termination recovery evidence')
            r['state'] = state
            r['events'].append(dict(at=event['at'], state=state, document=d))
        e.require(all(r['state'] in STATES for r in rows.values()) and
                  sum(r['state'] in ACTIVE for r in rows.values()) <= 1, 'Invalid capacity/history')
        return rows

    def inspect(self):
        with self.tx() as db: rows = self._rows(db)
        return dict(schema=PROTOCOL, integrity='verified', live_dispatch=False,
                    atomic_authority='single-broker-ledger-synthetic-only',
                    legacy_migration='blocked-not-migrated', tasks=rows,
                    active=sum(r['state'] in ACTIVE for r in rows.values()),
                    ambiguous=sum(r['state'] in {'held', 'starting', 'checking'} or
                        r['state'] in ACTIVE and (stopped(self.c) or self.clock() >= r['claim']['deadline'])
                        for r in rows.values()), stop=stopped(self.c))

    def claim_synthetic(self, policy, execution, task, worker):
        e.require(self.c['enabled'] and not stopped(self.c), 'Disabled or STOP active')
        e.require(isinstance(worker, str) and 0 < len(worker) <= 64, 'Worker identity required')
        with self.tx(True) as db:
            rows = self._rows(db)
            e.require(execution not in rows and not any(r['authorization']['task'] == task for r in rows.values()),
                      'Authorization already consumed')
            e.require(not any(r['state'] in ACTIVE for r in rows.values()) and
                      len(rows) < self.c['max_tasks'], 'Active or ambiguous worker hold')
            a = authorization(policy, execution, task, self.clock(), self.c)
            a['catalog_entry_digest'] = e.digest(a['spec']['task'])
            now = self.clock()
            c = dict(task=task, execution=execution, authorization=e.digest(a), worker=worker,
                     profile='synthetic-no-isolation-v1', mode='synthetic-only', token=uuid.uuid4().hex,
                     generation=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events').fetchone()[0],
                     started=now, deadline=min(a['expires'], now+a['spec']['limits']['timeout_seconds']))
            wire.request(a, c)  # Validate all wire bindings before consumption.
            db.execute('INSERT INTO grants VALUES (?,?,?,?)', (execution, task, e.canonical(a), e.canonical(c)))
            self._event(db, c, 'claimed', self._fence(c))
            e.require(not stopped(self.c), 'STOP before claim commit')
        return c

    @staticmethod
    def _fence(c): return dict(token=c['token'], generation=c['generation'])

    def _owned(self, db, c, states):
        rows = self._rows(db)
        e.require(c.get('execution') in rows, 'Unknown grant')
        row = rows[c['execution']]
        e.require(row['claim'] == c and row['state'] in states, 'Stale fence or replayed operation')
        return row

    def _guard(self, c):
        e.require(not stopped(self.c) and self.clock() < c['deadline'], 'STOP or expired grant')

    def _fresh(self, a):
        current = authorization(a['policy_path'], a['execution'], a['task'], self.clock(), self.c)
        current['catalog_entry_digest'] = e.digest(current['spec']['task'])
        e.require(current == a, 'Approval/source changed')

    def start_synthetic(self, c):
        # Commit startup intent BEFORE touching an endpoint. An interrupted
        # caller must never call this a second time, including after restart.
        with self.tx(True) as db:
            r = self._owned(db, c, {'claimed'})
            self._guard(c); self._fresh(r['authorization'])
            raw = wire.request(r['authorization'], c)
            self._event(db, c, 'starting', self._fence(c))
            self._guard(c)
        return raw

    def prepare_worker_synthetic(self, c):
        """Prepare exact source bytes without contact, launch or new authority."""
        from src.activation_bundle import worker_bundle
        with self.tx() as db:
            r = self._owned(db, c, {'claimed'})
            self._guard(c); self._fresh(r['authorization'])
            raw = worker_bundle(r['authorization'], c)
            self._guard(c)
        return raw

    def prepare_qa_synthetic(self, c, retained_worker_bundle):
        """Reconstruct captured output for a separate QA principal, no execution."""
        from src.activation_bundle import qa_bundle
        with self.tx() as db:
            r = self._owned(db, c, {'received'})
            self._guard(c); self._fresh(r['authorization'])
            raw = qa_bundle(r['authorization'], c, retained_worker_bundle,
                            r['events'][-1]['document']['response'].encode(), self.clock())
            self._guard(c)
        return raw

    def capture_synthetic(self, c, response, *, usage=None):
        with self.tx(True) as db:
            r = self._owned(db, c, {'starting'})
            self._guard(c)
            req = wire.request(r['authorization'], c)
            files = wire.ingest(req, response, self.clock())
            # Require every allowlisted file exactly once. This v1 protocol
            # supports replacement bytes only, never deletions or file creation.
            e.require(set(files) == set(r['authorization']['allowed']), 'Missing/extra authorized output files')
            document = dict(**self._fence(c), request=req.decode(), response=response.decode())
            if usage is not None:
                from src.codex_worker import TOKENS
                e.require(isinstance(usage, dict) and set(usage) == set(TOKENS) and
                          all(type(v) is int and v >= 0 for v in usage.values()) and
                          usage['cached_input_tokens'] <= usage['input_tokens'], 'Invalid usage telemetry')
                document['usage'] = usage
            self._event(db, c, 'received', document)
            self._guard(c)

    def capture_codex_synthetic(self, c, response, telemetry):
        """Controlled adapter experiment only; exhaustion/unknown retains slot.

        Telemetry is untrusted operational data, never billing enforcement or
        proof that the remote VM and all descendants have terminated.
        """
        from src.codex_worker import usage_outcome
        result = usage_outcome(telemetry)
        if result['state'] != 'complete':
            self.hold(c, 'Codex '+result['state']+'; no retry; external termination review required')
        else:
            self.capture_synthetic(c, response, usage=result['usage'])
        return result

    def validate_synthetic(self, c):
        """Trusted fresh-source reconstruction and fixed checks; no worker QA."""
        from src.concurrency_coordinator import verify_candidate
        with self.tx(True) as db:
            r = self._owned(db, c, {'received'})
            self._guard(c); self._fresh(r['authorization'])
            self._event(db, c, 'checking', self._fence(c))
            self._guard(c)
        self._guard(c); a = r['authorization']; self._fresh(a)
        policy, _, _ = e.catalog(a['policy_path'])
        req = wire.request(a, c)
        delta = wire.ingest(req, r['events'][-1]['document']['response'].encode(), self.clock())
        files = source_files(policy['repositories'][a['spec']['repo']]['source'], a['source'], a['allowed'])
        e.require(manifest(files) == a['source_manifest'], 'Broken source manifest')
        e.require(all(mode == files[name][0] for name, (mode, _) in delta.items()),
                  'Unexpected executable permission change')
        candidate = dict(files); candidate.update(delta)
        changed = sorted(k for k in files if candidate[k] != files[k])
        e.require(bool(changed) and set(changed) <= set(a['allowed']), 'Empty or out-of-scope candidate')
        artifact = dict(source_manifest=manifest(files), candidate_manifest=manifest(candidate),
                        files={k: [candidate[k][0], candidate[k][1].hex()] for k in changed},
                        changed=changed, token=c['token'])
        def guard():
            with self.tx() as db: self._owned(db, c, {'checking'})
            self._guard(c)
        qa = verify_candidate(a, artifact, policy, guard, self.c['max_artifact_bytes'], c['deadline']-self.clock())
        qa.update(protocol=PROTOCOL, generation=c['generation'], publication='separate-human-review-required',
                  isolation='synthetic-local-qa-not-external-isolation')
        with self.tx(True) as db:
            self._owned(db, c, {'checking'}); self._guard(c); self._fresh(a)
            self._event(db, c, 'validated', dict(**self._fence(c), qa=qa, qa_digest=e.digest(qa)))
            self._guard(c)
        return qa

    def hold(self, c, reason):
        e.require(isinstance(reason, str) and 0 < len(reason) <= 512, 'Recovery reason required')
        with self.tx(True) as db:
            self._owned(db, c, ACTIVE)
            self._event(db, c, 'held', dict(**self._fence(c), reason=reason, termination='unconfirmed'))

    def sweep(self):
        with self.tx(True) as db:
            for r in self._rows(db).values():
                if r['state'] in ACTIVE-{'held'} and (stopped(self.c) or self.clock() >= r['claim']['deadline']):
                    c = r['claim']
                    self._event(db, c, 'held', dict(**self._fence(c), reason='STOP or deadline', termination='unconfirmed'))

    def recover(self, c, operator, termination_evidence, response):
        # Trusted operator method, deliberately no remote/caller recovery route.
        # Digest references retained external watchdog/administrator evidence;
        # it is an attestation, not automatic proof that a guest has stopped.
        e.require(isinstance(operator, str) and 0 < len(operator) <= 128 and e.sha(termination_evidence) and
                  response == 'CONFIRM TERMINATED '+e.digest(c)+' '+termination_evidence,
                  'Exact operator termination attestation required')
        with self.tx(True) as db:
            self._owned(db, c, {'held'})
            self._event(db, c, 'interrupted', dict(**self._fence(c), operator=operator,
                        termination_evidence=termination_evidence, replay_permitted=False))

    def dispatch_live(self, *args, **kwargs):
        from src.integration_control import block_live_dispatch
        block_live_dispatch()
        raise ValueError('No live broker implementation')
