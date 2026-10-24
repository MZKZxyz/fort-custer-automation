"""Offline receiver projection and shared-budget authority regressions."""
from pathlib import Path
import tempfile
import unittest
from src import api_evidence as evidence, api_controller as api, coding_api as profile
from src import orchestration_evidence as e
from src.api_budget import Budget


class EvidenceTests(unittest.TestCase):
    def test_projection_discards_unknowns_and_ill_typed_counters(self):
        raw = e.canonical(dict(id='resp_offline',status='completed',model=profile.MODEL,
            service_tier='priority',metadata={'secret':'NEVER_RETAIN'},output=['UNTRUSTED_CODE'],
            usage=dict(input_tokens=True,output_tokens=-1,input_tokens_details=dict(
                cached_tokens=30,cache_write_tokens='SECRET'),output_tokens_details=dict(reasoning_tokens=10)))).encode()
        result = evidence.observe(raw,profile.payload('test'),profile.PRICING,dict(execution='a'*32),
                                  dict(request_id='req_offline'))
        self.assertEqual(result['observed_usage'],dict(cached_input_tokens=30,reasoning_tokens=10))
        self.assertFalse(result['trusted']); self.assertEqual(result['provider_response_id'],'resp_offline')
        self.assertNotIn('NEVER_RETAIN',e.canonical(result)); self.assertNotIn('UNTRUSTED_CODE',e.canonical(result))
        for bad in ('sk_SECRET','resp_bad\nsecret',{},'resp_'+('x'*97)):
            self.assertIsNone(evidence.identifier(bad,'resp_'))

    def test_observation_and_dispatch_never_release_hold(self):
        with tempfile.TemporaryDirectory() as root:
            budget = Budget(Path(root).resolve()/'budget.sqlite'); budget.initialize()
            budget.reserve('a'*32,'b'*64,100)
            budget.record_dispatch('a'*32)
            with self.assertRaises(ValueError): budget.record_dispatch('a'*32)
            budget.record_observation('a'*32,evidence.observe(b'{}',profile.payload('test'),profile.PRICING,{}))
            self.assertEqual(budget.status()['unresolved_nano_usd'],100)
            with self.assertRaises(ValueError): budget.reserve('c'*32,'b'*64,1)

    def test_budget_broker_binding_cannot_change_or_use_legacy_receiver(self):
        with tempfile.TemporaryDirectory() as root:
            budget = Budget(Path(root).resolve()/'budget.sqlite'); budget.initialize()
            budget.bind_coding_authority('a'*64); budget.bind_coding_authority('a'*64)
            with self.assertRaises(ValueError): budget.bind_coding_authority('b'*64)
            budget.check_coding_authority('a'*64,required=True)
            for binding in ({'receiver':'synthetic-coding-only'},
                            {'receiver':'synthetic-coding-only','broker_authority':'b'*64}):
                with self.assertRaises(ValueError):
                    budget.reserve('a'*32,'b'*64,1,provenance=dict(binding=binding))
            self.assertEqual(budget.status()['unresolved_requests'],0)
            budget.reserve('a'*32,'b'*64,1,provenance=dict(binding=dict(
                receiver='synthetic-coding-only',broker_authority='a'*64)))
            self.assertEqual(budget.status()['unresolved_requests'],1)


if __name__ == '__main__': unittest.main()
