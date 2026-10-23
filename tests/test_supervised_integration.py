"""Offline controls and one continuous promoted-task rehearsal; no sandbox claims."""
import copy
import json
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import test_concurrency_coordinator as cf
import test_task_orchestration as of
import test_catalog_publication as pf
from src import integration_control as control
from src import worker_handoff as wire
from src import orchestration_evidence as e
from src import catalog_promotion as promotion
from src import task_orchestration as orchestration
from src.local_runner import Runner, LocalCLI
from src.catalog_publication import Publications

REAL_GATE = control.block_live_dispatch


class MigrationTests(unittest.TestCase):
    def test_gate_has_no_configuration_override(self):
        with patch.dict('os.environ', {'FORT_CUSTER_LIVE': '1', 'ISOLATION_VERIFIED': 'true'}):
            with self.assertRaisesRegex(ValueError, control.PROTOCOL): REAL_GATE()

    def test_legacy_and_coordinator_cannot_dispatch_same_live_grant(self):
        f = cf.Fixture(count=1); self.addCleanup(f.close)
        claim = f.claim()
        controller = f.fixtures[0]
        ledger = Path(controller.config['state'])/'local.sqlite'
        before = ledger.read_bytes()
        # Restore the real production gate over the historical fixture's mock.
        with patch.object(control, 'block_live_dispatch', side_effect=REAL_GATE), \
             patch('src.local_runner.supervise', side_effect=AssertionError('worker launched')):
            for runner in (controller.runner, Runner(controller.path, controller.config['state'])):
                with self.assertRaisesRegex(ValueError, control.PROTOCOL): runner.execute(claim['execution'])
            with self.assertRaises(ValueError):
                f.coordinator.run_synthetic(claim, LocalCLI(controller.config))
            with self.assertRaisesRegex(ValueError, control.PROTOCOL):
                LocalCLI(controller.config).run(f.root, 'forged', lambda:False, 1)
        self.assertEqual(before, ledger.read_bytes())
        self.assertEqual(controller.runner.inspect(claim['execution'])['state'], 'approved')

    def test_separate_controller_process_cannot_bypass_gate(self):
        f = cf.Fixture(count=1); self.addCleanup(f.close)
        controller = f.fixtures[0]
        r = f.approvals[0]
        code = ("from src.local_runner import Runner;import sys;"
                "Runner(sys.argv[1],sys.argv[2]).execute(sys.argv[3])")
        result = subprocess.run([sys.executable, '-c', code, str(controller.path),
                                 controller.config['state'], r['id']], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(control.PROTOCOL.encode(), result.stderr)
        self.assertEqual(controller.runner.inspect(r['id'])['state'], 'approved')

    def test_readiness_never_green_and_does_not_mutate(self):
        f = cf.Fixture(count=1); self.addCleanup(f.close)
        controller = f.fixtures[0]
        paths = [controller.path, Path(controller.config['state'])/'local.sqlite']
        before = [p.read_bytes() for p in paths]
        view = control.health(controller.path, now=f.now)
        self.assertFalse(view['live_ready'])
        self.assertEqual(view['checks']['ledger_integrity'], 'verified')
        self.assertEqual(view['approved_tasks'], 1)
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertFalse(view['scheduling'])
        self.assertEqual(view['checks']['worker_isolation'], 'unverified')

    def test_missing_and_contradictory_evidence(self):
        view = control.health('/missing/policy')
        self.assertFalse(view['live_ready'])
        self.assertEqual(view['checks']['local_evidence'], 'unknown-or-contradictory')
        self.assertNotIn('/missing', json.dumps(view))


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.f = cf.Fixture(count=1); self.addCleanup(self.f.close)
        self.claim = self.f.claim()
        self.a = self.f.coordinator.inspect()['tasks']['task-0']['authorization']
        self.req = wire.request(self.a, self.claim)
        self.files = {self.a['allowed'][0]: (0o644, b'export const fixture = 2;\n')}
        self.out = wire.response(self.req, self.files)

    def test_narrow_immutable_request_and_transfer(self):
        self.assertIsInstance(self.req, bytes)
        self.assertNotIn(str(self.f.root), self.req.decode())
        self.assertNotIn('policy_path', self.req.decode())
        self.assertEqual(wire.ingest(self.req, self.out, self.f.now), self.files)

    def test_stale_fencing_and_forged_output(self):
        for key, value in [('token', 'f'*32), ('generation', 999), ('request', 'f'*64),
                           ('artifact_digest', 'f'*64), ('schema', 'future')]:
            doc = json.loads(self.out); doc[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                wire.ingest(self.req, e.canonical(doc).encode(), self.f.now)

    def test_missing_modified_or_interrupted_transfer(self):
        for raw in (b'', self.out[:-1], self.out.replace(b'666978', b'666979')):
            with self.assertRaises((ValueError, KeyError)):
                wire.ingest(self.req, raw, self.f.now)

    def test_protected_paths_and_extra_artifacts(self):
        for name in ('/operator/policy', '../approval.sqlite', '.env', '.git/config',
                     'a/../../publisher', 'a\\b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                wire.response(self.req, {name:(0o644,b'secret')})
        out = wire.response(self.req, {'unapproved.js':(0o644,b'wrong')})
        with self.assertRaises(ValueError): wire.ingest(self.req, out, self.f.now)

    def test_expired_output_and_changed_request(self):
        with self.assertRaises(ValueError):
            wire.ingest(self.req, self.out, self.claim['deadline'])
        for field in ('source', 'policy_digest'):
            doc = json.loads(self.req); doc[field] = 'f'*len(doc[field])
            with self.assertRaises(ValueError):
                wire.ingest(e.canonical(doc).encode(), self.out, self.f.now)

    def test_response_size(self):
        with self.assertRaises(ValueError):
            wire.response(self.req, {self.a['allowed'][0]:(0o644,b'x'*wire.MAXIMUM)})


def rehearsal():
    """Same proposal, imported task, execution, QA, publication and observer chain."""
    f = of.OrchestrationTests(); f.setUp()
    try:
        d = f.f.prepare()
        with patch.object(promotion, 'terminal'): f.f.bridge.approve(d['id'])
        f.f.bridge.apply(d['id'], f.f.export); f.f.install()
        f.policy = json.loads(f.path.read_text()); f.metadata()
        runner = Runner(f.path, f.policy['state'], lambda:f.now)
        r = runner.task_prepare('new-task')
        pub = Publications(runner)
        try: pub.prepare(r['id'])
        except ValueError: pass
        else: raise AssertionError('Publication shortcut accepted')
        r = runner.approve(r['id'], 'APPROVE '+r['binding'])
        receipts = {}
        def worker(root, prompt, cancelled, timeout):
            spec = r['spec']
            a = dict(task='new-task', execution=r['id'], repository=spec['task']['repository'],
                     source=spec['source'], source_manifest=spec['input_hash'],
                     policy_digest=e.digest(f.policy), allowed=spec['allowed'], spec=spec, expires=r['expires'])
            claim = dict(task=a['task'], execution=r['id'], authorization=e.digest(a), worker='offline-fixture',
                         token='a'*32, generation=1, started=f.now, deadline=f.now+timeout)
            request = wire.request(a, claim)
            name = spec['allowed'][0]
            files = {name:(0o644,(root/name).read_bytes()+b'\n// supervised fixture\n')}
            response = wire.response(request, files)
            for path, (mode, data) in wire.ingest(request, response, f.now).items():
                (root/path).write_bytes(data); (root/path).chmod(mode)
            receipts.update(request=e.digest(json.loads(request)), response=e.digest(json.loads(response)))
            return dict(input_tokens=3, cached_input_tokens=0, output_tokens=4)
        with patch.object(LocalCLI, 'run', side_effect=worker): r = runner.execute(r['id'])
        if r['state'] != 'validated': raise AssertionError(r)
        p = pub.prepare(r['id']); remote = pf.Remote(p['request'])
        pub.remote_inspect(p['id'], remote)
        pub.approve(p['id'], 'PUBLISH '+p['binding']); pub.execute(p['id'], remote)
        observe = lambda *args: dict(repository=remote.identity, base=remote.base_sha,
                                    head=remote.branch, prs=remote.rows)
        view, refs = orchestration.reconcile(f.c, f.now, observe)
        f.ledger.save(view, refs, f.now)
        row = next(t for t in view['tasks'] if t['id'] == 'new-task')
        if row['state'] != 'awaiting-human-merge': raise AssertionError(row)
        return dict(proposal=d['proposal']['proposal']['id'], promotion=d['id'], task='new-task',
                    execution=r['id'], source=r['spec']['source'], candidate=r['candidate_hash'],
                    qa=e.digest(r['qa']), publication=p['id'], draft_pr=remote.rows[0]['html_url'],
                    final_state=row['state'], receipts=receipts, operational_credentials=False,
                    live_workers=0, real_publication=False, independent_qa=True)
    finally: f.doCleanups()


class RehearsalTests(unittest.TestCase):
    def test_continuous_promoted_task(self):
        result = rehearsal()
        self.assertEqual(result['final_state'], 'awaiting-human-merge')
        self.assertEqual(result['live_workers'], 0)
        self.assertTrue(result['independent_qa'])


if __name__ == '__main__':
    unittest.main()
