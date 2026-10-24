"""Synthetic-only planning; sockets and real credential reads are forbidden."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from src import api_controller as c, observation_planning as p
from src import orchestration_evidence as e
from src.api_budget import Budget
from test_api_controller import Fake, response
from test_grant_broker import Fixture


def output(text=None, **changes):
    if text is None:
        text = e.canonical(dict(schema=p.SCHEMA, disposition='ready_for_review'))
    return response(output=[dict(type='message', role='assistant', status='completed',
        content=[dict(type='output_text', text=text, annotations=[])])], **changes)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.addCleanup(self.f.close)
        self.claim = self.f.claim()
        self.path = self.f.f.root/'planning-budget.sqlite'
        self.budget = Budget(self.path); self.budget.initialize()
        self.fake = Fake(output())
        self.controller = c.Controller(self.budget, self.fake)
        self.planner = p.Planner(self.controller)
        # Fixtures create only local repositories before these denial fences.
        # No production transport, socket or credential read exists in a plan.
        for target in ('socket.socket.connect', 'socket.create_connection',
                       'src.api_controller.ResponsesTransport.send',
                       'src.api_controller._http_child'):
            fence = patch(target, side_effect=AssertionError('Offline test boundary'))
            fence.start(); self.addCleanup(fence.stop)
        clean_env = patch.dict(os.environ, {}, clear=True)
        clean_env.start(); self.addCleanup(clean_env.stop)

    def observe(self):
        return self.planner.observe(self.f.broker, self.claim, 'mock')

    def test_valid_bound_non_executable_deterministic_request(self):
        before = self.f.controller.path.read_bytes()
        decision = self.observe()
        self.assertEqual(decision.classification, p.Classification('ready_for_review', 'review_required'))
        a = self.f.broker.inspect()['tasks'][self.claim['execution']]['authorization']
        self.assertEqual(decision.provenance.task, a['task'])
        self.assertEqual(decision.provenance.source_manifest, a['source_manifest'])
        self.assertEqual(decision.provenance.authorization, e.digest(a))
        self.assertEqual(decision.provenance.claim, e.digest(self.claim))
        self.assertEqual(self.planner.verify(decision, self.f.broker, self.claim, 'mock'), decision)
        self.assertEqual(self.f.controller.path.read_bytes(), before)
        request = self.fake.body
        self.assertLessEqual(len(request['input'].encode()), c.MAX_INPUT_BYTES)
        self.assertEqual(request['tools'], [])
        policy = e.decode(request['input'])['policy']
        self.assertEqual(policy['dispositions'], sorted(p.REASONS))
        self.assertIn('Return exactly schema and disposition.', policy['instruction'])
        self.assertNotIn('reason_code', e.canonical(policy))
        self.assertEqual(e.decode(request['input'])['untrusted_task'], a['spec']['task'])
        self.assertNotIn(self.claim['token'], request['input'])
        self.assertFalse(hasattr(decision, 'approved'))

    def test_all_four_dispositions(self):
        for disposition, reason in {
            'ready_for_review': 'review_required', 'insufficient_context': 'missing_context',
            'policy_blocked': 'policy_constraint', 'no_change_recommended': 'no_change_needed',
        }.items():
            raw = output(e.canonical(dict(schema=p.SCHEMA, disposition=disposition)))
            self.assertEqual(p._classification(raw), p.Classification(disposition, reason))

    def test_provenance_tampering_and_changed_claim(self):
        decision = self.observe()
        for key, value in dict(task='another-task', execution='another-execution', claim='a'*64,
                               principal='another', authorization='b'*64, source_manifest='c'*64,
                               task_digest='d'*64, request_id='e'*32).items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.planner.verify(replace(decision, provenance=replace(decision.provenance, **{key:value})),
                                    self.f.broker, self.claim, 'mock')
        changed = dict(self.claim, generation=self.claim['generation']+1)
        with self.assertRaises(ValueError): self.planner.verify(decision, self.f.broker, changed, 'mock')

    def test_source_change_before_dispatch_and_after_response(self):
        a = self.f.broker.inspect()['tasks'][self.claim['execution']]['authorization']
        source = Path(self.f.controller.config['repositories'][a['spec']['repo']]['source'])
        def advance():
            subprocess.run(['/usr/bin/git', '-C', str(source), '-c', 'user.name=Fixture',
                '-c', 'user.email=fixture@local', 'commit', '--allow-empty', '-qm', 'source changed'], check=True)
        advance()
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.fake.calls, 0)
        subprocess.run(['/usr/bin/git', '-C', str(source), 'reset', '--hard', a['source']],
                       check=True, stdout=subprocess.DEVNULL)
        self.fake.callback = advance
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.fake.calls, 1)
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)

    def test_stop_before_dispatch(self):
        with patch('src.grant_broker.stopped', return_value=True):
            with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.fake.calls, 0)
        self.assertEqual(self.budget.status()['lifetime_encumbered_nano_usd'], 0)

    def test_expired_and_wrong_principal_before_dispatch(self):
        with self.assertRaises(ValueError):
            self.planner.observe(self.f.broker, self.claim, 'another-principal')
        self.f.broker.clock = lambda:self.claim['deadline']
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.fake.calls, 0)
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)

    def test_stop_after_response_bills_without_delivery(self):
        stop = Path(self.f.broker.c['stop_files'][0])
        self.fake.callback = lambda:stop.touch(mode=0o600)
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)
        self.assertGreater(self.budget.status()['lifetime_encumbered_nano_usd'], 0)

    def test_expiry_after_response(self):
        self.fake.callback = lambda:setattr(self.f.broker, 'clock', lambda:self.claim['deadline'])
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)

    def test_revocation_after_response(self):
        # A broker hold revokes ownership for planning, even before deadline.
        self.fake.callback = lambda:self.f.broker.hold(self.claim, 'operator-stop')
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)

    def test_duplicates_and_restart_never_dispatch_twice(self):
        self.observe()
        self.planner = p.Planner(c.Controller(Budget(self.path), self.fake))
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.fake.calls, 1)

    def test_uncertain_transport_retains_durable_hold(self):
        self.fake.error = TimeoutError('untrusted error details')
        with self.assertRaises(c.APIUnavailable): self.observe()
        self.assertEqual(Budget(self.path).status()['unresolved_requests'], 1)
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.fake.calls, 1)
        self.assertNotIn('untrusted error details', e.canonical(self.budget.audit()))

    def test_crash_after_reservation_keeps_hold(self):
        # Simulate an abrupt control-flow exit (not caught as a transport error).
        self.fake.callback = lambda:(_ for _ in ()).throw(SystemExit(23))
        with self.assertRaises(SystemExit): self.observe()
        self.assertEqual(Budget(self.path).status()['unresolved_requests'], 1)
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.fake.calls, 1)

    def test_adversarial_outputs_have_no_side_effects_or_persistence(self):
        valid = dict(schema=p.SCHEMA, disposition='ready_for_review')
        marker = 'UNTRUSTED_PRIVATE_MARKER'
        texts = ['not json', '[]', 'null', 'NaN', '{}', 'x'*257,
                 '{"schema":"observation-decision-v1","schema":"observation-decision-v1"}',
                 e.canonical(dict(valid, disposition='execute')),
                 e.canonical(dict(valid, disposition=[])),
                 e.canonical(dict(valid, reason_code=True)),
                 e.canonical(dict(valid, reason_code='review_required')),
                 e.canonical(dict(valid, reason_code='policy_blocked')),
                 e.canonical(dict(valid, reason_code='missing_context')),
                 e.canonical(dict(valid, schema='v2'))]
        for key in ('approval', 'approved', 'command', 'patch', 'files', 'url', 'tool_arguments',
                    'publish', 'provenance', 'reasoning'):
            texts.append(e.canonical(dict(valid, **{key:marker})))
        hostile = [output(text) for text in texts]
        hostile += [output(status='incomplete'), response(output=[dict(type='function_call',
            name='shell', arguments=marker)]), response(output=[]),
            response(output=[dict(type='message', role='assistant', content=[dict(type='refusal', refusal=marker)])])]
        broker_before = self.f.broker.path.read_bytes()
        approval_before = self.f.controller.path.read_bytes()
        real_popen = subprocess.Popen
        def read_only_git(argv, *args, **kwargs):
            self.assertEqual(argv[:2], ['/usr/bin/git', '-c'])
            self.assertEqual(argv[5], '-C')
            self.assertIn(argv[7], ('remote', 'rev-parse', 'ls-tree', 'cat-file'))
            return real_popen(argv, *args, **kwargs)
        for i, raw in enumerate(hostile):
            with self.subTest(index=i):
                path = self.path.parent/f'bad-observation-{i}.sqlite'
                budget = Budget(path); budget.initialize()
                self.planner = p.Planner(c.Controller(budget, Fake(raw)))
                with patch('subprocess.Popen', side_effect=read_only_git), \
                     patch.object(Path, 'write_text', side_effect=AssertionError('No model file writes')), \
                     patch.object(Path, 'write_bytes', side_effect=AssertionError('No model file writes')), \
                     patch('src.api_tools.executable_receiver', side_effect=AssertionError('No execution')):
                    with self.assertRaises(ValueError): self.observe()
                self.assertEqual(self.planner.controller.transport.calls, 1)
                self.assertNotIn(marker.encode(), path.read_bytes())
                self.assertNotIn(marker, e.canonical(budget.audit()))
        self.assertEqual(broker_before, self.f.broker.path.read_bytes())
        self.assertEqual(approval_before, self.f.controller.path.read_bytes())

    def test_general_receipt_never_exposes_classification(self):
        receipt = c.receipt(output(), c.payload('offline'), c.DEFAULT_PRICING)
        self.assertNotIn('ready_for_review', e.canonical(receipt))
        self.observe()
        self.assertNotIn('review_required', e.canonical(self.budget.audit()))
        self.assertNotIn(b'review_required', self.path.read_bytes())

    def test_live_transport_denied_before_any_credential_access(self):
        self.planner = p.Planner(c.Controller(self.budget, c.ResponsesTransport('/never/read/key')))
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(self.budget.status()['unresolved_requests'], 0)


if __name__ == '__main__': unittest.main()
