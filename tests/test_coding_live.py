"""Real-source offline replay and deterministic transport; never inference."""
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_local_catalog as catalog
import coding_fixtures as fixtures
from src import coding_canary as canary, coding_api as profile, api_controller as api
from src import coding_contract as contract, orchestration_evidence as e
from src.coding_broker import CodingBroker, PROTOCOL
from src.api_budget import Budget
from src.local_runner import git, source_files, manifest


class Transport:
    synthetic = True
    def __init__(self):
        self.calls = []; self.raw = fixtures.envelope(); self.callback = lambda:None
    def send(self, body):
        api.validate_request(body)
        self.calls.append(e.decode(body)); self.callback()
        return self.raw


class CodingTests(unittest.TestCase):
    def setUp(self):
        f = catalog.CatalogTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.f = f
        source = fixtures.source(f.root/'pinned-source')
        repo = f.config['repositories']['fort-custer-server']
        repo.update(source=str(source), sha=canary.SOURCE)
        f.config['timeout_seconds'] = 60
        entry = f.entry()
        entry.update(source=canary.SOURCE, input_hash=manifest(source_files(source, canary.SOURCE)),
                     instructions=canary.INSTRUCTIONS, checks=[
                         dict(name='syntax', argv=['node','--check',contract.FILE], timeout_seconds=10),
                         dict(name='analyzer', argv=['node','--test','test/analyzer.test.js'], timeout_seconds=30)])
        entry['limits']['timeout_seconds'] = 60
        entry['limits'].update(api_spend_cents=contract.SPEND_CENTS, usage_policy=contract.USAGE_POLICY)
        f.config['catalog']['tasks'] = {'comment':entry}
        f.reload(); f.path.chmod(0o600)
        self.approved = f.approved('comment')
        (Path(f.config['state'])/'local.sqlite').chmod(0o600)
        self.budget = Budget(f.root/'api.sqlite'); self.budget.initialize()
        self.config = f.root/'api.json'
        self.api_config = dict(schema='responses-controller-v1', connectivity_enabled=False,
            credential_file=str(f.root/'never-read-key'), budget_file=str(self.budget.path),
            timezone='America/Los_Angeles', daily_nano_usd=10_000_000_000,
            lifetime_nano_usd=100_000_000_000, pricing=profile.PRICING)
        self.config.write_text(e.canonical(self.api_config)); self.config.chmod(0o600)
        self.broker_config = dict(schema=PROTOCOL, enabled=True, slots=1, live_limit=1,
            mode='coding-only', ledger=str(f.root/'coding.sqlite'), scratch=str(f.root/'coding-qa'),
            stop_files=[str(Path(f.config['state'])/'STOP')], max_tasks=1,
            max_artifact_bytes=1024*1024, max_storage_bytes=16*1024*1024,
            api_config=str(self.config))
        self.broker = CodingBroker(self.broker_config, lambda:f.now); self.broker.initialize()
        self.transport = Transport()
        self.controller = api.Controller(self.budget, self.transport, profile.PRICING)
        for name in ('src.api_controller.ResponsesTransport.send','src.api_controller._http_child',
                     'socket.socket.connect','src.local_publication.Publications'):
            fence = patch(name, side_effect=AssertionError('No live inference or publication'))
            fence.start(); self.addCleanup(fence.stop)

    def authorize(self):
        with patch('src.coding_broker.terminal_challenge', side_effect=lambda c:c), \
             patch('sys.stdout', new=io.StringIO()):
            return self.broker.authorize(self.f.path, self.approved['id'], 'comment', 'operator')

    def run_canary(self, claim):
        return canary.run(self.broker, claim, 'operator', self.controller)

    def test_real_edit_complete_offline_path(self):
        before = (Path(self.f.config['state'])/'local.sqlite').read_bytes()
        claim = self.authorize(); result = self.run_canary(claim)
        self.assertEqual(result['comment_regression'], 'executable-bytes-identical')
        self.assertEqual([x['name'] for x in result['checks']],
                         ['diff','syntax','analyzer','compile-regression','candidate'])
        self.assertTrue(all(x['code'] == 0 for x in result['checks']))
        self.assertIn('Validate the grid and compile', result['checks'][-1]['patch'])
        self.assertEqual(before, (Path(self.f.config['state'])/'local.sqlite').read_bytes())
        self.assertEqual(len(self.transport.calls), 1)
        request = self.transport.calls[0]
        self.assertEqual(request['model'], profile.MODEL)
        self.assertEqual(request['reasoning'], {'effort':'low'})
        self.assertEqual(request['tools'], [])
        self.assertNotIn(claim['token'], request['input'])
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)
        self.assertEqual(self.budget.status()['lifetime_encumbered_nano_usd'], 1464000)
        self.assertEqual(self.broker.inspect()['tasks'][claim['execution']]['state'], 'validated')
        with self.assertRaises(ValueError): self.run_canary(claim)
        with self.assertRaises(ValueError): self.authorize()
        self.assertEqual(len(self.transport.calls), 1)

    def test_unknown_envelope_keeps_hold_and_diagnostics(self):
        claim = self.authorize(); self.transport.raw = b'{"secret":"PRIVATE_MARKER"}'
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.budget.status()['unresolved_requests'], 1)
        self.assertEqual(self.budget.status()['lifetime_encumbered_nano_usd'], profile.MAXIMUM_CHARGE)
        self.assertNotIn('PRIVATE_MARKER', self.broker.path.read_bytes().decode(errors='ignore'))
        self.assertNotIn('PRIVATE_MARKER', self.budget.path.read_bytes().decode(errors='ignore'))
        self.assertEqual(self.broker.inspect()['tasks'][claim['execution']]['terminal_failure']['phase'],
                         'response_validation')
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(len(self.transport.calls), 1)

    def test_invalid_edit_is_billed_but_never_applied(self):
        claim = self.authorize()
        self.transport.raw = fixtures.envelope('{"old":"return rows;","new":"return [];"}')
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)
        self.assertEqual(self.broker.inspect()['tasks'][claim['execution']]['terminal_failure']['phase'],
                         'edit_validation')

    def test_stop_before_request(self):
        claim = self.authorize(); Path(self.broker.c['stop_files'][0]).touch()
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.transport.calls, [])

    def test_expired_approval_before_request(self):
        claim = self.authorize(); self.f.now = claim['deadline']
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.transport.calls, [])

    def test_stop_after_response_settles_without_delivery(self):
        claim = self.authorize()
        self.transport.callback = lambda:Path(self.broker.c['stop_files'][0]).touch()
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)
        self.assertEqual(self.broker.inspect()['tasks'][claim['execution']]['terminal_failure']['phase'],
                         'post_settlement_authorization')

    def test_expiry_after_response_settles(self):
        claim = self.authorize()
        self.transport.callback = lambda:setattr(self.f, 'now', claim['deadline'])
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)

    def test_source_change_after_response_settles(self):
        claim = self.authorize()
        source = self.f.config['repositories']['fort-custer-server']['source']
        self.transport.callback = lambda:git(source, '-c','user.name=Fixture','-c','user.email=f@local',
                                             'commit','--allow-empty','-qm','advanced')
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)
        self.assertIsNotNone(self.broker.inspect()['tasks'][claim['execution']]['terminal_failure'])

    def test_interrupted_request_consumed_without_retry(self):
        claim = self.authorize()
        def interrupt(): raise KeyboardInterrupt()
        self.transport.callback = interrupt
        with self.assertRaises(KeyboardInterrupt): self.run_canary(claim)
        self.assertEqual(self.budget.status()['unresolved_requests'], 1)
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(len(self.transport.calls), 1)

    def test_config_change_and_unapproved_principal_block(self):
        claim = self.authorize()
        with self.assertRaises(ValueError): canary.run(self.broker, claim, 'other', self.controller)
        config = dict(self.api_config, lifetime_nano_usd=99_000_000_000)
        self.config.write_text(e.canonical(config))
        with self.assertRaises(ValueError): self.run_canary(claim)
        self.assertEqual(self.transport.calls, [])

    def test_no_terminal_or_disabled_broker(self):
        with patch('src.coding_broker.terminal_challenge', return_value='yes'), \
             patch('sys.stdout', new=io.StringIO()):
            with self.assertRaises(ValueError):
                self.broker.authorize(self.f.path, self.approved['id'], 'comment', 'operator')
        self.broker.c['enabled'] = False
        with self.assertRaises(ValueError): self.authorize()
        self.assertEqual(self.transport.calls, [])

    def test_cache_write_and_long_context_accounting(self):
        for i, cached, writes, output in [(517,0,0,43),(2000,100,600,100),(272001,1000,500,4000)]:
            usage = dict(input_tokens=i,output_tokens=output,total_tokens=i+output,
                         input_tokens_details=dict(cached_tokens=cached,cache_write_tokens=writes),
                         output_tokens_details=dict(reasoning_tokens=output))
            raw = fixtures.envelope(usage=usage)
            result = api.receipt(raw,profile.payload('test'),profile.PRICING)
            expected=((i-cached-writes)*2000+cached*100+writes*2500)*(2 if i>272000 else 1)
            expected+=output*(15000 if i>272000 else 10000)
            self.assertEqual(result['estimated_cost_nano_usd'],expected)
            self.assertLessEqual(expected,profile.MAXIMUM_CHARGE)

    def test_failed_qa_retains_full_safe_check_diagnostics(self):
        from src import local_runner
        claim = self.authorize(); real = local_runner.supervise
        def check(command,*args,**kwargs):
            if '--test' in command:
                return dict(code=1,reason=None,stdout=b'full safe regression diagnostic',stderr=b'failure detail')
            return real(command,*args,**kwargs)
        with patch.object(local_runner,'supervise',side_effect=check):
            with self.assertRaises(ValueError): self.run_canary(claim)
        row = self.broker.inspect()['tasks'][claim['execution']]
        self.assertEqual(row['terminal_failure']['phase'],'independent_qa')
        reports = [x['evidence'] for x in row['events'] if x['state']=='qa_check']
        report = next(x for x in reports if x['name'] == 'analyzer')
        self.assertEqual(report['stderr'],'failure detail')
        self.assertEqual(report['stdout'],'full safe regression diagnostic')
        self.assertEqual(self.budget.status()['unresolved_requests'],0)


if __name__ == '__main__': unittest.main()
