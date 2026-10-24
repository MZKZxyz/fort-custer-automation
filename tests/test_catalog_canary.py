"""Second-canary regression using private temporary stores and mocked terminal only."""
import copy
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import test_catalog_activation as fixtures
from src import catalog_canary as canary, orchestration_evidence as e
from src import local_runner, live_observation as live


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ActivationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.policy['catalog']['tasks'] = {
            canary.ORIGINAL: self.f.policy['catalog']['tasks']['syntax-review']}
        self.f.save()
        self.old = local_runner.Runner(self.f.policy_path, self.f.policy['state'], lambda:self.f.f.now)
        # Runner's SQLite creation inherits the caller's umask (0644 under 022).
        # Observation review requires this temporary execution ledger to be private.
        catalog_ledger = Path(self.f.policy['state'])/'local.sqlite'
        catalog_ledger.chmod(0o600)
        for path in (catalog_ledger, self.f.policy_path, self.f.broker_path, self.f.api_path):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, str(path))
        self.first = self.old.task_prepare(canary.ORIGINAL)
        self.old.approve(self.first['id'], 'APPROVE '+self.first['binding'])
        self.broker = live.ObservationBroker(self.f.broker_config, lambda:self.f.f.now)
        self.broker.initialize()  # Synthetic temporary fixture only.
        self.claim = self.authorize(self.f.policy_path, self.first['id'], canary.ORIGINAL)
        self.version = self.f.root/'policy-v3.json'
        self.version.write_text(e.canonical(canary.candidate(self.f.policy_path)))
        self.version.chmod(0o600)
        self.assertEqual(self.version.stat().st_mode & 0o777, 0o600)
        fence = patch('src.api_controller.ResponsesTransport.send',
                      side_effect=AssertionError('No API requests'))
        fence.start(); self.addCleanup(fence.stop)

    def authorize(self, policy, execution, task):
        with patch('src.live_observation.terminal_challenge', side_effect=lambda c:c), \
             patch('sys.stdout', new=io.StringIO()):
            return self.broker.authorize(policy, execution, task, 'operator')

    def preflight(self):
        return canary.preflight(self.f.policy_path, self.version, self.f.broker_path, self.f.api_path)

    def test_preflight_preserves_every_file_and_never_constructs_runner(self):
        before = {str(p):p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()}
        with patch('src.local_runner.Runner', side_effect=AssertionError('No initialization')):
            self.assertTrue(self.preflight()['ready_for_manual_preparation'])
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()})
        self.f.unchanged()

    def test_new_policy_fresh_binding_and_existing_broker_history(self):
        old_row = copy.deepcopy(self.broker.inspect()['tasks'])
        runner = local_runner.Runner(self.version, self.f.policy['state'], lambda:self.f.f.now)
        with self.assertRaisesRegex(ValueError, 'already prepared'): runner.task_prepare(canary.ORIGINAL)
        second = runner.task_prepare(canary.SECOND)
        self.assertEqual(second['spec']['task'], self.first['spec']['task'])
        self.assertNotEqual(second['binding'], self.first['binding'])
        with self.assertRaises(ValueError):
            self.broker.review(self.version, second['id'], canary.SECOND, 'operator')
        runner.approve(second['id'], 'APPROVE '+second['binding'])
        claim = self.authorize(self.version, second['id'], canary.SECOND)
        self.broker.guard(claim, 'operator', {'authorized'})
        self.broker.guard(self.claim, 'operator', {'authorized'})
        self.assertEqual(old_row[self.first['id']], self.broker.inspect()['tasks'][self.first['id']])
        with self.assertRaisesRegex(ValueError, 'already prepared'): runner.task_prepare(canary.SECOND)
        with self.assertRaisesRegex(ValueError, 'consumed'): self.preflight()
        with self.assertRaises(ValueError):
            self.broker.review(self.version, self.first['id'], canary.SECOND, 'operator')

    def test_configuration_binding_and_policy_edits_fail_closed(self):
        changed = dict(self.f.broker_config, live_limit=2)
        with self.assertRaises(ValueError): live.ObservationBroker(changed).inspect()
        doc = e.decode(self.version.read_bytes())
        doc['catalog']['tasks'][canary.SECOND]['instructions'] += ' changed'
        self.version.write_text(e.canonical(doc))
        with self.assertRaisesRegex(ValueError, 'only add'): self.preflight()
        with self.assertRaises(ValueError): canary.candidate(self.version)

    def test_stop_and_unresolved_budget_block(self):
        stop = Path(self.f.policy['state'])/'STOP'; stop.touch(mode=0o600)
        with self.assertRaisesRegex(ValueError, 'STOP'): self.preflight()
        stop.unlink()  # Temporary fixture cleanup, never an operator instruction.
        self.f.budget.reserve('a'*32, 'b'*64, 1)
        with self.assertRaisesRegex(ValueError, 'Unresolved'): self.preflight()


if __name__ == '__main__': unittest.main()
