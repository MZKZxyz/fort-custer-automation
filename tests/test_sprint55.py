"""Operational trust-boundary regressions. Fixtures never attest live readiness."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from readiness import audit, POLICY, verify_receipt
from model_broker import ModelBroker, SyntheticProvider
from vm_runtime import VMRuntime, SyntheticVMProvider
from vm_watchdog import tick
from rehearsal import SyntheticIssuer
from trust import canonical
from planning import initialize
from secure_ledger import Ledger
from controller_service import admin, recover
from ledger_backup import snapshot, inspect, restore
from server_qa import verify_assets
from app_operations import AppOperations, verify_installation


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.now = 1792670400
        self.issuer = SyntheticIssuer()

    def broker(self, provider=None):
        b = ModelBroker(self.root/'broker.db', provider or SyntheticProvider(), lambda: self.now, initialize=True)
        b.register('a'*32, 'fixture/server#3', 'vsock:1', self.now+2400)
        return b

    def request(self, **changes):
        return canonical(dict(execution='a'*32, task='fixture/server#3', request_id='b'*32,
                              model='synthetic-codex', operation='investigate', input='maze',
                              max_output_tokens=128, **changes)).encode()

    def test_readiness_missing_forged_and_manually_passed_fail(self):
        self.assertFalse(audit()['ready'])
        (self.root/'controller.json').write_text('{"passed":true}')
        result = audit(self.root, self.root/'untrusted.json')
        self.assertTrue(all(c['status']=='blocked' for c in result['checks'] if c['id']!='policy_integrity'))
        p = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'src/readiness.py'), 'check'], capture_output=True)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)['policy'], POLICY)

    def test_readiness_even_removed_live_gate_cannot_self_activate(self):
        with patch('readiness.require_live', return_value=None):
            self.assertFalse(audit()['ready'])
            self.assertEqual(audit()['checks'][-1]['status'], 'blocked')

    def test_spending_or_security_configuration_drift_is_a_blocker(self):
        import shutil
        import readiness
        release=self.root/'release';release.mkdir()
        for folder in ('src','infra','config'):
            shutil.copytree(readiness.ROOT/folder,release/folder,ignore=shutil.ignore_patterns('__pycache__'))
        settings=release/'config/settings.json';data=json.loads(settings.read_text());data['budget']['daily_usd']=11
        settings.write_text(json.dumps(data))
        with patch('readiness.ROOT',release):
            report=audit()
        self.assertEqual(report['checks'][0]['status'],'blocked')

    def test_broker_bound_idempotence_expiry_and_revocation(self):
        b = self.broker(); response = b.request('vsock:1', self.request())
        self.assertEqual(response, b.request('vsock:1', self.request()))
        for principal, change in [('other', {}), ('vsock:1', {'task':'other#3'}), ('vsock:1', {'execution':'c'*32})]:
            request = json.loads(self.request()); request.update(change)
            with self.assertRaises(ValueError): b.request(principal, canonical(request).encode())
        b.revoke('a'*32)
        with self.assertRaises(ValueError): b.request('vsock:1', self.request())
        with self.assertRaises(ValueError): b.register('c'*32, 'fixture/server#4', 'vsock:2', self.now+2401)

    def test_broker_no_general_proxy_or_unbounded_requests(self):
        b = self.broker()
        for change in ({'url':'https://api.openai.com'}, {'model':'paid-model'}, {'operation':'responses'},
                       {'tools':[]}, {'max_output_tokens':True}, {'max_output_tokens':1025}):
            request = json.loads(self.request()); request.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): b.request('vsock:1', canonical(request).encode())
        with self.assertRaises(ValueError): b.request('vsock:1', b' '*32769)

    def test_expired_execution_and_two_executions_rejected(self):
        b = self.broker()
        with self.assertRaises(ValueError): b.register('c'*32, 'fixture/server#4', 'vsock:2', self.now+100)
        self.now += 2400
        with self.assertRaises(ValueError): b.request('vsock:1', self.request())

    def test_broker_crash_retains_durable_hold_and_blocks_retry(self):
        class Crashed(SyntheticProvider):
            def respond(self, request, cancelled): raise RuntimeError('Lost provider response')
        b = self.broker(Crashed())
        with self.assertRaises(RuntimeError): b.request('vsock:1', self.request())
        restarted = ModelBroker(self.root/'broker.db', SyntheticProvider(), lambda: self.now)
        with self.assertRaises(ValueError): restarted.request('vsock:1', self.request())
        request = json.loads(self.request()); request['request_id']='c'*32
        with self.assertRaises(ValueError): restarted.request('vsock:1', canonical(request).encode())

    def test_broker_cancellation_and_response_limits_retain_hold(self):
        class Cancels(SyntheticProvider):
            def respond(inner, request, cancelled):
                b.revoke('a'*32)
                return super().respond(request, lambda: False)
        b = self.broker(Cancels())
        with self.assertRaises(ValueError): b.request('vsock:1', self.request())
        with b.tx() as db: self.assertEqual(db.execute('SELECT state FROM requests').fetchone()[0], 'pending')

    def vm_request(self):
        return dict(execution='a'*32, task='fixture/server#3', source='b'*40, scope=['docs/maze.md'],
                    image='sha256:'+'c'*64, issued=self.now, deadline=self.now+2400)

    def run_vm(self, provider, request=None, cancel=lambda:False, exchange=lambda p,r:{'synthetic':True}):
        request = request or self.vm_request()
        return VMRuntime(provider, self.issuer.verifier, lambda:self.now).run(
            request, self.issuer.grant('vm-execution', request, self.now), exchange, cancel)

    def test_vm_signed_deadline_scope_and_cleanup(self):
        p = SyntheticVMProvider(); self.run_vm(p)
        self.assertEqual(p.calls, ['provision','inspect','terminate','absent'])
        for change in ({'deadline':self.now+2401}, {'scope':['config/policy.json']}, {'image':'vm:latest'}):
            r=self.vm_request();r.update(change)
            with self.assertRaises(ValueError): self.run_vm(SyntheticVMProvider(), r)

    def test_vm_forgery_cannot_provision(self):
        p = SyntheticVMProvider();r=self.vm_request();e=self.issuer.grant('vm-execution',r,self.now)
        e['signature']='forged'
        with self.assertRaises(ValueError): VMRuntime(p,self.issuer.verifier,lambda:self.now).run(r,e,lambda p,r:None)
        self.assertEqual(p.calls, [])

    def test_vm_cancel_crash_and_network_drift_always_clean(self):
        class Drift(SyntheticVMProvider):
            def call(self, op, data):
                r=super().call(op,data)
                if op=='inspect':r['network']='production'
                return r
        cases=[(SyntheticVMProvider(),lambda:True,lambda p,r:None),
               (SyntheticVMProvider(),lambda:False,lambda p,r:(_ for _ in ()).throw(RuntimeError('crash'))),
               (Drift(),lambda:False,lambda p,r:None)]
        for provider,cancel,exchange in cases:
            with self.assertRaises((ValueError,RuntimeError)):self.run_vm(provider,cancel=cancel,exchange=exchange)
            self.assertFalse(provider.requests)
            self.assertEqual(provider.calls[-2:],['terminate','absent'])

    def test_cleanup_uncertainty_is_never_success(self):
        class Leaks(SyntheticVMProvider):
            def call(self, op, data):
                result=super().call(op,data)
                if op=='absent':result['disks_absent']=False
                return result
        with self.assertRaises(RuntimeError):self.run_vm(Leaks())

    def test_provider_crash_after_creation_still_terminates(self):
        class Lost(SyntheticVMProvider):
            def call(self,op,data):
                r=super().call(op,data)
                if op=='provision':raise RuntimeError('lost response')
                return r
        p=Lost()
        with self.assertRaises(RuntimeError):self.run_vm(p)
        self.assertFalse(p.requests)

    def test_vm_cannot_fallback_to_live_or_docker(self):
        p=SyntheticVMProvider();p.synthetic=False
        with self.assertRaises(RuntimeError):self.run_vm(p)
        self.assertEqual(p.calls,[])

    def test_watchdog_independent_deadline_controller_failure_and_absence(self):
        class Inventory(SyntheticVMProvider):
            def call(self,op,data):
                if op=='inventory':return [dict(execution='a'*32,issued=1000,deadline=3400)]
                return super().call(op,data)
        self.assertEqual(tick(Inventory(),3399,True),[])
        self.assertEqual(tick(Inventory(),3400,True),['a'*32])
        self.assertEqual(tick(Inventory(),1001,False),['a'*32])
        self.assertEqual(tick(Inventory(),900,True),['a'*32])
        class Broken(Inventory):
            def call(self,op,data):raise RuntimeError('watchdog cannot reach provider')
        with self.assertRaises(RuntimeError):tick(Broken(),3400,False)

    def ledger(self):
        path=self.root/'ledger.db';initialize(path)
        ledger=Ledger(path,self.issuer.verifier,lambda:self.now,{'fixture/server'},synthetic=True)
        spec=dict(task='fixture/server#3',repo='fixture/server',branch='task/maze-3',source='a'*40,area='maze',allowed=['docs/maze.md'])
        run=ledger.dispatch(spec,self.issuer.grant('dispatch',ledger.request(spec),self.now))
        return ledger,run

    def test_admin_peer_identity_kill_audit_and_restart_hold_preservation(self):
        ledger,run=self.ledger()
        with self.assertRaises(ValueError):admin(ledger.path,{'operation':'kill'},999,{0},self.now)
        recover(ledger.path,self.now);recover(ledger.path,self.now)
        result=admin(ledger.path,{'operation':'kill'},0,{0},self.now)
        self.assertTrue(result['stopped'])
        with ledger.tx() as db:
            row=ledger.get(db,run);self.assertIsNone(row['final']);self.assertEqual(row['reserved'],300)
            self.assertEqual(db.execute("SELECT count(*) FROM s53_events WHERE event='startup_fenced'").fetchone()[0],1)
        with self.assertRaises(ValueError):ledger.claim(run,'worker')

    def test_backup_snapshot_preserves_full_ledger_and_never_overwrites(self):
        ledger,_=self.ledger();target=self.root/'snapshot.db'
        evidence=snapshot(ledger.path,target)
        self.assertEqual(evidence,inspect(ledger.path))
        with self.assertRaises(ValueError):snapshot(ledger.path,target)
        with self.assertRaises(FileExistsError):restore(self.root/'x.age',self.root/'identity',target)
        self.assertEqual(evidence,inspect(target))

    def test_missing_and_tampered_qa_assets_fail(self):
        from server_qa import SOURCE,TREE
        with self.assertRaises(ValueError):verify_assets(self.root,dict(source=SOURCE,tree=TREE,files={}))
        (self.root/'unexpected').write_text('tamper')
        with self.assertRaises(ValueError):verify_assets(self.root,dict(source=SOURCE,tree=TREE,files={'unexpected':'a'*64}))

    def test_app_identity_selection_and_role_separation(self):
        data=dict(id=1,app_id=2,account=dict(login='MZKZxyz'),repository_selection='selected',suspended_at=None)
        verify_installation(data,2,1,'MZKZxyz')
        for change in ({'app_id':3},{'repository_selection':'all'},{'suspended_at':'now'}):
            d=copy.deepcopy(data);d.update(change)
            with self.assertRaises(ValueError):verify_installation(d,2,1,'MZKZxyz')
        with self.assertRaises(ValueError):AppOperations(None,None,None,dict(reader={'app_id':1},publisher={'app_id':1}))

    def test_full_offline_activation_contract(self):
        from activation_rehearsal import rehearse
        result=rehearse()
        self.assertFalse(result['readiness']['ready'])
        self.assertTrue(result['workflow']['draft'])
        self.assertFalse(result['workflow']['worker_evidence']['real_vm'])
        self.assertIn('revoked',result['workflow']['worker_evidence']['broker_audit'])
        self.assertTrue(result['cancellation']['terminated'])
        self.assertEqual(result['cancellation']['state'],'failed')

    def test_exported_rehearsal_preserves_audit_and_refuses_overwrite(self):
        from activation_rehearsal import rehearse
        path=self.root/'evidence';rehearse(path)
        self.assertTrue((path/'synthetic-candidate.git').is_dir())
        with sqlite3.connect(path/'synthetic-ledger.db') as db:
            self.assertEqual(db.execute("SELECT count(*) FROM s53_events WHERE event='billing_reconciled'").fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0],1)
        with self.assertRaises(FileExistsError):rehearse(path)

    def test_app_tokens_scoped_audited_not_replayed_and_revoked(self):
        from datetime import datetime,timezone
        ledger,run=self.ledger();repo='MZKZxyz/fort-custer-server'
        identities=dict(reader=dict(app_id=1,installation_id=11),publisher=dict(app_id=2,installation_id=22))
        now=self.now
        class Transport:
            synthetic=True
            revoked=[]
            def installation(self,ident):
                return dict(id=ident,app_id=1 if ident==11 else 2,account=dict(login='MZKZxyz'),repository_selection='selected',suspended_at=None)
            def repositories(self,ident):return [repo]
            def mint(self,ident,request):
                return dict(token='public-synthetic-test-token',expires_at=datetime.fromtimestamp(now+3500,timezone.utc).isoformat(),
                            permissions=request['permissions'],repositories=[dict(full_name=repo)])
            def revoke(self,token):self.revoked.append(token)
        transport=Transport();ops=AppOperations(transport,self.issuer.verifier,lambda:self.now,identities,ledger)
        binding=dict(role='reader',repository=repo,execution=run)
        grant=self.issuer.grant('app-token',binding,now)
        ops.mint('reader',repo,run,grant)
        with self.assertRaises(ValueError):ops.mint('reader',repo,run,grant)
        self.assertEqual(ops.get('reader',run),'public-synthetic-test-token')
        self.now+=3500
        with self.assertRaises(ValueError):ops.get('reader',run)
        ops.revoke('reader',run)
        with self.assertRaises(KeyError):ops.get('reader',run)
        self.assertEqual(len(transport.revoked),1)

    def test_public_vector_signed_receipt_artifacts_and_tampering(self):
        # RFC 8032 test vector #1 is public test material, never an operational key.
        import base64,hashlib
        seed=bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
        private=self.root/'public-test-vector.der'
        private.write_bytes(bytes.fromhex('302e020100300506032b657004220420')+seed)
        key=self.root/'public.pem'
        subprocess.run(['openssl','pkey','-inform','DER','-in',str(private),'-pubout','-out',str(key)],check=True,capture_output=True)
        context=audit()['context'];log=self.root/'log';log.write_text('independent probe output fixture')
        from readiness import GATES
        payload=dict(gate='controller',context=context,policy=copy.deepcopy(POLICY),synthetic=False,issued=self.now,expires=self.now+300,
                     observations={name:dict(artifact='log',sha256=hashlib.sha256(log.read_bytes()).hexdigest()) for name in GATES['controller'][1]})
        message=self.root/'message';message.write_text(canonical(payload));signature=self.root/'signature'
        subprocess.run(['openssl','pkeyutl','-sign','-keyform','DER','-inkey',str(private),'-rawin','-in',str(message),'-out',str(signature)],check=True,capture_output=True)
        receipt=dict(payload=payload,signature=base64.b64encode(signature.read_bytes()).decode())
        trust=dict(controller=dict(public_key=str(key),key_sha256=hashlib.sha256(key.read_bytes()).hexdigest()))
        with patch('readiness.protected_file',side_effect=Path):
            verify_receipt('controller',receipt,trust,self.root,self.now,context)
            log.write_text('tampered')
            with self.assertRaises(ValueError):verify_receipt('controller',receipt,trust,self.root,self.now,context)
            receipt['payload']['policy']['task_cents']=999
            with self.assertRaises((ValueError,subprocess.SubprocessError)):
                verify_receipt('controller',receipt,trust,self.root,self.now,context)

    @unittest.skipUnless(__import__('shutil').which('age'), 'age not installed; encrypted restore not verified')
    def test_real_age_encrypted_restore_with_public_upstream_fixture(self):
        # Public age v1.2.1 testdata/example_keys.txt (blob c243a775a67f15848275adfae58b8db416909897).
        # This is published test material, never a newly generated operational identity.
        from ledger_backup import backup
        identity=self.root/'public-fixture.txt'
        identity.write_text('AGE-SECRET-KEY-184JMZMVQH3E6U0PSL869004Y3U2NYV7R30EU99CSEDNPH02YUVFSZW44VU\n')
        recipient='age1cy0su9fwf3gf9mw868g5yut09p6nytfmmnktexz2ya5uqg9vl9sss4euqm'
        ledger,_=self.ledger();encrypted=self.root/'backup.age';restored=self.root/'restored.db'
        before=inspect(ledger.path)
        evidence=backup(ledger.path,encrypted,recipient)
        self.assertEqual(evidence['logical_sha256'],before['logical_sha256'])
        self.assertEqual(restore(encrypted,identity,restored),before)
        wrong=self.root/'empty-identity';wrong.write_text('# Deliberately no public fixture identity\n')
        with self.assertRaises(subprocess.SubprocessError):restore(encrypted,wrong,self.root/'wrong.db')
        self.assertFalse((self.root/'wrong.db').exists())
        tampered=bytearray(encrypted.read_bytes());tampered[-1]^=1;encrypted.write_bytes(tampered)
        with self.assertRaises(subprocess.SubprocessError):restore(encrypted,identity,self.root/'tampered.db')
        self.assertFalse((self.root/'tampered.db').exists())
        self.assertEqual(inspect(ledger.path),before)


if __name__=='__main__':unittest.main()
