"""Transactional advisory plans, task states and conservative reservations."""
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from orchestrator import schedule, validate


def initialize(db_path):
    """Explicit bootstrap only. Never silently replace missing persistent state."""
    path = Path(db_path)
    if path.exists():
        raise ValueError('State already exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript('''
            CREATE TABLE metadata (version INTEGER NOT NULL);
            INSERT INTO metadata VALUES (1);
            CREATE TABLE daily_plans (day TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, report TEXT NOT NULL);
            CREATE TABLE tasks (id TEXT PRIMARY KEY, state TEXT NOT NULL CHECK(state IN ('reserved','review','blocked')), payload TEXT NOT NULL);
            CREATE TABLE reservations (task_id TEXT PRIMARY KEY REFERENCES tasks(id), day TEXT NOT NULL, cents INTEGER NOT NULL CHECK(cents > 0));
        ''')


def plan(db_path, settings, backlog, now=None):
    validate(settings)
    instant = now or datetime.now(ZoneInfo(settings['timezone']))
    if instant.tzinfo is None:
        raise ValueError('Planning timestamp must have timezone')
    day = instant.astimezone(ZoneInfo(settings['timezone'])).date().isoformat()
    fingerprint = hashlib.sha256(json.dumps({'settings': settings, 'backlog': sorted(backlog, key=lambda t: t['id'])}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if len({t['id'] for t in backlog}) != len(backlog):
        raise ValueError('Duplicate task identity')
    # mode=rw refuses to create a fresh database on missing state.
    with sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=rw', uri=True, timeout=30) as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('State integrity cannot be verified')
        if con.execute('SELECT version FROM metadata').fetchall() != [(1,)]:
            raise ValueError('Unsupported state version')
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='execution_tasks'").fetchone():
            if con.execute('SELECT count(*) FROM execution_tasks').fetchone()[0]:
                raise ValueError('Execution ledger active: use execution controller; advisory replanning is frozen')
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='s53_control'").fetchone():
            raise ValueError('Use unified Sprint 5.3 authority for planning')
        # Verify the complete ledger, including old-day active reservations.
        rows = con.execute('SELECT id, state, payload FROM tasks').fetchall()
        reservations = con.execute('SELECT task_id, day, cents FROM reservations').fetchall()
        active = {key: json.loads(payload) for key, state, payload in rows if state == 'reserved'}
        if set(active) != {r[0] for r in reservations}:
            raise ValueError('Task and reservation ledger disagree')
        if any(type(cents) is not int or cents <= 0 or cents != active[key]['reservation_cents'] for key, _, cents in reservations):
            raise ValueError('Invalid reservation ledger')
        if any(task.get('id') != key or not isinstance(task.get('area'), str) for key, task in active.items()):
            raise ValueError('Invalid active task identity or conflict area')
        if len(active) > settings['agents']['max_concurrent_coding']:
            raise ValueError('Active task ceiling exceeded')
        reserved_cents = sum(cents for _, _, cents in reservations)
        if reserved_cents > int(settings['budget']['daily_usd'] * 100):
            raise ValueError('Budget cannot be verified')
        previous = con.execute('SELECT fingerprint, report FROM daily_plans WHERE day=?', (day,)).fetchone()
        if previous:
            if previous[0] != fingerprint:
                raise ValueError('Daily plan already exists with different inputs; retain original plan')
            return json.loads(previous[1])
        report = schedule(settings, backlog, already_running=list(active.values()), already_reserved=reserved_cents / 100)
        report.update(active_reservations=list(active.values()), held_reservation_usd=reserved_cents / 100, planning_day=day, generated_at=instant.isoformat(), input_fingerprint=fingerprint,
                      qa_status='not_run', release_status='not_approved')
        states = {t['id']: 'review' for t in report['review']}
        states.update({t['id']: 'blocked' for t in report['skipped']})
        states.update({t['id']: 'reserved' for t in report['selected']})
        selected = {t['id']: t for t in report['selected']}
        for task in backlog:
            if task['id'] in active:
                continue
            con.execute('INSERT OR REPLACE INTO tasks VALUES (?, ?, ?)',
                        (task['id'], states[task['id']], json.dumps(selected.get(task['id'], task), allow_nan=False)))
        for task in report['selected']:
            con.execute('INSERT INTO reservations VALUES (?, ?, ?)', (task['id'], day, task['reservation_cents']))
        con.execute('INSERT INTO daily_plans VALUES (?, ?, ?)', (day, fingerprint, json.dumps(report, allow_nan=False)))
        return report


def markdown(report):
    def safe(value):
        import html
        return html.escape(str(value)).replace('\n', ' ').replace('\r', ' ').replace('|', '\\|')
    lines = [f"# Daily development plan — {report['planning_day']}", '',
             'Advisory dry run. No execution, issue writes, merges or deployments.', '',
             f"New reservations: ${report['reserved_usd']:.2f}; available before planning: ${report['available_before_usd']:.2f}.",
             '', '## Selected candidates', '']
    for task in report['selected']:
        lines.append(f"- {safe(task['id'])}: {safe(task.get('title', ''))} ({task['risk']}, ${task['reservation_cents']/100:.2f})")
    if not report['selected']:
        lines.append('None.')
    lines += ['', '## Existing held reservations', '']
    lines += [f"- {safe(t['id'])}: {safe(t['area'])} (${t['reservation_cents']/100:.2f})" for t in report.get('active_reservations', [])] or ['None.']
    for title, key, reasons in [('Requires your approval', 'review', 'review_reasons'), ('Deferred or blocked', 'skipped', 'reasons')]:
        lines += ['', f'## {title}', '']
        lines += [f"- {safe(t['id'])}: {safe(t.get('title', ''))} — {safe('; '.join(t[reasons]))}" for t in report[key]] or ['None.']
    return '\n'.join(lines) + '\n'


