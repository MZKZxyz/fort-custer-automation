"""Fort Custer automation MVP: strict dry-run scheduler, no live execution.

Python 3.11+ standard library only. Never invokes Codex or GitHub write APIs.
"""
import argparse
from datetime import datetime
import json
import os
import math
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(Path(path).read_text())


def validate(settings):
    numeric = [settings['budget']['daily_usd'], settings['budget']['max_task_reservation_usd']]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in numeric):
        raise AssertionError('Invalid budget')
    checks = [
        settings['budget']['fail_closed_if_metering_unavailable'] is True,
        settings['mode'] == 'dry_run',
        type(settings['agents']['max_concurrent_coding']) is int and 0 <= settings['agents']['max_concurrent_coding'] <= 3,
        0 <= settings['budget']['daily_usd'] <= 10,
        0 < settings['budget']['max_task_reservation_usd'] <= settings['budget']['daily_usd'],
        settings['budget']['max_task_reservation_usd'] <= 3,
        type(settings['agents']['max_retries']) is int and 0 <= settings['agents']['max_retries'] <= 2,
        0 < settings['agents']['max_task_runtime_minutes'] <= 40,
        settings['execution']['network_access'] is False,
        settings['security']['allow_agent_workflow_edits'] is False,
        settings['execution']['enabled'] is False,
        settings['release']['auto_merge'] is False,
        settings['release']['production_deploy'] is False,
        settings['release']['human_approval_required'] is True,
        settings['security']['production_database_access'] is False,
    ]
    if not all(checks):
        raise AssertionError('Only bounded dry-run planning with human release approval is supported')


def schedule(settings, backlog, already_completed=(), already_running=(), already_reserved=0):
    """Compute an advisory schedule. No side effects or dispatch.

    Areas act as an exclusive lease across overlapping tasks. Cross-repo API
    contracts require a manually declared common area to serialize correctly.
    """
    validate(settings)
    max_n = settings['agents']['max_concurrent_coding']
    available = settings['budget']['daily_usd'] - already_reserved
    if not math.isfinite(already_reserved) or already_reserved < 0 or available < 0:
        raise ValueError('Invalid prior budget')
    selected, areas, used, skipped, review = [], set(), 0, [], []
    available_cents = int(Decimal(str(available)) * 100)
    if len({t['id'] for t in backlog}) != len(backlog):
        raise ValueError('Duplicate task identity')
    completed = set(already_completed)
    running_ids = {t['id'] for t in already_running}
    for t in already_running:
        areas.add(t['area'])
    tasks = sorted(backlog, key=lambda t: (-t.get('priority', 0), t['id']))
    for task in tasks:
        reasons = []
        review_reasons = list(task.get('review_reasons', []))
        if task.get('risk') not in ('L0', 'L1', 'L2'):
            review_reasons.append('high or unverified risk requires approval')
        if review_reasons:
            review.append(dict(task, review_reasons=sorted(set(review_reasons))))
            continue
        if task['id'] in running_ids or task['id'] in completed:
            reasons.append('already running or complete')
        if not set(task.get('depends_on', [])).issubset(completed | set(task.get('verified_closed_dependencies', []))):
            reasons.append('unmet dependency')
        if any(task['area'].rstrip('/') == area.rstrip('/') or task['area'].startswith(area.rstrip('/') + '/') or area.startswith(task['area'].rstrip('/') + '/') for area in areas):
            reasons.append('exclusive area occupied')
        if len(selected) + len(already_running) >= max_n:
            reasons.append('concurrency ceiling')
        estimate = float(task['estimated_usd'])
        if not math.isfinite(estimate) or estimate <= 0 or estimate > settings['budget']['max_task_reservation_usd']:
            reasons.append('invalid or excessive reservation')
        # Reserve the configured per-task maximum, never an untrusted issue estimate.
        cents = int((Decimal(str(settings['budget']['max_task_reservation_usd'])) * 100).to_integral_value(rounding=ROUND_CEILING))
        if used + cents > available_cents:
            reasons.append('daily budget ceiling')
        if reasons:
            skipped.append({'id':task['id'], 'reasons':reasons})
            continue
        selected.append(dict(task, reservation_cents=cents))
        areas.add(task['area'])
        used += cents
    return {'mode':'dry_run', 'selected':selected, 'reserved_usd':used / 100,
            'available_before_usd':round(available,2), 'skipped':skipped, 'review': review,
            'execution_performed':False, 'merges_performed':False}


def record_report(db_path, report, timezone):
    """Store a local advisory audit entry. No billing claim is implied."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, timestamp TEXT, mode TEXT, report TEXT)')
        con.execute('INSERT INTO audit(timestamp, mode, report) VALUES (?, ?, ?)',
                    (datetime.now(ZoneInfo(timezone)).isoformat(), report['mode'], json.dumps(report)))


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in {'init','sync','queue','inspect','status','report','preview'}:
        from src.task_orchestration import main as operational_main
        return operational_main(sys.argv[1:])
    p = argparse.ArgumentParser()
    p.add_argument('--initialize-state', action='store_true', help='Explicitly bootstrap a NEW ledger')
    p.add_argument('--source', choices=['sample', 'github'], default='sample')
    p.add_argument('--settings', default=ROOT/'config/settings.json')
    p.add_argument('--backlog', default=ROOT/'examples/backlog.json')
    p.add_argument('--out', default=ROOT/'examples/latest-report.json')
    p.add_argument('--db', default=ROOT/'state/automation.db')
    args = p.parse_args()
    settings = read_json(args.settings)
    validate(settings)
    from issues import ingest
    from planning import plan, initialize, markdown
    backlog = ingest(settings, os.environ.get('GITHUB_TOKEN')) if args.source == 'github' else read_json(args.backlog)
    if args.initialize_state:
        initialize(args.db)
    result = plan(args.db, settings, backlog)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2)+'\n')
    Path(args.out).with_suffix('.md').write_text(markdown(result))
    record_report(args.db, result, settings['timezone'])
    print(f"Advisory plan saved: {len(result['selected'])} selected, {len(result['review'])} require approval; execution disabled.")


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Do not print untrusted API payloads or credential-bearing exceptions.
        raise SystemExit('Planning failed closed. Verify configuration, GitHub read permissions and persistent state.') from None

