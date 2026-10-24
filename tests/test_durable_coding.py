"""Real controller/broker/budget/QA with synthetic transport and disposable stores."""
import copy
import hashlib
import io
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_coding_live as live
import coding_fixtures as fixtures
from src import coding_contract as contract, coding_canary as canary, coding_api as profile
from src import orchestration_evidence as e, api_controller as api
from src.durable_coding import DurableBroker
from src.billing_reconciliation import reconcile
from src.local_runner import source_files, manifest


class DurableTests(unittest.TestCase):
    def setUp(self):
        setup = live.CodingTests(); setup.setUp(); self.addCleanup(setup.doCleanups)
        self.base, self.f = setup, setup.f
        second = copy.deepcopy(self.f.config['catalog']['tasks']['comment'])
        fixture = e.decode((Path(__file__).parent/'fixtures/coding/add-compile-regression.json').read_bytes())
        self.edit = dict(old=fixture.pop('old'), new=fixture.pop('synthetic_new'))
        fixture['old'] = self.edit['old']
        second.update(allowed=[fixture['path']], instructions='Add a regression test for a missing exit.',
                      edit_contract=fixture, checks=[
                          dict(name='syntax',argv=['node','--check',fixture['path']],timeout_seconds=10),
                          dict(name='analyzer',argv=['node','--test',fixture['path']],timeout_seconds=30)])
        second['limits']['usage_policy'] = contract.REVIEWED_USAGE
        self.f.config['catalog']['tasks']['regression'] = second
        self.f.reload(); self.f.path.chmod(0o600)
        self.first = self.f.approved('comment')
        self.second = self.f.approved('regression')
        self.broker = DurableBroker(setup.broker_config,lambda:self.f.now)
        with self.terminal(): self.broker.upgrade()
        self.broker.enqueue(self.f.path,self.first['id'],'comment')
        self.broker.enqueue(self.f.path,self.second['id'],'regression')
        self.budget, self.transport, self.controller = setup.budget, setup.transport, setup.controller

    @staticmethod
    def terminal():
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch('src.durable_coding.terminal_challenge', side_effect=lambda c:c))
        stack.enter_context(patch('src.billing_reconciliation.terminal_challenge', side_effect=lambda c:c))
        stack.enter_context(patch('sys.stdout',new=io.StringIO()))
        return stack

    def authorize(self, run=None, task='comment'):
        run = self.first if run is None else run
        with self.terminal(): return self.broker.authorize(self.f.path,run['id'],task,'operator')

    def execute(self,claim): return canary.run(self.broker,claim,'operator',self.controller)

    def second_success(self):
        self.transport.raw = fixtures.envelope(e.canonical(self.edit))
        claim = self.authorize(self.second,'regression')
        result = self.execute(claim)
        self.assertEqual(self.broker.inspect()['tasks'][claim['execution']]['state'],'validated')
        self.assertEqual(result['comment_regression'],'reviewed-replacement')
        self.assertTrue(all(x['code']==0 for x in result['checks']))
        return claim

    def external(self,claim,amount=1464000,outcome='billed'):
        root = self.f.root
        artifact = root/'provider-evidence.txt'
        artifact.write_text('SYNTHETIC externally retained provider support billing record')
        artifact.chmod(0o600)
        value = dict(schema='provider-billing-evidence-v1',request_id=e.digest(claim)[:32],
            execution=claim['execution'],provider_request_id='req_offline',provider_response_id='resp_offline',
            account_project='synthetic-project',source='provider-support-confirmation',
            reference='https://help.openai.com/offline-evidence',
            artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),actual_nano_usd=amount,
            currency='USD',final=True,provider_terminal=True,outcome=outcome,model=profile.MODEL,service_tier='default',
            pricing_version=profile.PRICING['version'],usage=dict(input_tokens=517,cached_input_tokens=0,
                cache_write_tokens=0,output_tokens=43,reasoning_tokens=0))
        path = root/'billing-evidence.json'; path.write_text(e.canonical(value)); path.chmod(0o600)
        return path,artifact

    def resolve(self,claim):
        path,artifact = self.external(claim)
        with self.terminal():
            reconcile(self.budget,path,artifact)
            self.broker.adjudicate(claim['execution'],path,artifact)

    def test_two_distinct_successes_same_ledgers(self):
        first = self.authorize(); self.execute(first)
        second = self.second_success()
        self.assertNotEqual(e.digest(first)[:32],e.digest(second)[:32])
        self.assertEqual(len(self.transport.calls),2)
        self.assertEqual(self.budget.status()['unresolved_requests'],0)
        self.assertEqual(len(self.broker.inspect()['tasks']),2)
        with self.broker.tx(True) as db:
            for table in ('coding_jobs','coding_events','coding_upgrade'):
                with self.assertRaises(sqlite3.IntegrityError): db.execute(f'DELETE FROM {table}')

    def test_validation_failure_external_resolution_then_success(self):
        claim = self.authorize(); self.transport.raw = fixtures.envelope(prompt_cache_retention='24h',id='resp_offline')
        with self.assertRaises(ValueError): self.execute(claim)
        self.assertEqual(self.broker.inspect()['tasks'][claim['execution']]['state'],'blocked')
        with self.assertRaises(ValueError): self.authorize(self.second,'regression')
        self.resolve(claim); self.second_success()
        self.assertEqual(len(self.transport.calls),2)
        self.assertIn('response_observed_untrusted',[v['kind'] for v in self.budget.audit()])

    def test_independent_qa_failure_allows_fresh_authorization(self):
        claim = self.authorize()
        from src import local_runner
        real = local_runner.supervise
        def check(command,*args,**kwargs):
            if '--test' in command: return dict(code=1,reason=None,stdout=b'failed',stderr=b'synthetic failure')
            return real(command,*args,**kwargs)
        with patch.object(local_runner,'supervise',side_effect=check):
            with self.assertRaises(ValueError): self.execute(claim)
        self.assertEqual(self.broker.inspect()['tasks'][claim['execution']]['state'],'failed')
        self.second_success()

    def test_restart_before_dispatch_and_duplicate_authorization(self):
        claim = self.authorize()
        self.broker = DurableBroker(self.base.broker_config,lambda:self.f.now)
        with self.assertRaises(ValueError): self.authorize()
        self.execute(claim)
        with self.assertRaises(ValueError): self.execute(claim)
        self.assertEqual(len(self.transport.calls),1)

    def test_restart_after_dispatch_never_redispatch(self):
        claim = self.authorize(); self.broker.admit(claim,'operator')
        self.broker = DurableBroker(self.base.broker_config,lambda:self.f.now)
        with self.assertRaises(ValueError): self.execute(claim)
        with self.assertRaises(ValueError): self.authorize(self.second,'regression')
        self.assertEqual(self.transport.calls,[])
        path,artifact = self.external(claim,0,'confirmed-no-charge')
        with self.terminal(): self.broker.adjudicate(claim['execution'],path,artifact)
        self.second_success()

    def test_restart_after_provider_dispatch_keeps_hold_without_redispatch(self):
        claim = self.authorize()
        def crash(): raise KeyboardInterrupt()
        self.transport.callback = crash
        with self.assertRaises(KeyboardInterrupt): self.execute(claim)
        self.broker = DurableBroker(self.base.broker_config,lambda:self.f.now)
        with self.assertRaises(ValueError): self.execute(claim)
        with self.assertRaises(ValueError): self.authorize(self.second,'regression')
        self.assertEqual(len(self.transport.calls),1)
        self.assertEqual(self.budget.status()['unresolved_nano_usd'],profile.MAXIMUM_CHARGE)

    def test_crash_during_qa_needs_local_termination_proof(self):
        claim = self.authorize(); self.broker.admit(claim,'operator')
        ident = e.digest(claim)[:32]
        self.budget.reserve(ident,'a'*64,profile.MAXIMUM_CHARGE)
        self.budget.settle(ident,1464000,{'status':'completed'})
        self.broker.progress(claim,'response_validation')
        self.broker.progress(claim,'post_settlement_authorization')
        self.broker.progress(claim,'independent_qa')
        path,artifact = self.external(claim)
        with self.terminal(), self.assertRaises((ValueError,TypeError)):
            self.broker.adjudicate(claim['execution'],path,artifact)
        termination = self.f.root/'qa-termination.txt'
        termination.write_text('SYNTHETIC administrator proof: controller and QA descendants stopped')
        termination.chmod(0o600)
        with self.terminal(): self.broker.adjudicate(claim['execution'],path,artifact,termination)
        self.second_success()

    def test_unknown_response_keeps_billing_fenced_across_new_broker(self):
        claim = self.authorize(); self.transport.raw = b'not JSON'
        with self.assertRaises(ValueError): self.execute(claim)
        self.assertEqual(self.budget.status()['unresolved_nano_usd'],5310000000)
        self.broker = DurableBroker(self.base.broker_config,lambda:self.f.now)
        with self.assertRaises(ValueError): self.authorize(self.second,'regression')
        path,artifact = self.external(claim)
        with self.terminal(), self.assertRaises(ValueError): self.broker.adjudicate(claim['execution'],path,artifact)
        self.assertEqual(len(self.transport.calls),1)

    def test_metadata_sanitized_and_linked_before_validation(self):
        claim = self.authorize()
        self.transport.raw = fixtures.envelope(id='resp_offline',prompt_cache_retention='24h',
            metadata={'secret':'DO_NOT_RETAIN'},unknown='PRIVATE_PROVIDER_BODY')
        self.transport.response_metadata = dict(request_id='req_offline')
        with self.assertRaises(ValueError): self.execute(claim)
        audit = self.budget.audit()
        observation = e.decode(next(x['evidence'] for x in audit if x['kind']=='response_observed_untrusted'))
        self.assertEqual(observation['execution'],claim['execution'])
        self.assertEqual(observation['provider_response_id'],'resp_offline')
        self.assertEqual(observation['provider_request_id'],'req_offline')
        self.assertFalse(observation['trusted'])
        self.assertNotIn('calculated_charge',observation)
        for marker in (b'DO_NOT_RETAIN',b'PRIVATE_PROVIDER_BODY'):
            self.assertNotIn(marker,self.budget.path.read_bytes())
        self.assertEqual(e.decode(audit[-1]['evidence'])['validation_rule'],'cache_policy')

    def test_incomplete_never_applies_patch_then_next_work_allowed(self):
        claim = self.authorize()
        self.transport.raw = fixtures.envelope(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
        with patch('src.coding_contract.apply',side_effect=AssertionError('No patch')):
            with self.assertRaises(ValueError): self.execute(claim)
        self.second_success()

    def test_known_provider_rejection_retains_accounting_until_review(self):
        claim = self.authorize()
        error = api.APIUnavailable('request_rejected','response_headers','response_received',400)
        def reject(body): raise error
        with patch.object(self.transport,'send',side_effect=reject):
            with self.assertRaises(ValueError): self.execute(claim)
        row = self.broker.inspect()['tasks'][claim['execution']]
        self.assertEqual(row['billing']['provider_state'],'known-provider-rejection')
        self.assertEqual(row['billing']['state'],'unresolved')
        self.resolve(claim)
        self.second_success()

    def test_stop_expired_policy_and_source_fail_closed(self):
        claim = self.authorize()
        stop = Path(self.broker.c['stop_files'][0]); stop.touch()
        with self.assertRaises(ValueError): self.execute(claim)
        stop.unlink()  # Disposable fixture only.
        self.f.now = claim['deadline']
        with self.assertRaises(ValueError): self.execute(claim)
        self.f.now = claim['started']
        policy = self.f.path.read_bytes(); self.f.config['timeout_seconds'] += 1; self.f.reload()
        with self.assertRaises(ValueError): self.execute(claim)
        self.f.path.write_bytes(policy)
        from src.local_runner import git
        git(self.f.config['repositories']['fort-custer-server']['source'],'-c','user.name=Fixture',
            '-c','user.email=f@local','commit','--allow-empty','-qm','changed')
        with self.assertRaises(ValueError): self.execute(claim)
        self.assertEqual(self.transport.calls,[])

    def test_repeated_catalog_task_fresh_execution_and_approvals(self):
        claim = self.authorize(); self.execute(claim)
        prepared = self.broker.prepare(self.f.path,'comment')
        self.assertNotEqual(prepared['execution'],claim['execution'])
        with self.assertRaises(ValueError):
            with self.terminal(): self.broker.authorize(self.f.path,prepared['execution'],'comment','operator')
        with self.terminal(): self.broker.approve(prepared['execution'])
        with self.terminal(): fresh = self.broker.authorize(self.f.path,prepared['execution'],'comment','operator')
        self.execute(fresh)
        self.assertEqual(len(self.transport.calls),2)

    def test_shared_historical_hold_blocks_without_grant_consumption(self):
        self.budget.reserve('d4d25e5cc5574e70a0ce7651b7e76517','a'*64,5310000000)
        with self.assertRaises(ValueError): self.authorize()
        self.assertEqual(self.broker.inspect()['tasks'][self.first['id']]['state'],'queued')
        self.assertEqual(self.transport.calls,[])
        # A distinct disposable broker cannot use the same shared budget, even after billing settles.
        from src.coding_broker import CodingBroker
        alternate = dict(self.base.broker_config, ledger=str(self.f.root/'alternate-offline.sqlite'))
        CodingBroker(alternate,lambda:self.f.now).initialize()
        with self.terminal(), self.assertRaises(ValueError):
            DurableBroker(alternate,lambda:self.f.now).upgrade()

    def test_daily_and_lifetime_caps_across_queue_jobs(self):
        with self.budget.tx(True) as db:
            # Synthetic historical settled evidence leaves less than one maximum authorization.
            self.budget.event(db,'offline-fixture','a'*32,{})
        self.budget.reserve('a'*32,'a'*64,5_000_000_000)
        self.budget.settle('a'*32,5_000_000_000,{'status':'completed'})
        with self.assertRaises(ValueError): self.authorize()
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.budget.status()['lifetime_encumbered_nano_usd'],5_000_000_000)

    def test_reconciliation_requires_complete_linked_external_evidence(self):
        claim = self.authorize(); self.transport.raw = fixtures.envelope(id='resp_offline',prompt_cache_retention='24h')
        with self.assertRaises(ValueError): self.execute(claim)
        path,artifact = self.external(claim)
        original = e.decode(path.read_bytes())
        for key,value in [('final',False),('actual_nano_usd',0),('execution','f'*32),
                          ('provider_response_id','resp_conflict'),('artifact_sha256','a'*64),
                          ('outcome','confirmed-no-charge'),('usage',dict(original['usage'],input_tokens=1)),
                          ('reference','https://attacker.invalid/record')]:
            path.write_text(e.canonical(dict(original,**{key:value})))
            with self.terminal(), self.assertRaises(ValueError): reconcile(self.budget,path,artifact)
        path.write_text(e.canonical(original))
        with patch('src.billing_reconciliation.terminal_challenge',return_value='yes'),patch('sys.stdout',new=io.StringIO()):
            with self.assertRaises(ValueError): reconcile(self.budget,path,artifact)
        self.assertEqual(self.budget.status()['unresolved_requests'],1)


