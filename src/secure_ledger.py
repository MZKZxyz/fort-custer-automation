"""Sprint 5.3 single-writer authority, additive to immutable 5.1/5.2 history.

Only a trusted service owns this file. Worker/QA containers never mount it.
All admissions/approval consumption/claims use BEGIN IMMEDIATE, including plans.
"""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo
from trust import canonical, digest, sha, require_live


class Ledger:
    def __init__(self, path, verifier, clock, repositories, *, synthetic=False):
        self.path, self.verifier, self.clock = Path(path), verifier, clock
        self.repositories, self.synthetic = frozenset(repositories), synthetic
        # Existing verified ledger only: no silent bootstrap after state loss.
        with self.tx() as db:
            if db.execute('SELECT version FROM metadata').fetchall() != [(1,)]:
                raise ValueError('Unsupported planning ledger')
            db.execute('CREATE TABLE IF NOT EXISTS s53_control (id INTEGER PRIMARY KEY CHECK(id=1), stopped INTEGER NOT NULL, synthetic INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO s53_control VALUES (1,0,?)', (int(synthetic),))
            if db.execute('SELECT synthetic FROM s53_control').fetchone()[0] != int(synthetic):
                raise ValueError('Cannot mix synthetic and operational accounting')
            db.execute('''CREATE TABLE IF NOT EXISTS s53_runs (
                id TEXT PRIMARY KEY, task TEXT NOT NULL, spec TEXT NOT NULL, state TEXT NOT NULL,
                day TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved BETWEEN 1 AND 300),
                owner TEXT, lease REAL, deadline REAL, stopped INTEGER NOT NULL DEFAULT 0,
                candidate TEXT, qa TEXT, pr TEXT, final INTEGER, final_day TEXT, legacy INTEGER NOT NULL DEFAULT 0)''')
            db.execute('CREATE TABLE IF NOT EXISTS s53_grants (nonce TEXT PRIMARY KEY, action TEXT NOT NULL, envelope TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS s53_events (id INTEGER PRIMARY KEY, at REAL NOT NULL, run TEXT, event TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS s53_qa_reports (digest TEXT PRIMARY KEY, report TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS s53_usage (id INTEGER PRIMARY KEY, run TEXT NOT NULL, kind TEXT NOT NULL, evidence TEXT NOT NULL)')
            # Append-only records against accidental controller SQL mutations.
            for table in ('s53_grants', 's53_events', 's53_usage', 's53_qa_reports'):
                for action in ('UPDATE', 'DELETE'):
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_{action} BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT,'Immutable audit record'); END''')

    @contextmanager
    def tx(self):
        with sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True, timeout=30) as db:
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('Corrupt ledger')
            db.execute('BEGIN IMMEDIATE')
            yield db

    def event(self, db, run, event, payload):
        db.execute('INSERT INTO s53_events(at,run,event,payload) VALUES (?,?,?,?)',
                   (self.clock(), run, event, canonical(payload)))

    def day(self):
        return datetime.fromtimestamp(self.clock(), ZoneInfo('America/Los_Angeles')).date().isoformat()

    def enabled(self, db):
        if db.execute('SELECT stopped FROM s53_control').fetchone()[0]:
            raise ValueError('Persistent kill switch engaged')

    def rows(self, db):
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM s53_runs')]

    def legacy(self, db):
        """Only planning-only ledgers can be upgraded automatically.

        Nonempty 5.2 execution ledgers need a reviewed mapping before takeover;
        ambiguous settlement is never inferred from synthetic receipts.
        """
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_tasks'").fetchone():
            if db.execute('SELECT count(*) FROM execution_tasks').fetchone()[0]:
                raise ValueError('Sprint 5.2 execution history requires reviewed migration mapping')
        rows = db.execute('SELECT r.task_id,r.cents,t.state,t.payload FROM reservations r JOIN tasks t ON t.id=r.task_id').fetchall()
        if len(rows) != db.execute('SELECT count(*) FROM reservations').fetchone()[0]:
            raise ValueError('Orphan reservation')
        reserved = {r[0] for r in db.execute("SELECT id FROM tasks WHERE state='reserved'")}
        if reserved != {r[0] for r in rows}:
            raise ValueError('Reservation identity mismatch')
        result = {}
        for task, cents, state, payload in rows:
            p = json.loads(payload)
            if state != 'reserved' or p['id'] != task or type(cents) is not int or not 0 < cents <= 300 or cents != p['reservation_cents']:
                raise ValueError('Unverifiable legacy hold')
            result[task] = p
        return result

    def accounting(self, db):
        runs, legacy = self.rows(db), self.legacy(db)
        mapped = {r['task'] for r in runs if r['legacy']}
        holds = [p for t, p in legacy.items() if t not in mapped]
        used = sum(p['reservation_cents'] for p in holds)
        for r in runs:
            if r['final'] is None or r['day'] == self.day() or r['final_day'] == self.day():
                used += r['reserved'] if r['final'] is None else r['final']
        return runs, legacy, holds, used

    def plan(self, settings, backlog):
        from orchestrator import schedule
        if settings['timezone'] != 'America/Los_Angeles':
            raise ValueError('Accounting timezone mismatch')
        inputs={'settings':settings,'backlog':sorted(backlog,key=lambda t:t['id'])}
        fingerprint=digest(inputs)
        import hashlib
        legacy_fingerprint=hashlib.sha256(json.dumps(inputs,sort_keys=True,allow_nan=False).encode()).hexdigest()
        with self.tx() as db:
            self.enabled(db)
            runs, legacy, holds, used = self.accounting(db)
            prior = db.execute('SELECT fingerprint,report FROM daily_plans WHERE day=?', (self.day(),)).fetchone()
            if prior:
                if prior[0] not in (fingerprint,legacy_fingerprint):
                    raise ValueError('Immutable daily decision already exists')
                return json.loads(prior[1])
            # A durable task identity can never be independently selected again.
            owned = set(legacy) | {r['task'] for r in runs}
            mapped={r['task'] for r in runs if r['legacy']}
            active=[p for task,p in legacy.items() if task not in mapped]
            active += [dict(id=r['task'],area=json.loads(r['spec'])['area']) for r in runs if r['state'] not in ('completed','failed') or r['final'] is None or not r['stopped']]
            result = schedule(settings, backlog, already_running=active, already_completed=owned, already_reserved=used/100)
            for p in result['selected']:
                if p['id'] in owned:
                    raise ValueError('Task already owned')
                db.execute('INSERT OR REPLACE INTO tasks VALUES (?,?,?)', (p['id'],'reserved',canonical(p)))
                db.execute('INSERT INTO reservations VALUES (?,?,?)', (p['id'],self.day(),p['reservation_cents']))
            result.update(planning_day=self.day(), authority='sprint-5.3', input_fingerprint=fingerprint,
                          qa_status='not_run', release_status='not_approved')
            db.execute('INSERT INTO daily_plans VALUES (?,?,?)', (self.day(),fingerprint,canonical(result)))
            self.event(db,None,'daily_plan',{'day':self.day(),'fingerprint':fingerprint})
            return result

    def validate_spec(self, spec):
        required = {'task','repo','branch','source','area','allowed'}
        if set(spec) != required or spec['repo'] not in self.repositories:
            raise ValueError('Repository or scope denied')
        if not re.fullmatch(re.escape(spec['repo'])+r'#[1-9][0-9]*',spec['task']):
            raise ValueError('Canonical issue identity required')
        if not re.fullmatch(r'task/[a-z0-9][a-z0-9-]{0,63}', spec['branch']):
            raise ValueError('Explicit task branch required')
        sha(spec['source'])
        for name in [spec['area'], *spec['allowed']]:
            from independent_qa import safe_path, protected
            if not safe_path(name) or protected(name):
                raise ValueError('Protected or invalid task scope')
        if not spec['allowed'] or sorted(set(spec['allowed'])) != spec['allowed']:
            raise ValueError('Explicit unique sorted file scope required')

    def request(self, spec, action='dispatch', candidate=None, qa_digest=None):
        self.validate_spec(spec)
        binding = dict(spec=spec)
        if action == 'publish':
            binding.update(candidate=sha(candidate), qa=qa_digest)
        elif action != 'dispatch':
            raise ValueError('Unknown action')
        return binding

    def dispatch(self, spec, grant):
        self.validate_spec(spec)
        if not self.synthetic:
            require_live()
        with self.tx() as db:
            self.enabled(db)
            runs, legacy, holds, used = self.accounting(db)
            previous = [r for r in runs if r['task'] == spec['task']]
            if len(previous) >= 3 or any(r['state'] != 'failed' or not r['stopped'] or r['final'] is None for r in previous):
                raise ValueError('Task owned or retry unresolved/ceiling')
            if any(r['state'] in ('dispatched','running','stopping','reconciliation_required') for r in runs):
                raise ValueError('One-agent concurrency or unresolved termination')
            if any(json.loads(r['spec'])['branch'] == spec['branch'] and r['task'] != spec['task'] for r in runs):
                raise ValueError('Branch already owned')
            own = legacy.get(spec['task']) if not previous else None
            if own and (own['repo'] != spec['repo'] or own['area'] != spec['area'] or own['reservation_cents'] != 300):
                raise ValueError('Planning scope/reservation mismatch')
            def overlap(a,b):
                return a==b or a.startswith(b+'/') or b.startswith(a+'/')
            if any(p['id'] != spec['task'] and overlap(p['area'],spec['area']) for p in holds):
                raise ValueError('Planning area owned')
            if any(r['task'] != spec['task'] and r['state'] not in ('failed','completed') and overlap(json.loads(r['spec'])['area'],spec['area']) for r in runs):
                raise ValueError('Execution area owned')
            if used + (0 if own else 300) > 1000:
                raise ValueError('Daily budget ceiling')
            operator = self.verifier.consume(db, grant, 'dispatch', self.request(spec), self.clock())
            run = uuid.uuid4().hex
            db.execute('INSERT INTO s53_runs(id,task,spec,state,day,reserved,lease,deadline,legacy) VALUES (?,?,?,?,?,?,?,?,?)',
                       (run,spec['task'],canonical(spec),'dispatched',self.day(),300,self.clock()+60,self.clock()+2400,int(bool(own))))
            self.event(db,run,'dispatch_authorized',dict(operator=operator,spec=spec,grant=grant['payload']['nonce']))
            return run

    def claim(self, run, owner):
        with self.tx() as db:
            self.enabled(db)
            r = self.get(db,run)
            if r['state'] != 'dispatched' or r['owner'] or self.clock() >= min(r['lease'],r['deadline']):
                raise ValueError('Lease unavailable')
            db.execute("UPDATE s53_runs SET state='running',owner=? WHERE id=?",(owner,run))
            self.event(db,run,'claimed',dict(owner=owner))

    def heartbeat(self, run, owner):
        with self.tx() as db:
            self.enabled(db)
            r=self.get(db,run)
            if r['owner'] != owner or r['state'] != 'running' or self.clock() >= min(r['lease'],r['deadline']):
                raise ValueError('Worker fenced')
            db.execute('UPDATE s53_runs SET lease=? WHERE id=?',(min(self.clock()+60,r['deadline']),run))

    def get(self, db, run):
        db.row_factory=sqlite3.Row
        r=db.execute('SELECT * FROM s53_runs WHERE id=?',(run,)).fetchone()
        if not r:
            raise ValueError('Unknown execution')
        return dict(r)

    def stop(self, grant=None, *, run=None):
        with self.tx() as db:
            if run is None:
                self.verifier.consume(db,grant,'kill',{'ledger':'sprint-5.3'},self.clock())
                db.execute('UPDATE s53_control SET stopped=1')
            targets=[r for r in self.rows(db) if (run is None or r['id']==run) and r['state'] in ('dispatched','running','stopping','reconciliation_required')]
            for r in targets:
                db.execute("UPDATE s53_runs SET state='stopping' WHERE id=?",(r['id'],))
                self.event(db,r['id'],'termination_requested',{'kill':run is None})

    def recover(self):
        # Restart recovery never guesses that an orphan process is dead.
        with self.tx() as db:
            for r in self.rows(db):
                if r['state'] in ('dispatched','running','stopping') and (r['state']=='stopping' or self.clock()>=min(r['lease'],r['deadline'])):
                    db.execute("UPDATE s53_runs SET state='reconciliation_required' WHERE id=?",(r['id'],))
                    self.event(db,r['id'],'recovery_fenced',{'reservation_retained':r['reserved']})

    def terminated(self, run):
        # Trusted supervisor calls only after cgroup/container absence verified.
        with self.tx() as db:
            r=self.get(db,run)
            db.execute('UPDATE s53_runs SET stopped=1 WHERE id=?',(run,))
            self.event(db,run,'termination_verified',{'prior_state':r['state']})

    def record_usage(self, run, evidence, verifier):
        # Usage has provenance from controller transport, never worker files.
        verifier(evidence,run,self.clock())
        with self.tx() as db:
            self.get(db,run)
            prior=db.execute('SELECT evidence FROM s53_usage WHERE run=? AND kind="observed"',(run,)).fetchall()
            if prior:
                if any(p[0]!=canonical(evidence) for p in prior):
                    db.execute("UPDATE s53_runs SET state='reconciliation_required' WHERE id=?",(run,))
                    self.event(db,run,'conflicting_usage',{'reservation_retained':True})
                    return False
                return True
            db.execute('INSERT INTO s53_usage(run,kind,evidence) VALUES (?,?,?)',(run,'observed',canonical(evidence)))
            self.event(db,run,'usage_observed',{'digest':digest(evidence),'billed':False})

    def finalize(self, run, evidence, verify_billing):
        verify_billing(evidence,run,self.clock())
        with self.tx() as db:
            r=self.get(db,run)
            cents=evidence.get('cents')
            if type(cents) is not int or not 0 <= cents <= r['reserved'] or not r['stopped'] or r['final'] is not None:
                raise ValueError('Final billing/termination invalid')
            if evidence.get('synthetic') is not self.synthetic:
                raise ValueError('Accounting provenance mismatch')
            db.execute('UPDATE s53_runs SET final=?,final_day=? WHERE id=?',(cents,self.day(),run))
            db.execute('INSERT INTO s53_usage(run,kind,evidence) VALUES (?,?,?)',(run,'finalized',canonical(evidence)))
            self.event(db,run,'billing_reconciled',{'cents':cents,'evidence':digest(evidence)})

    def finish(self, run, candidate=None):
        with self.tx() as db:
            r=self.get(db,run)
            if not r['stopped'] or r['final'] is None or r['state'] not in ('running','dispatched','stopping','reconciliation_required'):
                raise ValueError('Unresolved reservation/termination or invalid terminal transition')
            if candidate and (r['state'] != 'running' or self.clock()>=r['deadline']):
                raise ValueError('Candidate fenced')
            if candidate:
                self.enabled(db)
                sha(candidate)
                if not db.execute('SELECT 1 FROM s53_usage WHERE run=? AND kind="observed"',(run,)).fetchone():
                    raise ValueError('Missing observed usage')
            db.execute('UPDATE s53_runs SET state=?,candidate=? WHERE id=?',('qa' if candidate else 'failed',candidate,run))
            self.event(db,run,'candidate' if candidate else 'failed',{'sha':candidate})
