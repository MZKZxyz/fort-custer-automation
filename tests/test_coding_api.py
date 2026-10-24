"""Fast profile/adversarial accounting tests; no transport credentials."""
import copy
import tempfile
from pathlib import Path
import unittest
import json

import coding_fixtures as fixtures
from src import api_controller as api, coding_api as profile, orchestration_evidence as e
from src.api_budget import Budget


class ProfileTests(unittest.TestCase):
    def test_new_catalog_profile_cannot_reinterpret_subscription_grants(self):
        from src import coding_contract as contract
        entry = json.loads((Path(__file__).parents[1]/'config/coding-task.example.json').read_text())['catalog']['tasks']['sol-low-compile-comment']
        contract.catalog_task(entry)
        for changes in (dict(source='f'*40),dict(allowed=['other.js']),
                        dict(limits=dict(entry['limits'],api_spend_cents=0,
                                         usage_policy='subscription-no-paid-refills')),
                        dict(limits=dict(entry['limits'],api_spend_cents=532))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                contract.catalog_task(dict(entry,**changes))
    def test_fixture_profile_and_exact_replacement(self):
        value = fixtures.capture()
        request = profile.payload('test')
        self.assertEqual({k:v for k,v in request.items() if k not in {'input','service_tier'}},
                         value['request_parameters'])
        self.assertEqual(value['provenance']['source_file'],'tools/maze-analyzer/solver.js')
        self.assertEqual(value['provenance']['response_status'],'completed')
        self.assertEqual(profile.visible_edit(fixtures.envelope()), e.canonical(value['model_output']).encode())

    def test_exact_request_profile(self):
        request = profile.payload('test')
        api.validate_request(e.canonical(request).encode())
        for key,value in [('tools',[{'type':'web_search'}]),('reasoning',{'effort':'medium'}),
                          ('max_output_tokens',4001),('store',True),('background',True),
                          ('stream',True),('service_tier','priority'),('prompt_cache_retention','12h'),
                          ('input','x'*24001)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                api.validate_request(e.canonical(dict(request,**{key:value})).encode())

    def test_invalid_coding_response_never_becomes_edit(self):
        for text in ('{}','[]','null','not JSON','x'*16385,
                     '{"old":"a","new":"b","file":"unexpected.js"}',
                     '{"old":"a","old":"b","new":"c"}',
                     '{"old":true,"new":"b"}'):
            with self.subTest(text=text[:50]), self.assertRaises(ValueError):
                profile.visible_edit(fixtures.envelope(text))
        for changes in (dict(status='incomplete',incomplete_details={'reason':'max_output_tokens'}),
                        dict(output=[]),dict(output=[{'type':'function_call','name':'shell','arguments':'pwd'}]),
                        dict(model='unexpected-model')):
            raw=fixtures.envelope(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                api.receipt(raw,profile.payload('test'),profile.PRICING)
                profile.visible_edit(raw)

    def test_unpriced_or_invalid_usage_retains_full_hold(self):
        base=fixtures.capture()['usage']
        cases=[]
        for details in ({'cached_tokens':0}, {'cached_tokens':0,'cache_write_tokens':True},
                        {'cached_tokens':500,'cache_write_tokens':500},
                        {'cached_tokens':0,'cache_write_tokens':100,'cache_write_tokens_details':
                         {'ttl_30m_tokens':0,'ttl_12h_tokens':100}},
                        {'cached_tokens':0,'cache_write_tokens':0,'unknown':1}):
            cases.append(dict(base,input_tokens_details=details))
        cases.extend([dict(base,output_tokens=4001,total_tokens=4518),dict(base,input_tokens=True),
                      dict(base,total_tokens=1)])
        for usage in cases:
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                api.receipt(fixtures.envelope(usage=usage),profile.payload('test'),profile.PRICING)

    def test_settled_incomplete_is_consumed_and_duplicate_never_sends(self):
        class Transport:
            synthetic=True
            calls=0
            def send(self,body):
                self.calls+=1
                return fixtures.envelope(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
        with tempfile.TemporaryDirectory() as temp:
            budget=Budget(Path(temp)/'budget.sqlite');budget.initialize()
            transport=Transport(); controller=api.Controller(budget,transport,profile.PRICING)
            for _ in range(2):
                with self.assertRaises(ValueError):
                    controller._request('f'*32,profile.payload('test'),
                        {'receiver':'synthetic-coding-only'},lambda:None,_coding=True)
            self.assertEqual(transport.calls,1)
            self.assertEqual(budget.status()['unresolved_requests'],0)


if __name__ == '__main__': unittest.main()
