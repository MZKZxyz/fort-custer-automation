"""Simulation-only durable control plane. All monetary values are integer cents."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

STATES = ('planned', 'reserved', 'awaiting_approval', 'dispatched', 'running', 'qa',
          'pr_ready', 'completed', 'failed', 'cancelled', 'reconciliation_required')
TABLES = ('execution_events', 'execution_receipts', 'execution_attempts', 'execution_tasks', 'execution_control')


def migrate(path, down=False):
    """Additive transactional migration; downgrade refuses to discard execution data."""
    with sqlite3.connect(path, timeout=30) as db:
        db.execute('BEGIN IMMEDIATE')
        if down:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_tasks'").fetchone():
                if db.execute('SELECT count(*) FROM execution_tasks').fetchone()[0]:
                    raise ValueError('Archive execution ledger and restore backup; downgrade would lose data')
            for table in TABLES:
                db.execute(f'DROP TABLE IF EXISTS {table}')
            return
        db.execute('CREATE TABLE IF NOT EXISTS execution_control (id INTEGER PRIMARY KEY CHECK(id=1), stopped INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO execution_control VALUES (1,0)')
        db.execute(f'''CREATE TABLE IF NOT EXISTS execution_tasks (
            id TEXT PRIMARY KEY, repo TEXT NOT NULL, branch TEXT NOT NULL, area TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN {STATES}), candidate TEXT, qa TEXT, pr TEXT)''')
        db.execute('''CREATE TABLE IF NOT EXISTS execution_attempts (
            id TEXT PRIMARY KEY, task TEXT NOT NULL REFERENCES execution_tasks(id),
            dispatch_key TEXT UNIQUE NOT NULL, day TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved BETWEEN 1 AND 300),
            legacy_task TEXT UNIQUE, actual INTEGER, settled INTEGER NOT NULL DEFAULT 0, owner TEXT,
            lease_until REAL, deadline REAL, stopped INTEGER NOT NULL DEFAULT 0)''')
        db.execute('''CREATE TABLE IF NOT EXISTS execution_receipts (
            receipt TEXT PRIMARY KEY, attempt TEXT UNIQUE NOT NULL, cents INTEGER NOT NULL, source TEXT NOT NULL)''')
        db.execute('CREATE TABLE IF NOT EXISTS execution_events (id INTEGER PRIMARY KEY, task TEXT, event TEXT NOT NULL, payload TEXT NOT NULL)')


class Controller:
    def __init__(self, path, clock, repositories=('synthetic/client', 'synthetic/server'), branches=('main',)):
        self.path, self.clock = path, clock
        self.repositories, self.branches = set(repositories), set(branches)
        migrate(path)

    @contextmanager
    def tx(self):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='s53_control'").fetchone():
                raise ValueError('Sprint 5.3 authority active; legacy execution is fenced')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db

    def event(self, db, task, event, **payload):
        db.execute('INSERT INTO execution_events(task,event,payload) VALUES (?,?,?)', (task, event, json.dumps(payload)))

    def add(self, task, repo, branch, area):
        if repo not in self.repositories or branch not in self.branches or not isinstance(area, str) or not area or any(p in ('', '.', '..') for p in area.split('/')) or '\\' in area:
            raise ValueError('Repository, branch or shared work area denied')
        with self.tx() as db:
            db.execute('INSERT INTO execution_tasks(id,repo,branch,area,state) VALUES (?,?,?,?,?)', (task, repo, branch, area, 'planned'))

    def import_reserved(self, task, branch='main'):
        """Copy trusted planner identity; retain the original reservation row as audit."""
        with self.tx() as db:
            row = db.execute("SELECT t.payload,r.cents FROM tasks t JOIN reservations r ON r.task_id=t.id WHERE t.id=? AND t.state='reserved'", (task,)).fetchone()
            if not row:
                raise ValueError('No verified planning reservation')
            payload = json.loads(row['payload'])
            if payload['id'] != task or payload['reservation_cents'] != row['cents']:
                raise ValueError('Legacy reservation mismatch')
        self.add(task, payload['repo'], branch, payload['area'])

    def reserve(self, task, key, cents=300):
        if type(cents) is not int or not 0 < cents <= 300:
            raise ValueError('Reservation must be 1..300 cents')
        day = datetime.fromtimestamp(self.clock(), ZoneInfo('America/Los_Angeles')).date().isoformat()
        with self.tx() as db:
            old = db.execute('SELECT * FROM execution_attempts WHERE dispatch_key=?', (key,)).fetchone()
            if old:
                if old['task'] != task or old['reserved'] != cents:
                    raise ValueError('Idempotency key reused with different request')
                return old['id']
            if db.execute('SELECT stopped FROM execution_control').fetchone()[0]:
                raise ValueError('Kill switch engaged')
            if db.execute('SELECT 1 FROM execution_tasks WHERE state="reconciliation_required"').fetchone():
                raise ValueError('Unresolved accounting or worker termination')
            t = db.execute('SELECT * FROM execution_tasks WHERE id=?', (task,)).fetchone()
            if not t or t['state'] not in ('planned', 'failed'):
                raise ValueError('Task is not eligible')
            attempts = db.execute('SELECT * FROM execution_attempts WHERE task=?', (task,)).fetchall()
            if len(attempts) >= 3 or any(not a['settled'] or not a['stopped'] for a in attempts):
                raise ValueError('Retry ceiling or unresolved previous attempt')
            active = db.execute("SELECT * FROM execution_tasks WHERE state IN ('reserved','awaiting_approval','dispatched','running','qa','pr_ready','reconciliation_required')").fetchall()
            legacy = []
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='reservations'").fetchone():
                columns = {r[1] for r in db.execute('PRAGMA table_info(reservations)')}
                if columns != {'task_id', 'day', 'cents'}:
                    if db.execute('SELECT count(*) FROM reservations').fetchone()[0]:
                        raise ValueError('Unmapped legacy reservations require operator reconciliation')
                else:
                    legacy = db.execute('SELECT r.*,t.payload,t.state FROM reservations r JOIN tasks t ON t.id=r.task_id').fetchall()
                    if len(legacy) != db.execute('SELECT count(*) FROM reservations').fetchone()[0]:
                        raise ValueError('Orphan legacy reservation')
                    for row in legacy:
                        payload = json.loads(row['payload'])
                        if row['state'] != 'reserved' or row['cents'] != payload['reservation_cents'] or row['cents'] <= 0:
                            raise ValueError('Invalid legacy reservation')
            mapped = {r[0] for r in db.execute('SELECT legacy_task FROM execution_attempts WHERE legacy_task IS NOT NULL')}
            unmapped = [r for r in legacy if r['task_id'] not in mapped]
            own = next((r for r in unmapped if r['task_id'] == task), None)
            others = [r for r in unmapped if r['task_id'] != task]
            def overlaps(left, right):
                return left == right or left.startswith(right+'/') or right.startswith(left+'/')
            areas = [a['area'] for a in active] + [json.loads(r['payload'])['area'] for r in others]
            if len(active)+len(others) >= 3 or any(overlaps(t['area'], area) for area in areas):
                raise ValueError('Concurrency or cross-repository work-area conflict')
            if own:
                payload = json.loads(own['payload'])
                if cents != own['cents'] or t['repo'] != payload['repo'] or t['area'] != payload['area']:
                    raise ValueError('Execution must preserve original reservation and scope')
            used = db.execute('SELECT coalesce(sum(CASE WHEN settled=1 THEN actual ELSE reserved END),0) FROM execution_attempts WHERE day=? OR settled=0', (day,)).fetchone()[0]
            used += sum(r['cents'] for r in others)
            # Older audit-only plans have no reservations table: retain their advisory hold.
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='reservations'").fetchone() and db.execute("SELECT 1 FROM sqlite_master WHERE name='daily_plans'").fetchone():
                plan = db.execute('SELECT report FROM daily_plans WHERE day=?', (day,)).fetchone()
                if plan:
                    from decimal import Decimal, ROUND_CEILING
                    used += int((Decimal(str(json.loads(plan[0])['reserved_usd'])) * 100).to_integral_value(rounding=ROUND_CEILING))
            if used + cents > 1000:
                raise ValueError('Daily budget exhausted')
            execution = str(uuid.uuid4())
            db.execute('INSERT INTO execution_attempts(id,task,dispatch_key,day,reserved,legacy_task) VALUES (?,?,?,?,?,?)', (execution, task, key, day, cents, task if own else None))
            db.execute("UPDATE execution_tasks SET state='reserved',candidate=NULL,qa=NULL WHERE id=?", (task,))
            self.event(db, task, 'reserved', execution=execution, cents=cents)
            db.execute("UPDATE execution_tasks SET state='awaiting_approval' WHERE id=?", (task,))
            return execution

    def dispatch(self, execution, operator):
        if not operator.startswith('human:'):
            raise ValueError('Human approval identity required')
        with self.tx() as db:
            a = db.execute('SELECT * FROM execution_attempts WHERE id=?', (execution,)).fetchone()
            if not a or a['stopped'] or db.execute('SELECT stopped FROM execution_control').fetchone()[0]:
                raise ValueError('Dispatch denied')
            t = db.execute('SELECT state FROM execution_tasks WHERE id=?', (a['task'],)).fetchone()[0]
            if t in ('dispatched', 'running'):
                return execution
            if t != 'awaiting_approval':
                raise ValueError('Invalid dispatch state')
            db.execute("UPDATE execution_tasks SET state='dispatched' WHERE id=?", (a['task'],))
            db.execute('UPDATE execution_attempts SET deadline=?,lease_until=? WHERE id=?', (self.clock()+2400, self.clock()+60, execution))
            self.event(db, a['task'], 'dispatch_approved', operator=operator)
        return execution

    def claim(self, execution, owner):
        with self.tx() as db:
            a = db.execute('SELECT * FROM execution_attempts WHERE id=?', (execution,)).fetchone()
            if not a or a['owner'] or a['stopped']:
                return False
            state = db.execute('SELECT state FROM execution_tasks WHERE id=?', (a['task'],)).fetchone()[0]
            if state != 'dispatched' or self.clock() >= min(a['lease_until'], a['deadline']):
                raise ValueError('Dispatch lease expired')
            db.execute('UPDATE execution_attempts SET owner=? WHERE id=?', (owner, execution))
            db.execute("UPDATE execution_tasks SET state='running' WHERE id=?", (a['task'],))
            return True

    def heartbeat(self, execution, owner):
        with self.tx() as db:
            a = db.execute('SELECT * FROM execution_attempts WHERE id=?', (execution,)).fetchone()
            t = db.execute('SELECT state FROM execution_tasks WHERE id=?', (a['task'],)).fetchone()[0]
            if t != 'running' or a['stopped'] or self.clock() >= min(a['lease_until'], a['deadline']) or a['owner'] != owner:
                raise ValueError('Expired or fenced worker')
            db.execute('UPDATE execution_attempts SET owner=?,lease_until=? WHERE id=?', (owner, min(self.clock()+60, a['deadline']), execution))
            db.execute("UPDATE execution_tasks SET state='running' WHERE id=?", (a['task'],))

    def recover(self, kill=False):
        with self.tx() as db:
            if kill:
                db.execute('UPDATE execution_control SET stopped=1')
            for a in db.execute('SELECT a.*,t.state FROM execution_attempts a JOIN execution_tasks t ON t.id=a.task WHERE a.stopped=0').fetchall():
                if kill or (a['lease_until'] is not None and self.clock() >= min(a['lease_until'], a['deadline'])):
                    state = 'cancelled' if a['state'] in ('reserved', 'awaiting_approval') else 'reconciliation_required'
                    db.execute('UPDATE execution_tasks SET state=? WHERE id=?', (state, a['task']))
                    self.event(db, a['task'], 'stop_requested', reason='kill' if kill else 'expired')

    def settle(self, execution, receipt, cents, source='mock', terminated=True):
        """Trusted adapter input only. Mock cents are synthetic, never billed dollars."""
        with self.tx() as db:
            a = db.execute('SELECT * FROM execution_attempts WHERE id=?', (execution,)).fetchone()
            if not a:
                raise ValueError('Unknown execution')
            if a['settled']:
                prior = db.execute('SELECT * FROM execution_receipts WHERE attempt=?', (execution,)).fetchone()
                if prior['receipt'] != receipt or prior['cents'] != cents:
                    raise ValueError('Conflicting metering')
                return
            if source != 'mock' or not receipt or type(cents) is not int or cents < 0 or cents > a['reserved'] or not terminated:
                db.execute("UPDATE execution_tasks SET state='reconciliation_required' WHERE id=?", (a['task'],))
                self.event(db, a['task'], 'accounting_blocked')
                return False
            db.execute('INSERT INTO execution_receipts VALUES (?,?,?,?)', (receipt, execution, cents, source))
            db.execute('UPDATE execution_attempts SET actual=?,settled=1,stopped=1 WHERE id=?', (cents, execution))
            self.event(db, a['task'], 'synthetic_usage', cents=cents, receipt=receipt)
            return True

    def finish(self, execution, sha=None):
        with self.tx() as db:
            a = db.execute('SELECT * FROM execution_attempts WHERE id=?', (execution,)).fetchone()
            state = db.execute('SELECT state FROM execution_tasks WHERE id=?', (a['task'],)).fetchone()[0]
            if not a['settled'] or not a['stopped'] or state not in ('running', 'reconciliation_required'):
                raise ValueError('Missing metering, termination or invalid state')
            if sha and a['deadline'] is not None and self.clock() >= a['deadline']:
                raise ValueError('Runtime exceeded; candidate fenced')
            if state == 'reconciliation_required' and sha:
                raise ValueError('Expired candidate is fenced')
            if sha and (len(sha) != 40 or any(c not in '0123456789abcdef' for c in sha)):
                raise ValueError('Exact commit SHA required')
            db.execute('UPDATE execution_tasks SET state=?,candidate=? WHERE id=?', ('qa' if sha else 'failed', sha, a['task']))

    def snapshot(self):
        with self.tx() as db:
            return {table: [dict(r) for r in db.execute(f'SELECT * FROM {table}')] for table in TABLES}

