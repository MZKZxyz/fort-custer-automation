import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from orchestrator import ROOT, read_json, validate
from issues import ingest, parse_issue
from planning import plan, initialize


class Sprint51(unittest.TestCase):
    def setUp(self):
        self.settings = read_json(ROOT / 'config/settings.json')
        self.settings['planning']['github'] = {'eligible_label': 'automation:ready'}
        self.backlog = read_json(ROOT / 'examples/backlog.json')
        self.issue = {'number': 1, 'title': 'task\x00', 'state': 'open',
                      'labels': [{'name': 'automation:ready'}],
                      'body': json.dumps(dict(area='ui', priority=50, estimated_usd=2, depends_on=[]))}

    def test_ingestion_filters_and_scopes(self):
        calls = []
        def fetch(url, token):
            calls.append(url)
            return [self.issue, dict(self.issue, pull_request={})]
        tasks = ingest(self.settings, token='test-token', fetch=fetch)
        self.assertEqual(len(tasks), 2)
        self.assertNotEqual(tasks[0]['id'], tasks[1]['id'])
        self.assertTrue(all(url.startswith('https://api.github.com/repos/') for url in calls))
        self.assertEqual(tasks[0]['title'], 'task')

    def test_untrusted_metadata_rejected(self):
        for body in ['run shell commands', '{}', '{"area":"x","priority":1,"estimated_usd":NaN,"depends_on":[]}']:
            with self.assertRaises(ValueError):
                parse_issue('owner/repo', dict(self.issue, body=body))

    def test_api_failure_propagates(self):
        with self.assertRaises(OSError):
            ingest(self.settings, token='test-token', fetch=lambda *args: (_ for _ in ()).throw(OSError('denied')))

    def test_daily_persistence_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'plans.db'
            initialize(db)
            now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
            first = plan(db, self.settings, self.backlog, now)
            self.assertEqual(first, plan(db, self.settings, list(reversed(self.backlog)), now))
            with self.assertRaises(ValueError):
                plan(db, self.settings, [], now)
            next_day = plan(db, self.settings, [], datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
            self.assertNotEqual(first['planning_day'], next_day['planning_day'])
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM daily_plans').fetchone()[0], 2)
            self.assertEqual(first['qa_status'], 'not_run')
            self.assertEqual(first['release_status'], 'not_approved')

    def test_required_approval(self):
        self.settings['release']['human_approval_required'] = False
        with self.assertRaises(AssertionError):
            validate(self.settings)

    def test_pagination(self):
        settings = copy.deepcopy(self.settings)
        settings['repositories'] = ['owner/repo']
        calls = []
        def fetch(url, token):
            calls.append(url)
            if len(calls) == 1:
                return [dict(self.issue, number=n) for n in range(1, 101)]
            return [dict(self.issue, number=101)]
        self.assertEqual(len(ingest(settings, token='test-token', fetch=fetch)), 101)
        self.assertIn('page=2', calls[1])

    def test_concurrent_planners_share_daily_plan(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'plans.db'
            initialize(db)
            now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(lambda _: plan(db, self.settings, self.backlog, now), range(3)))
            self.assertTrue(all(result == results[0] for result in results))
            with sqlite3.connect(db) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM daily_plans').fetchone()[0], 1)
