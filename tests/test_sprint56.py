"""No network, inference, operational ledger or real OAuth credentials."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from subscription_harness import FakeOAuth, FakeAppServer, SubscriptionHarness, live_subscription_bridge
from readiness import audit, GATES


class SubscriptionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve(strict=True)/'offline.db'
        self.now = 1000
        self.oauth, self.server = FakeOAuth(), FakeAppServer()
        self.h = SubscriptionHarness(self.path, self.oauth, self.server, lambda:self.now, initialize=True)
        self.request = dict(execution='a'*32, task='fixture/server#3', repository='fixture/server',
                            source='b'*40, model='fixture-codex', operation='investigate')

    def approve(self):
        self.h.approve('a'*32, 'fixture-vsock:1', 'fixture/server#3', 'fixture/server', 'b'*40, 3400)

    def run_turn(self):
        return self.h.request('fixture-vsock:1', self.request)

    def test_valid_authorization_single_bounded_turn_and_no_token_in_audit(self):
        self.approve(); self.assertEqual(self.run_turn()['state'], 'complete')
        with self.assertRaises(ValueError): self.run_turn()
        self.assertEqual(self.server.calls, 1)
        self.assertNotIn(self.oauth.credential.encode(), self.path.read_bytes())
        with self.h.tx() as db:
            events=[r['event'] for r in db.execute('SELECT * FROM audit')]
        self.assertEqual(events, ['approved','turn_reserved','turn_stopped'])

    def test_missing_consent_eligibility_expiry_state_identity_and_scopes(self):
        for key,value in [('consent',False),('eligible',False),('expires',1000),
                          ('state','attacker'),('account','other'),('scopes',{'arbitrary'}),
                          ('credential','not-a-public-fixture'),('revoked',True)]:
            old=getattr(self.oauth,key);setattr(self.oauth,key,value)
            with self.subTest(key=key),self.assertRaises(ValueError):self.approve()
            setattr(self.oauth,key,old)
        self.assertEqual(self.server.calls,0)

    def test_rotation_rechecks_account_and_revocation(self):
        self.approve()
        with self.assertRaises(ValueError): self.oauth.rotate(self.now, account='other')
        self.oauth.rotate(self.now)
        self.assertEqual(self.run_turn()['state'],'complete')
        with self.h.tx() as db:self.assertEqual(db.execute('SELECT generation FROM execution').fetchone()[0],2)

    def test_revocation_expiry_and_worker_cancellation_before_request(self):
        self.approve()
        self.oauth.revoked=True
        with self.assertRaises(ValueError):self.run_turn()
        self.oauth.revoked=False;self.now=3400
        with self.assertRaises(ValueError):self.run_turn()
        self.now=1000;self.h.stop('a'*32)
        restarted=SubscriptionHarness(self.path,self.oauth,self.server,lambda:self.now)
        with self.assertRaises(ValueError):restarted.request('fixture-vsock:1',self.request)
        self.assertEqual(self.server.calls,0)

    def test_incompatible_model_api_fallback_refill_purchase_tokens_and_tools(self):
        self.approve()
        for change in [dict(model='gpt-api'),dict(operation='responses'),dict(operation='buy_credits'),
                       dict(operation='consume_reset_credit'),dict(paid_refill=True),dict(api_fallback=True),
                       dict(accessToken=self.oauth.credential),dict(tools=['shell']),dict(principal='fixture-vsock:1')]:
            req=dict(self.request);req.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.h.request('fixture-vsock:1',req)
        self.assertEqual(self.server.calls,0)

    def test_worker_identity_repository_source_task_and_one_agent(self):
        self.approve()
        with self.assertRaises(ValueError):self.h.request('attacker',self.request)
        for key in ['repository','source','task','execution']:
            req=dict(self.request);req[key]='other'
            with self.assertRaises(ValueError):self.h.request('fixture-vsock:1',req)
        with self.assertRaises(ValueError):self.h.approve('c'*32,'fixture-vsock:1','fixture/server#3','fixture/server','b'*40,3400)

    def test_quota_exhaustion_latches_and_never_falls_back(self):
        self.approve();self.server.outcome='quota';result=self.run_turn()
        self.assertEqual(result['state'],'exhausted')
        self.assertFalse(result['api_fallback']);self.assertFalse(result['paid_refill']);self.assertFalse(result['credit_purchase'])
        with self.assertRaises(ValueError):self.run_turn()

    def test_ambiguous_error_malicious_tools_and_exposure_are_stops(self):
        for outcome in ['unknown','tool','exposure']:
            with self.subTest(outcome=outcome):
                path=Path(self.tmp.name).resolve(strict=True)/(outcome+'.db');server=FakeAppServer(outcome)
                h=SubscriptionHarness(path,self.oauth,server,lambda:self.now,initialize=True)
                h.approve('a'*32,'fixture-vsock:1','fixture/server#3','fixture/server','b'*40,3400)
                result=h.request('fixture-vsock:1',self.request)
                self.assertEqual(result['state'],'uncertain')
                self.assertNotIn(self.oauth.credential,json.dumps(result));self.assertNotIn(self.oauth.credential.encode(),path.read_bytes())
                with self.assertRaises(ValueError):h.request('fixture-vsock:1',self.request)

    def test_controller_and_broker_restart_keep_pending_hold_even_after_deadline(self):
        self.approve();self.server.outcome='crash'
        with self.assertRaises(RuntimeError):self.run_turn()
        self.now=4000
        restarted=SubscriptionHarness(self.path,self.oauth,FakeAppServer(),lambda:self.now)
        with self.assertRaises(ValueError):restarted.request('fixture-vsock:1',self.request)
        self.oauth.expires=6400
        with self.assertRaises(ValueError):restarted.approve('c'*32,'fixture-vsock:1','fixture/server#3','fixture/server','b'*40,6400)
        restarted.stop('a'*32, 'kill_switch')
        with self.assertRaises(ValueError):restarted.approve('c'*32,'fixture-vsock:1','fixture/server#3','fixture/server','b'*40,6400)
        with self.assertRaises(FileExistsError):SubscriptionHarness(self.path,self.oauth,self.server,lambda:self.now,initialize=True)

    def test_inflight_cancel_expiry_and_revocation_cannot_report_success(self):
        for action in ['cancel','expiry','revoke']:
            path=Path(self.tmp.name).resolve(strict=True)/(action+'.db');server=FakeAppServer()
            oauth=FakeOAuth();h=SubscriptionHarness(path,oauth,server,lambda:self.now,initialize=True)
            h.approve('a'*32,'fixture-vsock:1','fixture/server#3','fixture/server','b'*40,3400)
            original=server.turn
            def during():
                if action=='cancel':h.stop('a'*32)
                elif action=='expiry':self.now=3400
                else:oauth.revoked=True
                return original()
            server.turn=during
            self.assertEqual(h.request('fixture-vsock:1',self.request)['state'],'uncertain')
            self.now=1000

    def test_real_provider_and_live_bridge_are_impossible(self):
        with self.assertRaises(ValueError):SubscriptionHarness(self.path,object(),self.server,lambda:1000)
        with self.assertRaises(RuntimeError):live_subscription_bridge()

    def test_new_readiness_requires_external_observations_and_explicit_task(self):
        sub={c['id']:c for c in audit()['checks']}
        for gate in ['subscription_eligibility','subscription_isolation','subscription_execution_binding','task_authorization','subscription_transport']:
            self.assertTrue(sub[gate]['mandatory']);self.assertEqual(sub[gate]['status'],'blocked')
        self.assertIn('branch_protection',GATES['github_apps'][1])
        for gate in ['subscription_eligibility','subscription_isolation','subscription_execution_binding']:
            api={c['id']:c for c in audit(mode='api_billing')['checks']}
            self.assertEqual(api[gate]['status'],'not_applicable')
        with patch('readiness.require_live',return_value=None):self.assertFalse(audit()['ready'])


class ProtocolAndAssetTests(unittest.TestCase):
    def test_pinned_protocol_fixtures_and_generated_required_fields(self):
        root=Path(__file__).parent/'fixtures/app-server-0.163.0'
        manifest=json.loads((root/'manifest.json').read_text())
        for name,expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected)
        messages=json.loads((root/'messages.json').read_text())
        for case in messages:
            schema=json.loads((root/case['schema']).read_text())
            self.assertTrue(set(schema.get('required',[])) <= set(case['message']))
            if case['schema']=='TurnCompletedNotification.json':
                turn=case['message']['turn']
                self.assertTrue(set(schema['definitions']['Turn']['required']) <= set(turn))
                if turn['error'] is not None:
                    self.assertTrue(set(schema['definitions']['TurnError']['required']) <= set(turn['error']))
        for outcome in ['complete','quota','unknown']:
            self.assertIn(dict(schema='TurnCompletedNotification.json',message=FakeAppServer(outcome).turn()['params']),messages)
        login=json.loads((root/'LoginAccountParams.json').read_text())
        external=[v for v in login['oneOf'] if v['properties']['type']['enum']==['chatgptAuthTokens']][0]
        self.assertIn('FOR OPENAI INTERNAL USE ONLY',external['description'])

    def test_asset_plan_rejects_unlocked_dependencies_and_records_blockers(self):
        from server_qa_assets import plan
        lock=dict(lockfileVersion=3,packages={'':{},'node_modules/bcrypt':dict(
            version='5.1.1',resolved='https://registry.npmjs.org/bcrypt/-/bcrypt-5.1.1.tgz',integrity='sha512-'+__import__('base64').b64encode(bytes(64)).decode())})
        result=plan(json.dumps(lock).encode())
        self.assertFalse(result['ready']);self.assertFalse(result['production_database'])
        self.assertIsNone(result['mongodb']['archive_sha256'])
        for change in [dict(integrity=None),dict(integrity='sha512-bad'),dict(resolved='https://untrusted.invalid/package'),dict(version='6.0.0')]:
            changed=copy.deepcopy(lock);changed['packages']['node_modules/bcrypt'].update(change)
            with self.assertRaises(ValueError):plan(json.dumps(changed).encode())

    def test_asset_root_symlink_is_rejected(self):
        from server_qa import verify_assets
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(strict=True);(root/'link').symlink_to(root,target_is_directory=True)
            with self.assertRaises(ValueError):verify_assets(root/'link',{})


if __name__=='__main__':unittest.main()
