import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from issues import ingest
from orchestrator import ROOT, read_json, schedule
from planning import initialize, plan, markdown
from remote_state import restore, save


class Safety(unittest.TestCase):
    def setUp(self):
        self.settings = read_json(ROOT / 'config/settings.json')
        self.settings['repositories'] = ['owner/repo']
        self.issue = dict(number=1, title='Documentation', state='open',
                          labels=[{'name': 'automation:ready'}, {'name': 'L0'}],
                          body=json.dumps(dict(area='docs', priority=50, estimated_usd=0.01, depends_on=[])))
        self.now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)

    def ingest(self, issues):
        return ingest(self.settings, 'test-token', fetch=lambda *a: issues)

    def test_risk_and_approval_routing(self):
        variants = [self.issue, dict(self.issue, number=2, labels=[{'name': 'L0'}]),
                    dict(self.issue, number=3, title='Change JWT authentication'),
                    dict(self.issue, number=4, body='Please implement this'),
                    dict(self.issue, number=5, labels=self.issue['labels'] + [{'name': 'L3'}])]
        report = schedule(self.settings, self.ingest(variants))
        self.assertEqual([t['id'] for t in report['selected']], ['owner/repo#1'])
        self.assertEqual(len(report['review']), 4)
        self.assertEqual(report['reserved_usd'], 3)
        self.assertIn('Requires your approval', markdown(dict(report, planning_day='2026-10-22')))

    def test_protected_area(self):
        issue = copy.deepcopy(self.issue)
        metadata = json.loads(issue['body'])
        metadata['area'] = '.github/workflows/ci.yml'
        issue['body'] = json.dumps(metadata)
        self.assertEqual(len(schedule(self.settings, self.ingest([issue]))['review']), 1)

    def test_noncanonical_areas_require_review(self):
        for area in ['docs//guide', './docs', 'docs/../api', '/docs', 'docs/']:
            issue = copy.deepcopy(self.issue)
            metadata = json.loads(issue['body'])
            metadata['area'] = area
            issue['body'] = json.dumps(metadata)
            self.assertEqual(len(schedule(self.settings, self.ingest([issue]))['review']), 1)

    def test_duplicate_issue_and_missing_token(self):
        with self.assertRaises(ValueError):
            self.ingest([self.issue, self.issue])
        with self.assertRaises(ValueError):
            ingest(self.settings, fetch=lambda *a: [])

    def test_api_errors_redact_sensitive_exception(self):
        for status in [401, 403, 404, 429, 500, 503]:
            def fetch(*args):
                raise HTTPError('https://api.github.com/private?token=SECRET', status, 'SECRET', {}, None)
            with self.assertRaises(OSError) as error:
                ingest(self.settings, 'SECRET', fetch=fetch)
            self.assertNotIn('SECRET', str(error.exception))

    def test_dependency_verified_closed_and_open(self):
        issue = copy.deepcopy(self.issue)
        metadata = json.loads(issue['body'])
        metadata['depends_on'] = ['owner/repo#2']
        issue['body'] = json.dumps(metadata)
        for state in ['open', 'closed']:
            def fetch(url, token):
                return {'number': 2, 'state': state} if url.endswith('/2') else [issue]
            report = schedule(self.settings, ingest(self.settings, 'test', fetch=fetch))
            self.assertEqual(len(report['selected']), int(state == 'closed'))

    def test_cycles_and_hierarchical_conflicts(self):
        tasks = self.ingest([self.issue])
        second = dict(tasks[0], id='owner/repo#2', area='docs/guide')
        self.assertEqual(len(schedule(self.settings, tasks + [second])['selected']), 1)
        tasks[0]['depends_on'] = [second['id']]
        second['depends_on'] = [tasks[0]['id']]
        self.assertFalse(schedule(self.settings, tasks + [second])['selected'])

    def test_missing_and_corrupt_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'db'
            with self.assertRaises(sqlite3.OperationalError):
                plan(db, self.settings, [], self.now)
            self.assertFalse(db.exists())
            db.write_bytes(b'invalid')
            with self.assertRaises(sqlite3.DatabaseError):
                plan(db, self.settings, [], self.now)

    def test_reservations_survive_days_and_ledger_mismatch(self):
        tasks = self.ingest([self.issue])
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'db'
            initialize(db)
            plan(db, self.settings, tasks, self.now)
            later = plan(db, self.settings, tasks, self.now + timedelta(days=1))
            self.assertFalse(later['selected'])
            self.assertEqual(later['available_before_usd'], 7)
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT state FROM tasks').fetchall(), [('reserved',)])
                con.execute('DELETE FROM reservations')
            with self.assertRaises(ValueError):
                plan(db, self.settings, tasks, self.now + timedelta(days=2))

    def test_concurrent_different_plans_only_one_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'db'
            initialize(db)
            tasks = self.ingest([self.issue])
            def attempt(backlog):
                try:
                    return plan(db, self.settings, backlog, self.now)
                except ValueError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, [tasks, [dict(tasks[0], id='owner/repo#2')]]))
            self.assertEqual(sum(r is not None for r in results), 1)
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT sum(cents) FROM reservations').fetchone()[0], 300)

    def test_bad_budget_and_reservation_precision(self):
        for bad in [float('nan'), float('inf'), True, -1, 11]:
            settings = copy.deepcopy(self.settings)
            settings['budget']['daily_usd'] = bad
            with self.assertRaises(AssertionError):
                schedule(settings, [])
        settings = copy.deepcopy(self.settings)
        settings['budget']['daily_usd'] = 0.05
        settings['budget']['max_task_reservation_usd'] = 0.021
        tasks = self.ingest([self.issue])
        tasks += [dict(tasks[0], id='owner/repo#2', area='tools')]
        report = schedule(settings, tasks)
        self.assertEqual(report['reserved_usd'], 0.03)
        self.assertEqual(len(report['selected']), 1)

    def test_remote_state_missing_and_denied_never_resets(self):
        for status in [403, 404, 500]:
            def request(*args):
                raise HTTPError('url', status, 'denied', {}, None)
            with tempfile.TemporaryDirectory() as directory:
                db = Path(directory) / 'db'
                with self.assertRaises(ValueError):
                    restore(db, 'owner/repo', 'test', request=request)
                self.assertFalse(db.exists())

    def test_remote_compare_and_swap_failure_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'db'
            initialize(db)
            def request(method, path, token, payload):
                self.assertEqual(method, 'PUT')
                self.assertEqual(payload['sha'], 'old-sha')
                raise HTTPError('url', 409, 'stale', {}, None)
            with self.assertRaises(HTTPError):
                save(db, 'owner/repo', 'test', 'old-sha', request=request)
