"""Offline safety tests. Synthetic principals/receipts never prove Mac isolation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from src import activation_bundle as bundle, codex_worker, integration_control as control
from src import orchestration_evidence as e, migration_inventory
from src.worker_transport import IsolatedEndpoint
from test_grant_broker import Fixture, REAL_GATE


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.addCleanup(self.f.close)
        self.b = self.f.broker
        self.c = self.f.claim()
        self.source = self.b.prepare_worker_synthetic(self.c)

    def qa(self):
        req = self.b.start_synthetic(self.c)
        self.b.capture_synthetic(self.c, self.f.output(req))
        return self.b.prepare_qa_synthetic(self.c, self.source)

    def test_broker_exact_source_instructions_no_privileged_paths(self):
        req, files = bundle.unpack_worker(self.source)
        row = self.b.inspect()['tasks'][self.c['execution']]
        self.assertEqual(req['instructions'], row['authorization']['spec']['prompt'])
        self.assertEqual(bundle.manifest(files), row['authorization']['source_manifest'])
        self.assertNotIn(str(self.f.controller.path).encode(), self.source)
        self.assertNotIn(b'policy_path', self.source)
        self.assertEqual(row['state'], 'claimed')  # Preparation cannot dispatch.

    def test_qa_reconstructs_captured_bytes_and_fixed_checks_without_execution(self):
        raw = self.qa()
        with patch('subprocess.Popen', side_effect=AssertionError('Controller executed candidate')):
            req, candidate, checks = bundle.unpack_qa(raw, self.f.f.now)
        self.assertEqual(req['token'], self.c['token'])
        self.assertEqual(checks, self.b.inspect()['tasks'][self.c['execution']]['authorization']['checks'])
        self.assertEqual(bundle.manifest(candidate), e.decode(raw)['candidate_manifest'])
        self.assertEqual(self.b.inspect()['tasks'][self.c['execution']]['state'], 'received')

    def test_source_package_tampering_unknown_fields_modes_and_paths(self):
        doc = e.decode(self.source)
        name = next(iter(doc['source']))
        for key, value in [('source', {name:[0o120777,'00']}),
                           ('source', {'../escape':[0o644,'00']}),
                           ('source', {'.env.secret':[0o644,'00']}),
                           ('source', {name:[0o666,'00']}),
                           ('source', {name:[0o644,'01']}),
                           ('credential', 'must-not-forward')]:
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(doc); bad[key] = value
                with self.assertRaises(ValueError): bundle.unpack_worker(bundle.pack(bad))
        bad = copy.deepcopy(doc); req = e.decode(bad['request']); req['credential']='secret'
        bad['request']=e.canonical(req)
        with self.assertRaises(ValueError): bundle.unpack_worker(bundle.pack(bad))

    def test_bundle_size_ceiling(self):
        with self.assertRaises(ValueError): bundle.pack({'oversize':'x'*bundle.MAXIMUM})
        with self.assertRaises(ValueError): bundle.unpack_worker(b'x'*(bundle.MAXIMUM+1))
        with self.assertRaises(ValueError): bundle.decode_files({'x':[0o644,'AA']})

    def test_changed_source_commit_and_policy_block_preparation(self):
        a = self.b.inspect()['tasks'][self.c['execution']]['authorization']
        source = self.f.controller.config['repositories'][a['spec']['repo']]['source']
        from src.local_runner import git
        git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@local',
            'commit', '--allow-empty', '-qm', 'changed head')
        with self.assertRaises(ValueError): self.b.prepare_worker_synthetic(self.c)

    def test_expiry_stop_and_replayed_start(self):
        stop = Path(self.f.config['stop_files'][0]); stop.touch()
        with self.assertRaises(ValueError): self.b.prepare_worker_synthetic(self.c)
        stop.unlink()
        self.b.start_synthetic(self.c)
        with self.assertRaises(ValueError): self.b.prepare_worker_synthetic(self.c)
        with self.assertRaises(ValueError): self.b.start_synthetic(self.c)
        self.assertEqual(self.b.inspect()['active'],1)

    def test_wrong_retained_request_and_changed_checks_rejected(self):
        raw = self.qa()
        bad=e.decode(raw); bad['checks'][0]['argv']=['sh','-c','true']
        with self.assertRaises(ValueError): bundle.unpack_qa(bundle.pack(bad),self.f.f.now)
        changed=e.decode(self.source); req=e.decode(changed['request']);req['instructions']='forged'
        changed['request']=e.canonical(req)
        with self.assertRaises(ValueError): self.b.prepare_qa_synthetic(self.c,bundle.pack(changed))

    def test_candidate_and_receipt_tampering_replay_expiry(self):
        raw = self.qa(); req,candidate,checks=bundle.unpack_qa(raw,self.f.f.now)
        receipt=dict(schema=bundle.PROTOCOL,kind='qa-result',request=hashlib.sha256(raw).hexdigest(),
            token=req['token'],generation=req['generation'],candidate_manifest=bundle.manifest(candidate),
            checks=[dict(name=c['name'],argv=c['argv'],code=0,reason=None) for c in checks],
            candidate_unchanged=True,publication='separate-authorization-required')
        self.assertEqual(bundle.verify_qa_response(raw,bundle.pack(receipt),self.f.f.now),receipt)
        for key,value in [('token','f'*32),('generation',99),('candidate_manifest','f'*64),
                          ('request','f'*64),('checks',[]),('candidate_unchanged',False),
                          ('publication','approved'),('worker_report',True)]:
            bad=copy.deepcopy(receipt);bad[key]=value
            with self.assertRaises(ValueError): bundle.verify_qa_response(raw,bundle.pack(bad),self.f.f.now)
        with self.assertRaises(ValueError): bundle.verify_qa_response(raw,bundle.pack(receipt),req['deadline'])
        bad=e.decode(raw); bad['candidate_manifest']='f'*64
        with self.assertRaises(ValueError): bundle.unpack_qa(bundle.pack(bad),self.f.f.now)

    def test_qa_identity_separation(self):
        uid=os.getuid()
        with self.assertRaises(ValueError): bundle.IsolatedQA(IsolatedEndpoint('/unprovisioned',uid+1),uid+1)
        with self.assertRaises(ValueError): bundle.IsolatedQA(IsolatedEndpoint('/unprovisioned',uid+1),uid)
        with self.assertRaises(ValueError): bundle.IsolatedQA(object(),uid+2)

    def test_external_qa_client_checks_stop_before_contact_and_after_response(self):
        # Protocol/guard fixture only: invented UIDs do NOT prove OS isolation.
        raw=self.qa();req,candidate,checks=bundle.unpack_qa(raw,self.f.f.now)
        receipt=bundle.pack(dict(schema=bundle.PROTOCOL,kind='qa-result',
            request=hashlib.sha256(raw).hexdigest(),token=req['token'],generation=req['generation'],
            candidate_manifest=bundle.manifest(candidate),
            checks=[dict(name=c['name'],argv=c['argv'],code=0,reason=None) for c in checks],
            candidate_unchanged=True,publication='separate-authorization-required'))
        endpoint=IsolatedEndpoint('/unprovisioned',os.getuid()+1)
        client=bundle.IsolatedQA(endpoint,os.getuid()+2)
        with patch.object(endpoint,'exchange',return_value=receipt) as exchange:
            with self.assertRaises(ValueError):
                client.check(raw,lambda:self.f.f.now,lambda:(_ for _ in ()).throw(ValueError('STOP')))
            exchange.assert_not_called()
            self.assertEqual(client.check(raw,lambda:self.f.f.now,lambda:None),e.decode(receipt))
            with self.assertRaises(ValueError):
                from unittest.mock import Mock
                client.check(raw,lambda:self.f.f.now,Mock(side_effect=[None,ValueError('STOP after IPC')]))

    def test_inventory_preserves_ledgers_and_never_converts_approvals(self):
        paths=[self.b.path,self.f.f.coordinator.path,Path(self.f.controller.config['state'])/'local.sqlite']
        before=[p.read_bytes() for p in paths]
        report=migration_inventory.inventory(self.f.controller.path,self.f.f.config,self.f.config)
        self.assertFalse(report['migration_verified'])
        self.assertTrue(report['broker'][0]['termination_review_required'])
        self.assertFalse(report['local'][0]['authorization_converted'])
        self.assertEqual(before,[p.read_bytes() for p in paths])
        self.assertFalse(report['simultaneous_snapshot'])

    def test_subscription_exhaustion_is_durable_broker_hold_after_restart(self):
        req=self.b.start_synthetic(self.c)
        raw=e.canonical(dict(type='turn.failed',error=dict(codexErrorInfo='usageLimitExceeded'))).encode()
        result=self.b.capture_codex_synthetic(self.c,self.f.output(req),raw)
        self.assertEqual(result['state'],'subscription-exhausted')
        from src.grant_broker import Broker
        restarted=Broker(self.f.config,lambda:self.f.f.now)
        view=restarted.inspect()
        self.assertEqual(view['active'],1)
        self.assertEqual(view['tasks'][self.c['execution']]['state'],'held')
        with self.assertRaises(ValueError):self.f.claim()
        with self.assertRaises(ValueError):restarted.start_synthetic(self.c)

    def test_complete_usage_is_retained_with_bounded_output(self):
        req=self.b.start_synthetic(self.c)
        telemetry=b'\n'.join(e.canonical(x).encode() for x in [
            {'type':'thread.started'},{'type':'turn.started'},
            {'type':'turn.completed','usage':dict(input_tokens=5,cached_input_tokens=1,output_tokens=2)}])
        self.b.capture_codex_synthetic(self.c,self.f.output(req),telemetry)
        event=self.b.inspect()['tasks'][self.c['execution']]['events'][-1]
        self.assertEqual(event['document']['usage']['input_tokens'],5)

    def test_legacy_and_coordinator_and_real_adapter_block_before_side_effects(self):
        from src.local_runner import LocalCLI
        from src.catalog_publication import reconstruct
        with patch.object(control, 'block_live_dispatch', side_effect=REAL_GATE), \
             patch('subprocess.Popen', side_effect=AssertionError('Launched')):
            for call in (lambda:self.f.controller.runner.execute(self.c['execution']),
                         lambda:LocalCLI({}).run(None,None,None,None),
                         lambda:self.f.f.coordinator.dispatch_live(self.c),
                         lambda:self.b.dispatch_live(self.c),
                         lambda:codex_worker.CodexWorker().run(approved=True, isolated=True)):
                with self.assertRaisesRegex(ValueError,control.PROTOCOL): call()
        # Broker evidence cannot be laundered into historical publisher approval.
        with self.assertRaises(ValueError): reconstruct(self.f.controller.runner,self.c['execution'])
        self.assertEqual(self.f.controller.runner.inspect(self.c['execution'])['state'],'approved')

    def test_readiness_requires_all_eight_categories_and_no_receipt_override(self):
        report=control.health(self.f.controller.path,now=self.f.f.now)
        self.assertEqual(len(report['activation_prerequisites']),8)
        self.assertTrue(all(v.startswith(('unknown','blocked')) for v in report['activation_prerequisites'].values()))
        self.assertFalse(report['live_ready'])
        self.assertEqual(report['checks']['live_worker_capacity'],0)
        self.assertEqual(report['codex_authentication']['state'],'blocked')


class UsageTests(unittest.TestCase):
    def complete(self,usage):
        return b'\n'.join(e.canonical(x).encode() for x in [
            {'type':'thread.started'},{'type':'turn.started'},
            {'type':'turn.completed','usage':usage}])

    def test_success_usage_and_subscription_limits_are_not_dollars(self):
        out=codex_worker.usage_outcome(self.complete(dict(input_tokens=10,cached_input_tokens=2,output_tokens=3)))
        self.assertEqual(out['state'],'complete');self.assertFalse(out['retry'])
        self.assertNotIn('cost',out)

    def test_quota_is_first_class_and_never_retried(self):
        raw=e.canonical(dict(type='turn.failed',error=dict(codexErrorInfo='usageLimitExceeded',
                           message='do-not-log-private-text'))).encode()
        out=codex_worker.usage_outcome(raw)
        self.assertEqual(out['state'],'subscription-exhausted');self.assertFalse(out['retry'])
        self.assertNotIn('do-not-log',e.canonical(out))

    def test_unknown_auth_partial_telemetry_and_invalid_usage_are_held(self):
        for raw in (b'{}',b'bad json',b'{"type":"error","message":"quota"}',
                    self.complete(dict(input_tokens=1,cached_input_tokens=2,output_tokens=0)),
                    self.complete(dict(input_tokens=True,cached_input_tokens=0,output_tokens=0)),
                    self.complete(dict(input_tokens=1,cached_input_tokens=0))):
            out=codex_worker.usage_outcome(raw)
            self.assertEqual(out['state'],'unknown');self.assertFalse(out['retry'])

    def test_auth_boundary_no_environment_or_model_receipt_can_enable_it(self):
        with patch.dict(os.environ,{'FORT_CUSTER_LIVE':'1','CODEX_HOME':'/untrusted'}):
            self.assertEqual(codex_worker.authentication_boundary()['state'],'blocked')
            with self.assertRaises(ValueError):codex_worker.CodexWorker().run(receipt={'all_verified':True})


if __name__ == '__main__':
    unittest.main()
