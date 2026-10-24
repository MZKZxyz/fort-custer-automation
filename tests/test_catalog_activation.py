"""Legacy-to-separate-catalog admission; temporary files and fake Responses only."""
import copy
import io
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

import test_local_catalog as fixtures
from test_observation_planning import output
from src import catalog_activation as activation, orchestration_evidence as e
from src import live_observation as live, api_controller as api, local_runner
from src.api_budget import Budget
from src.source_observation import git


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CatalogTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root; self.root.chmod(0o700)
        self.policy = copy.deepcopy(self.f.config)
        self.policy.update(state=str(self.root/'catalog-state'), scratch=str(self.root/'catalog-scratch'))
        self.policy['catalog']['tasks'] = {'syntax-review': self.policy['catalog']['tasks']['constant']}
        task = self.policy['catalog']['tasks']['syntax-review']
        task['instructions'] = 'Add one explanatory comment; preserve behavior.'
        task['issue_snapshot'] = {k:v for k,v in task['issue_snapshot'].items() if k != 'body'}
        self.policy_path = self.root/'catalog.json'
        # Historical records are seeded as opaque fixtures, never admitted or executed.
        self.f.config.pop('catalog'); self.f.reload(); self.f.path.chmod(0o600)
        for state in ('pending', 'failed', 'failed', 'validated'):
            r = self.f.runner.prepare(3, 'fort-custer-server', self.f.fixture.issue)
            r['state'] = state
            with self.f.runner.tx() as db: self.f.runner.save(db, r)
        self.legacy_db = Path(self.f.config['state'])/'local.sqlite'; self.legacy_db.chmod(0o600)
        self.legacy_before = [self.f.path.read_bytes(), self.legacy_db.read_bytes()]
        self.broker_path = self.root/'observation.json'
        self.broker_config = dict(schema=live.PROTOCOL, enabled=True, mode='observation-only',
            slots=1, live_limit=1, ledger=str(self.root/'observation.sqlite'),
            scratch=str(self.root/'observation-scratch'), max_tasks=100,
            max_artifact_bytes=1048576, max_storage_bytes=16777216,
            stop_files=[str(Path(self.f.config['state'])/'STOP'), str(Path(self.policy['state'])/'STOP')])
        self.budget = Budget(self.root/'budget.sqlite'); self.budget.initialize()
        self.key = self.root/'key'; self.key.write_text('offline fixture'); self.key.chmod(0o600)
        self.api_path = self.root/'api.json'
        self.api_config = dict(schema='responses-controller-v1', connectivity_enabled=False,
            credential_file=str(self.key), budget_file=str(self.budget.path), timezone='America/Los_Angeles',
            daily_nano_usd=10_000_000_000, lifetime_nano_usd=100_000_000_000, pricing=api.DEFAULT_PRICING)
        self.save()
        for target in ('socket.socket.connect', 'socket.create_connection', 'src.api_controller._http_child',
                       'src.local_runner.Runner.execute', 'src.local_runner.LocalCLI.run',
                       'src.local_publication.Publications'):
            fence = patch(target, side_effect=AssertionError('No inference, coding or publication'))
            fence.start(); self.addCleanup(fence.stop)
        clean = patch.dict(os.environ, {}, clear=True); clean.start(); self.addCleanup(clean.stop)

    def save(self):
        for p, doc in [(self.policy_path, self.policy), (self.broker_path, self.broker_config),
                       (self.api_path, self.api_config)]:
            p.write_text(e.canonical(doc)); p.chmod(0o600)

    def preflight(self):
        return activation.preflight(self.f.path, self.policy_path, self.broker_path, self.api_path)

    def unchanged(self):
        self.assertEqual(self.legacy_before, [self.f.path.read_bytes(), self.legacy_db.read_bytes()])

    def test_deterministic_build_and_read_only_preflight(self):
        self.policy['catalog']['tasks']['syntax-review']['input_hash'] = 'UNREVIEWED'
        self.save()
        a = activation.build(self.policy_path); b = activation.build(self.policy_path)
        self.assertEqual(a, b)
        self.assertEqual(self.policy['catalog']['tasks']['syntax-review']['input_hash'], 'UNREVIEWED')
        self.policy = a; self.save()
        before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('src.local_runner.Runner', side_effect=AssertionError('Read-only preflight')):
            report = self.preflight()
        self.assertTrue(report['ready']); self.assertFalse(report['initialized'])
        self.assertEqual(report['policy_digest'], e.digest(self.policy))
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        with self.assertRaises(ValueError): activation.build(self.policy_path)
        self.unchanged()

    def test_complete_fresh_terminal_approval_to_live_review_and_fake_response(self):
        self.preflight()
        old_umask = os.umask(0o077)
        try: runner = local_runner.Runner(self.policy_path, self.policy['state'], lambda:self.f.now)
        finally: os.umask(old_umask)
        r = runner.task_prepare('syntax-review')
        broker = live.ObservationBroker(self.broker_config)
        # A pending task and every historical execution are insufficient.
        with self.assertRaises(ValueError): broker.review(self.policy_path, r['id'], 'syntax-review', 'operator')
        with sqlite3.connect(self.legacy_db) as db:
            ids = [row[0] for row in db.execute('SELECT id FROM runs')]
        for identity in ids:
            with self.assertRaises(ValueError): broker.review(self.policy_path, identity, 'syntax-review', 'operator')
        argv = ['local_runner', '--policy', str(self.policy_path), '--state', self.policy['state'], 'approve', r['id']]
        with patch.object(sys, 'argv', argv), patch('sys.stdout', new=io.StringIO()), \
             patch('src.local_runner.terminal_challenge', side_effect=OSError('No tty')):
            with self.assertRaises(OSError): local_runner.main()
        self.assertEqual(runner.inspect(r['id'])['state'], 'pending')
        challenges = []
        def confirm(c): challenges.append(c); return c
        with patch.object(sys, 'argv', argv), patch('sys.stdout', new=io.StringIO()), \
             patch('src.local_runner.terminal_challenge', side_effect=confirm):
            self.assertEqual(local_runner.main(), 0)
        self.assertEqual(challenges, ['APPROVE '+r['binding']])
        review = broker.review(self.policy_path, r['id'], 'syntax-review', 'operator')
        self.assertEqual(review['reviewed']['spec'], r['spec'])
        broker.initialize()
        with patch('src.live_observation.terminal_challenge', side_effect=confirm), patch('sys.stdout', new=io.StringIO()):
            claim = broker.authorize(self.policy_path, r['id'], 'syntax-review', 'operator')
        self.assertTrue(challenges[-1].startswith('AUTHORIZE ONE OBSERVATION '))
        with patch.object(api.ResponsesTransport, 'send', return_value=output()) as send:
            planner = live.LivePlanner(api.Controller(self.budget, api.ResponsesTransport(str(self.key))))
            decision = planner.observe(broker, claim, 'operator')
        self.assertEqual(decision.classification.disposition, 'ready_for_review')
        self.assertEqual(send.call_count, 1)
        self.assertEqual(runner.inspect(r['id'])['state'], 'approved')
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)
        self.unchanged()

    def test_stop_in_either_installation_blocks_without_initialization(self):
        for path in self.broker_config['stop_files']:
            p = Path(path); p.parent.mkdir(exist_ok=True, mode=0o700); p.touch(mode=0o600)
            with self.assertRaisesRegex(ValueError, 'STOP|empty'): self.preflight()
            p.unlink()
        self.assertFalse(Path(self.broker_config['ledger']).exists()); self.unchanged()

    def test_missing_prerequisite_and_revision_mismatch(self):
        self.policy['cli'] = str(self.root/'missing'); self.save()
        with self.assertRaisesRegex(ValueError, 'Missing pinned'): self.preflight()
        self.policy['cli'] = str(self.f.fixture.fake); self.save()
        repo = self.policy['repositories']['fort-custer-server']
        git(repo['source'], '-c', 'user.name=Fixture', '-c', 'user.email=f@local', 'commit', '--allow-empty', '-qm', 'new')
        with self.assertRaisesRegex(ValueError, 'revision mismatch'): self.preflight()
        self.assertFalse(Path(self.policy['state']).exists()); self.unchanged()

    def test_unsupported_and_oversized_task(self):
        self.broker_config['schema'] = 'grant-broker-v1-synthetic'; self.save()
        with self.assertRaises(ValueError): self.preflight()
        self.broker_config['schema'] = live.PROTOCOL
        self.policy['catalog']['tasks']['syntax-review']['instructions'] = 'x'*1100; self.save()
        with self.assertRaisesRegex(ValueError, 'ceiling'): self.preflight()
        self.unchanged()

    def test_separation_stop_coverage_and_existing_state(self):
        original = copy.deepcopy(self.broker_config)
        for key, value in [('ledger', str(self.legacy_db)), ('scratch', self.f.config['scratch']),
                           ('stop_files', [self.broker_config['stop_files'][1]])]:
            self.broker_config = dict(original, **{key:value}); self.save()
            with self.assertRaises(ValueError): self.preflight()
        self.broker_config = original; self.save()
        state = Path(self.policy['state']); state.mkdir(mode=0o700)
        (state/'local.sqlite').touch(mode=0o600)
        with self.assertRaisesRegex(ValueError, 'absent or empty'): self.preflight()
        self.unchanged()

    def test_budget_hold_blocks_and_credential_contents_are_not_read(self):
        real = Path.read_bytes
        def read(path):
            if path == self.key: raise AssertionError('Credential content read')
            return real(path)
        with patch.object(Path, 'read_bytes', read): self.preflight()
        self.budget.reserve('a'*32, 'b'*64, 1)
        with self.assertRaisesRegex(ValueError, 'Unresolved'): self.preflight()
        self.assertFalse(Path(self.policy['state']).exists()); self.unchanged()

    def test_symlink_and_binary_mismatch(self):
        self.policy['cli_sha256'] = 'a'*64; self.save()
        with self.assertRaisesRegex(ValueError, 'digest mismatch'): self.preflight()
        self.policy['cli_sha256'] = self.f.config['cli_sha256']; self.save()
        Path(self.policy['state']).symlink_to(self.f.config['state'], target_is_directory=True)
        with self.assertRaises(ValueError): self.preflight()
        self.unchanged()


if __name__ == '__main__': unittest.main()
