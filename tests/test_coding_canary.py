"""Synthetic integration only. Real Sol capture is not available in this checkout."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_grant_broker import Fixture
from src import coding_canary as c, coding_contract as contract
from src.local_runner import git, source_files, manifest


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture(); self.addCleanup(self.fixture.close)
        f = self.fixture.controller
        repo = next(iter(f.config['repositories'].values()))
        source = Path(repo['source'])
        (source/contract.FILE).write_text('export function compile(rows) {\n  return rows;\n}\n')
        (source/'test/analyzer.test.js').write_text(
            "import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
            "import {compile} from '../tools/maze-analyzer/solver.js';\n"
            "test('compile preserves input identity', () => {const rows=['SE'];"
            "assert.equal(compile(rows), rows);});\n")
        if self._testMethodName == 'test_failed_tests_retain_hold':
            (source/'test/analyzer.test.js').write_text("throw Error('synthetic regression failure');\n")
        git(source, 'add', '.')
        git(source, '-c', 'user.name=Fixture', '-c', 'user.email=f@local', 'commit', '-qm', 'compile fixture')
        repo['sha'] = git(source, 'rev-parse', 'HEAD').decode().strip()
        entry = f.config['catalog']['tasks'].pop('task-0')
        entry.update(source=repo['sha'], input_hash=manifest(source_files(source, repo['sha'])),
                     instructions=c.INSTRUCTIONS, checks=[
                         dict(name='syntax', argv=['node', '--check', contract.FILE], timeout_seconds=3),
                         dict(name='analyzer', argv=['node', '--test', 'test/analyzer.test.js'], timeout_seconds=3)])
        f.config['catalog']['tasks']['comment'] = entry
        f.reload()
        self.approval = f.approved('comment')
        self.claim = self.fixture.broker.claim_synthetic(f.path, self.approval['id'], 'comment', 'offline')
        self.raw = json.dumps(dict(old='export function compile(rows) {',
            new='// Compile rows without changing their identity.\n// Preserve behavior.\n'
                'export function compile(rows) {')).encode()
        for name in ('src.api_controller.ResponsesTransport.send', 'src.api_controller._http_child',
                     'src.local_publication.Publications'):
            fence = patch(name, side_effect=AssertionError('No inference, credentials or publication'))
            fence.start(); self.addCleanup(fence.stop)

    def run_replay(self):
        return c.replay_synthetic(self.fixture.broker, self.claim, self.raw)

    def test_offline_broker_to_independent_qa_and_no_replay(self):
        source = Path(next(iter(self.fixture.controller.config['repositories'].values()))['source'])
        before = (source/contract.FILE).read_bytes()
        result = self.run_replay()
        self.assertEqual([q['name'] for q in result['checks']],
                         ['diff', 'syntax', 'analyzer', 'candidate'])
        self.assertTrue(all(q['code'] == 0 for q in result['checks']))
        self.assertEqual((source/contract.FILE).read_bytes(), before)
        with self.assertRaises(ValueError): self.run_replay()

    def test_invalid_edit_consumes_claim(self):
        self.raw = b'{"old":"return rows;","new":"return [];"}'
        with self.assertRaises(ValueError): self.run_replay()
        self.assertEqual(self.fixture.broker.inspect()['tasks'][self.approval['id']]['state'], 'starting')
        with self.assertRaises(ValueError): self.run_replay()

    def test_stop_fails_closed(self):
        Path(self.fixture.config['stop_files'][0]).touch()
        with self.assertRaises(ValueError): self.run_replay()

    def test_expiry_fails_closed(self):
        self.fixture.broker.clock = lambda:self.claim['deadline']
        with self.assertRaises(ValueError): self.run_replay()

    def test_failed_tests_retain_hold(self):
        with self.assertRaises(ValueError): self.run_replay()
        self.assertEqual(self.fixture.broker.inspect()['tasks'][self.approval['id']]['state'], 'checking')
        with self.assertRaises(ValueError): self.run_replay()

    def test_source_mismatch_fails_closed(self):
        repo = next(iter(self.fixture.controller.config['repositories'].values()))
        git(repo['source'], '-c', 'user.name=Fixture', '-c', 'user.email=f@local',
            'commit', '--allow-empty', '-qm', 'advanced')
        with self.assertRaises(ValueError): self.run_replay()

    def test_live_disabled(self):
        self.assertFalse(c.readiness()['live_enabled'])


if __name__ == '__main__':
    unittest.main()
