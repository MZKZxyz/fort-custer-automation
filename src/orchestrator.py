"""Fort Custer automation MVP: strict dry-run scheduler, no live execution.

Python 3.11+ standard library only. Never invokes Codex or GitHub write APIs.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(Path(path).read_text())


def validate(settings):
    assert settings['mode'] == 'dry_run', 'Only dry_run mode is implemented'
    assert settings['agents']['max_concurrent_coding'] <= 3
    assert settings['budget']['daily_usd'] <= 10
    assert settings['execution']['enabled'] is False
    assert settings['release']['auto_merge'] is False
    assert settings['release']['production_deploy'] is False
    assert settings['security']['production_database_access'] is False


def schedule(settings, backlog, already_completed=(), already_running=(), already_reserved=0):
    """Compute an advisory schedule. No side effects or dispatch.

    Areas act as an exclusive lease across overlapping tasks. Cross-repo API
    contracts require a manually declared common area to serialize correctly.
    """
    validate(settings)
    max_n = settings['agents']['max_concurrent_coding']
    available = settings['budget']['daily_usd'] - already_reserved
    selected, areas, used, skipped = [], set(), 0.0, []
    completed = set(already_completed)
    running_ids = {t['id'] for t in already_running}
    for t in already_running:
        areas.add(t['area'])
    tasks = sorted(backlog, key=lambda t: (-t['priority'], t['id']))
    for task in tasks:
        reasons = []
        if task['id'] in running_ids or task['id'] in completed:
            reasons.append('already running or complete')
        if not set(task.get('depends_on', [])).issubset(completed):
            reasons.append('unmet dependency')
        if task['area'] in areas:
            reasons.append('exclusive area occupied')
        if len(selected) + len(already_running) >= max_n:
            reasons.append('concurrency ceiling')
        estimate = float(task['estimated_usd'])
        if estimate <= 0 or estimate > settings['budget']['max_task_reservation_usd']:
            reasons.append('invalid or excessive reservation')
        if used + estimate > available + 1e-9:
            reasons.append('daily budget ceiling')
        if reasons:
            skipped.append({'id':task['id'], 'reasons':reasons})
            continue
        selected.append(task)
        areas.add(task['area'])
        used += estimate
    return {'mode':'dry_run', 'selected':selected, 'reserved_usd':round(used,2),
            'available_before_usd':round(available,2), 'skipped':skipped,
            'execution_performed':False, 'merges_performed':False}


def record_report(db_path, report, timezone):
    """Store a local advisory audit entry. No billing claim is implied."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, timestamp TEXT, mode TEXT, report TEXT)')
        con.execute('INSERT INTO audit(timestamp, mode, report) VALUES (?, ?, ?)',
                    (datetime.now(ZoneInfo(timezone)).isoformat(), report['mode'], json.dumps(report)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--settings', default=ROOT/'config/settings.json')
    p.add_argument('--backlog', default=ROOT/'examples/backlog.json')
    p.add_argument('--out', default=ROOT/'examples/latest-report.json')
    p.add_argument('--db', default=ROOT/'state/automation.db')
    args = p.parse_args()
    settings = read_json(args.settings)
    result = schedule(settings, read_json(args.backlog))
    result['generated_at'] = datetime.now(ZoneInfo(settings['timezone'])).isoformat()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2)+'\n')
    record_report(args.db, result, settings['timezone'])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