class LegacyUpgradeTests(unittest.TestCase):
    def test_legacy_consumed_records_remain_verifiable_and_fenced(self):
        setup = live.CodingTests(); setup.setUp(); self.addCleanup(setup.doCleanups)
        claim = setup.authorize()
        setup.transport.raw = fixtures.envelope(prompt_cache_retention='24h')
        with self.assertRaises(ValueError): setup.run_canary(claim)
        before = setup.broker.inspect()['tasks']
        with setup.broker.tx() as db:
            evidence = [tuple(x) for x in db.execute('SELECT * FROM events ORDER BY seq')]
        broker = DurableBroker(setup.broker_config,lambda:setup.f.now)
        with DurableTests.terminal(): broker.upgrade()
        self.assertEqual(broker.inspect()['legacy'],before)
        with broker.tx() as db:
            self.assertEqual([tuple(x) for x in db.execute('SELECT * FROM events ORDER BY seq')],evidence)
        with self.assertRaises(ValueError): broker.enqueue(setup.f.path,claim['execution'],'comment')
        with self.assertRaises(ValueError): canary.run(broker,claim,'operator',setup.controller)
        self.assertEqual(setup.budget.status()['unresolved_nano_usd'],5310000000)
        # Only synthetic external evidence closes this disposable legacy hold.
        helper = DurableTests()
        helper.f, helper.budget, helper.broker = setup.f, setup.budget, broker
        path,artifact = helper.external(claim)
        with DurableTests.terminal():
            reconcile(setup.budget,path,artifact)
            broker.adjudicate(claim['execution'],path,artifact)
        self.assertEqual(broker.inspect()['legacy'],before)
        self.assertIn(claim['execution'],broker.inspect()['legacy_closures'])
        prepared = broker.prepare(setup.f.path,'comment')
        with DurableTests.terminal():
            broker.approve(prepared['execution'])
            fresh = broker.authorize(setup.f.path,prepared['execution'],'comment','operator')
        setup.transport.raw = fixtures.envelope()
        canary.run(broker,fresh,'operator',setup.controller)
        self.assertNotEqual(fresh['execution'],claim['execution'])
        self.assertEqual(broker.inspect()['tasks'][fresh['execution']]['state'],'validated')


if __name__ == '__main__': unittest.main()
