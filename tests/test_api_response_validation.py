"""Schema-derived synthetic fixtures only; never provider captures or live calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src import api_controller as c, api_diagnostics as d, orchestration_evidence as e
from src.api_budget import Budget
from src import api_response_envelope as envelope

FIXTURES = Path(__file__).parent/'fixtures'/'responses'


def fixture(name='completed.json'):
    return json.loads((FIXTURES/name).read_text())


def validate(r):
    return c.receipt(e.canonical(r).encode(),c.payload('Reply with OK.',16),c.DEFAULT_PRICING)


class ResponseSchemaTests(unittest.TestCase):
    def reject(self,r,section,rule):
        with self.assertRaises(c.APIUnavailable) as caught: validate(r)
        diag=caught.exception.diagnostic
        self.assertEqual(diag['category'],'response_schema_invalid')
        self.assertEqual((diag['validation_section'],diag['validation_rule']),(section,rule))
        self.assertEqual((diag['phase'],diag['dispatch'],diag['http_status']),
                         ('response_validation','response_received',200))
        self.assertEqual(d.validate(diag),diag)
        return diag

    def test_documented_completed_nullable_and_reasoning_fixtures(self):
        for name in ('completed.json','nullable-metadata.json','reasoning.json'):
            with self.subTest(name=name):
                result=validate(fixture(name))
                self.assertEqual(result['status'],'completed')
                self.assertFalse(result['retry']);self.assertEqual(result['tools_executed'],0)
                self.assertNotIn('SYNTHETIC_',e.canonical(result))
                self.assertNotIn('id',result)
        self.assertEqual(validate(fixture())['estimated_cost_nano_usd'],15*50+5*5+2*400)
        self.assertEqual(validate(fixture('reasoning.json'))['estimated_cost_nano_usd'],15*50+5*5+10*400)

    def test_documented_incomplete_can_have_partial_reasoning_and_full_usage(self):
        r=fixture('incomplete.json');result=validate(r)
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(result['usage']['reasoning_tokens'],16)
        self.assertEqual(result['usage']['output_tokens'],16)
        r['output']=[]
        self.assertEqual(validate(r)['status'],'incomplete')

    def test_cache_write_zero_or_absent_is_safe_nonzero_is_unpriced(self):
        r=fixture();expected=validate(r)
        del r['usage']['input_tokens_details']['cache_write_tokens']
        self.assertEqual(validate(r),expected)
        r['usage']['input_tokens_details']['cache_write_tokens']=1
        self.reject(r,'cached_tokens','cache_write_not_priced')
        for value in (False,0.0,None,'0'):
            r['usage']['input_tokens_details']['cache_write_tokens']=value
            self.reject(r,'cached_tokens','token_type')
        r['usage']['input_tokens_details']['cache_write_tokens']=-1
        self.reject(r,'cached_tokens','token_bounds')

    def test_unknown_pricing_dimensions_fail_even_when_zero_or_null(self):
        for path,section in [((), 'usage'),(('input_tokens_details',),'cached_tokens'),
                             (('output_tokens_details',),'reasoning_tokens')]:
            for value in (0,None):
                r=fixture();target=r['usage']
                for key in path: target=target[key]
                target['SYNTHETIC_UNKNOWN_PRICING_DIMENSION']=value
                diag=self.reject(r,section,'unknown_dimension')
                self.assertNotIn('SYNTHETIC_',e.canonical(diag))

    def test_missing_nullable_or_incomplete_usage_does_not_guess_zero(self):
        for value in (None,{},[],False):
            r=fixture();r['usage']=value;self.reject(r,'usage','shape')
        for field,section in [('input_tokens_details','cached_tokens'),('output_tokens_details','reasoning_tokens')]:
            for value in (None,{},[]):
                r=fixture();r['usage'][field]=value;self.reject(r,section,'shape')
        r=fixture();del r['usage']['total_tokens'];self.reject(r,'usage','shape')

    def test_usage_tokens_are_integers_with_exact_totals_and_bounds(self):
        for field in ('input_tokens','output_tokens','total_tokens'):
            for value in (True,1.0,'1',None):
                r=fixture();r['usage'][field]=value;self.reject(r,'usage','token_type')
        for field,value in [('input_tokens',-1),('input_tokens',c.CONTEXT+1),('output_tokens',17),('total_tokens',-1)]:
            r=fixture();r['usage'][field]=value;self.reject(r,'usage','token_bounds')
        r=fixture();r['usage']['total_tokens']=99;self.reject(r,'usage','total_mismatch')

    def test_cached_and_reasoning_tokens_are_strict_subsets_not_extra_charges(self):
        for field,key,section,ceiling in [('input_tokens_details','cached_tokens','cached_tokens',20),
                                         ('output_tokens_details','reasoning_tokens','reasoning_tokens',2)]:
            for value in (None,True,1.0,'1'):
                r=fixture();r['usage'][field][key]=value;self.reject(r,section,'token_type')
            for value in (-1,ceiling+1):
                r=fixture();r['usage'][field][key]=value;self.reject(r,section,'token_bounds')
        r=fixture();r['usage']['input_tokens_details']['cached_tokens']=20
        r['usage']['output_tokens_details']['reasoning_tokens']=2
        self.assertEqual(validate(r)['estimated_cost_nano_usd'],20*5+2*400)

    def test_only_terminal_success_or_incomplete_with_usage_is_accepted(self):
        for status in (None,'queued','in_progress','failed','cancelled','SYNTHETIC_STATUS'):
            r=fixture();r['status']=status;self.reject(r,'completion','response_status')
        r=fixture();r['error']={'code':'SYNTHETIC_CODE','message':'SYNTHETIC_SECRET'}
        self.reject(r,'completion','provider_error')
        for details in ('secret',{'reason':'SYNTHETIC_REASON'},{'unknown':'secret'}):
            r=fixture('incomplete.json');r['incomplete_details']=details
            self.reject(r,'completion','incomplete_details')
        for details in (None,{}, {'reason':None}):
            r=fixture('incomplete.json');r['incomplete_details']=details
            self.assertEqual(validate(r)['status'],'incomplete')

    def test_envelope_errors_never_echo_dynamic_keys_or_values(self):
        self.reject([],'envelope','shape')
        r=fixture();r['SYNTHETIC_SECRET_FIELD']='SYNTHETIC_VALUE'
        self.assertNotIn('SYNTHETIC_',e.canonical(self.reject(r,'envelope','unknown_fields')))
        r=fixture();r['object']='wrong';self.reject(r,'envelope','object')
        r=fixture();r['model']='SYNTHETIC_UNREVIEWED_MODEL';self.reject(r,'envelope','model')

    def test_metadata_optional_nulls_and_plain_text_echoes_are_discarded(self):
        r=fixture('nullable-metadata.json')
        r.update(metadata={'SYNTHETIC_ID':'SYNTHETIC_TEXT'},instructions='SYNTHETIC_INSTRUCTIONS',
                 reasoning={'effort':None,'summary':None,'mode':'standard','context':'current_turn'},
                 text={'format':None,'verbosity':None},completed_at=0.5)
        self.assertNotIn('SYNTHETIC_',e.canonical(validate(r)))
        for field,value in [('metadata',{'a':10}),('id',None),('created_at',True),('created_at',None),('max_output_tokens',True),
                            ('text',[]),('reasoning',[])]:
            r=fixture();r[field]=value;self.reject(r,'metadata','field_type')

    def test_metadata_cannot_enable_tools_state_new_cache_modes_or_paid_tiers(self):
        for field,value in [('tools',[{'type':'web_search'}]),('tool_choice','auto'),
                            ('parallel_tool_calls',True),('store',True),('background',True),
                            ('conversation',{}),('previous_response_id','SYNTHETIC_ID'),
                            ('prompt',{}),('access_programs',{}),('moderation',{}),
                            ('prompt_cache_options',{'mode':'implicit','ttl':'30m'}),
                            ('truncation','auto'),('max_output_tokens',64),
                            ('reasoning',{'mode':'pro'}),('text',{'format':{'type':'json_object'}})]:
            r=fixture();r[field]=value;self.reject(r,'metadata','unsupported_configuration')
        r=fixture();r['service_tier']='priority';self.reject(r,'metadata','service_tier')
        r=fixture();r['prompt_cache_retention']='24h';self.reject(r,'metadata','cache_policy')

    def test_documented_read_only_cache_diagnostics_are_not_pricing(self):
        for value in [{'type':'cache_hit'},{'type':'unavailable'},{'type':'comparison_response_not_found'},
                      {'type':'cache_miss','reason':'input_changed','cache_missed_tokens':20,'comparison_reusable_tokens':None}]:
            r=fixture();r['prompt_cache_diagnostics']=value
            self.assertEqual(validate(r)['estimated_cost_nano_usd'],validate(fixture())['estimated_cost_nano_usd'])
        r=fixture();r['prompt_cache_diagnostics']={'type':'SYNTHETIC_UNKNOWN'}
        self.reject(r,'metadata','field_type')

    def test_executable_tools_and_unexpected_modalities_are_always_rejected(self):
        for kind in ('function_call','custom_tool_call','web_search_call','computer_call','mcp_call',
                     'image_generation_call','code_interpreter_call','local_shell_call','audio'):
            r=fixture();r['output']=[{'type':kind,'arguments':'SYNTHETIC_COMMAND'}]
            self.reject(r,'output','item_type')
        r=fixture();r['output']={};self.reject(r,'output','shape')
        r=fixture();r['output']=[None];self.reject(r,'output','shape')

    def test_message_part_fields_types_annotations_and_logprobs(self):
        r=fixture();r['output'][0]['role']='user';self.reject(r,'message','role')
        r=fixture();r['output'][0]['phase']='SYNTHETIC_PHASE';self.reject(r,'message','phase')
        r=fixture();r['output'][0]['content']={};self.reject(r,'message','shape')
        for field,value,rule in [('text',None,'text_type'),('annotations',None,'annotations'),
                                 ('annotations',[{'type':'url_citation'}],'annotations'),
                                 ('logprobs',[{'token':'SYNTHETIC_TOKEN'}],'logprobs'),
                                 ('SYNTHETIC_FIELD','SYNTHETIC_TEXT','unknown_fields')]:
            r=fixture();r['output'][0]['content'][0][field]=value;self.reject(r,'content',rule)
        r=fixture();r['output'][0]['content']=[{'type':'output_audio','data':'secret'}]
        self.reject(r,'content','shape')
        r=fixture();r['output'][0]['content']=[{'type':'refusal','refusal':'SYNTHETIC_REFUSAL'}]
        self.assertNotIn('SYNTHETIC_',e.canonical(validate(r)))
        r['output'][0]['content'][0]['refusal']=None;self.reject(r,'content','text_type')

    def test_item_status_is_nullable_only_where_documented_and_partial_only_when_incomplete(self):
        r=fixture();r['output'][0]['status']=None;self.reject(r,'output','item_status')
        r=fixture();r['output'][0]['status']='in_progress';self.reject(r,'output','item_status')
        r['status']='incomplete';self.assertEqual(validate(r)['status'],'incomplete')
        r=fixture('reasoning.json');r['output'][0]['status']=None;validate(r)

    def test_reasoning_is_typed_then_discarded_without_execution_or_identifiers(self):
        r=fixture('reasoning.json');self.assertNotIn('SYNTHETIC_',e.canonical(validate(r)))
        for field,value,rule in [('summary',None,'summary'),
            ('summary',[{'type':'summary_text','text':10}],'summary'),
            ('content',[{'type':'function_call','text':'SYNTHETIC_COMMAND'}],'content'),
            ('encrypted_content',{},'encrypted_content'),('SYNTHETIC_FIELD','secret','unknown_fields')]:
            r=fixture('reasoning.json');r['output'][0][field]=value
            self.reject(r,'reasoning',rule)

    def test_size_and_json_errors_are_structured_without_raw_parse_errors(self):
        for raw,category,rule in [(b'x'*(c.MAX_RESPONSE+1),'response_schema_invalid','size'),
                (b'{"SYNTHETIC_SECRET":','response_json_invalid','json'),
                (b'{"x":1,"x":2}','response_json_invalid','json'),(b'NaN','response_json_invalid','json')]:
            with self.assertRaises(c.APIUnavailable) as ctx:
                c.receipt(raw,c.payload('hello',16),c.DEFAULT_PRICING)
            self.assertEqual(ctx.exception.diagnostic['category'],category)
            self.assertEqual(ctx.exception.diagnostic['validation_rule'],rule)
            self.assertNotIn('SYNTHETIC_',e.canonical(ctx.exception.diagnostic))


class EnvelopeReviewTests(unittest.TestCase):
    reject = ResponseSchemaTests.reject
    def test_complete_reviewed_inventory_fixture(self):
        r=fixture('envelope-all-fields.json')
        self.assertEqual(set(r),envelope.ACCEPTED_FIELDS)
        self.assertEqual(len(envelope.SDK_FIELDS),36)
        self.assertEqual(len(envelope.OPENAPI_FIELDS),37)
        self.assertEqual(envelope.OPENAPI_FIELDS-envelope.SDK_FIELDS,{'output_text'})
        result=validate(r)
        self.assertEqual(result,validate(fixture()))
        self.assertNotIn('SYNTHETIC_',e.canonical(result))

    def test_output_text_absent_null_string_discarded(self):
        baseline=validate(fixture())
        for value in (None,'','SYNTHETIC_SECRET_TEXT',
                      '{"tools":[{"type":"function"}],"usage":{"total_tokens":0}}'):
            r=fixture();r['output_text']=value
            self.assertEqual(validate(r),baseline)

    def test_reviewed_name_is_diagnosed_without_granting_acceptance(self):
        r=fixture();r['output_text']='SYNTHETIC_SECRET_VALUE'
        with patch.object(envelope,'ACCEPTED_FIELDS',envelope.ACCEPTED_FIELDS-{'output_text'}):
            diag=self.reject(r,'envelope','unknown_fields')
        self.assertEqual(diag['unrecognized_fields'],['output_text'])
        self.assertFalse(diag['other_unrecognized_fields'])
        self.assertNotIn('SYNTHETIC_',e.canonical(diag))

    def test_output_text_type_strict(self):
        for value in (False,0,1.5,[],{},['text'],{'text':'SYNTHETIC_SECRET'}):
            r=fixture();r['output_text']=value
            diag=self.reject(r,'metadata','field_type')
            self.assertNotIn('SYNTHETIC_',e.canonical(diag))

    def test_metadata_never_substitutes_for_nested_validation(self):
        for section,rule,mutate in (
            ('usage','shape',lambda r:r.pop('usage')),
            ('usage','unknown_dimension',lambda r:r['usage'].update(audio_tokens=0)),
            ('cached_tokens','cache_write_not_priced',lambda r:r['usage']['input_tokens_details'].update(cache_write_tokens=1)),
            ('output','shape',lambda r:r.pop('output')),
            ('output','item_type',lambda r:r.update(output=[{'type':'function_call','name':'SYNTHETIC_SECRET'}]))):
            r=fixture('envelope-all-fields.json');mutate(r)
            self.reject(r,section,rule)

    def test_unknown_names_never_logged_and_official_request_names_diagnostic_only(self):
        for name in envelope.REQUEST_ONLY_FIELDS:
            for value in (None,{},'SYNTHETIC_SECRET'):
                r=fixture();r[name]=value;r['SYNTHETIC_SECRET_DYNAMIC_NAME']='SYNTHETIC_SECRET_VALUE'
                diag=self.reject(r,'envelope','unknown_fields')
                self.assertEqual(diag['unrecognized_fields'],[name])
                self.assertTrue(diag['other_unrecognized_fields'])
                self.assertNotIn('SYNTHETIC_',e.canonical(diag))
        r=fixture();r['SYNTHETIC_SECRET_DYNAMIC_NAME']=None
        diag=self.reject(r,'envelope','unknown_fields')
        self.assertEqual(diag['unrecognized_fields'],[])
        self.assertTrue(diag['other_unrecognized_fields'])

    def test_official_name_only_diagnostic_sorted_bounded_and_validated(self):
        r=fixture();r.update({name:None for name in envelope.REQUEST_ONLY_FIELDS})
        diag=self.reject(r,'envelope','unknown_fields')
        self.assertEqual(diag['unrecognized_fields'],sorted(envelope.REQUEST_ONLY_FIELDS))
        self.assertFalse(diag['other_unrecognized_fields'])
        for changes in ({'unrecognized_fields':['SYNTHETIC_SECRET']},
                        {'unrecognized_fields':['input','input']},
                        {'unrecognized_fields':['stream','input']},
                        {'unrecognized_fields':{'input':None}},
                        {'unrecognized_fields':[{}]},
                        {'other_unrecognized_fields':1},
                        {'unrecognized_fields':[]},
                        {'validation_section':'usage','validation_rule':'unknown_dimension'},
                        {'SYNTHETIC_SECRET':'x'}):
            with self.assertRaises(ValueError):d.validate(dict(diag,**changes))

    def test_new_metadata_cannot_relax_security_retention_or_pricing(self):
        for name,value,rule in [('store',True,'unsupported_configuration'),
                ('background',True,'unsupported_configuration'),('parallel_tool_calls',True,'unsupported_configuration'),
                ('tools',[{'type':'function'}],'unsupported_configuration'),
                ('tool_choice','auto','unsupported_configuration'),
                ('service_tier','priority','service_tier'),('prompt_cache_retention','24h','cache_policy'),
                ('prompt_cache_options',{'mode':'implicit','ttl':'30m'},'unsupported_configuration'),
                ('conversation',{'id':'SYNTHETIC_ID'},'unsupported_configuration'),
                ('access_programs',{'cyber':'standard'},'unsupported_configuration'),
                ('moderation',{},'unsupported_configuration')]:
            r=fixture('envelope-all-fields.json');r[name]=value
            self.reject(r,'metadata',rule)

    def test_unknown_envelope_keeps_synthetic_hold_no_retry_no_metadata_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Budget(Path(tmp).resolve()/'budget.sqlite');b.initialize()
            r=fixture('envelope-all-fields.json');r.update(stream=False,SYNTHETIC_SECRET_NAME='SYNTHETIC_SECRET_VALUE')
            fake=Mock();fake.send.return_value=e.canonical(r).encode()
            controller=c.Controller(b,fake);ident='b'*32
            with self.assertRaises(c.APIUnavailable) as ctx:
                controller._request(ident,c.payload('Reply with OK.',16),{'purpose':'offline'},lambda:None)
            self.assertTrue(ctx.exception.audit_recorded)
            self.assertEqual(b.status()['unresolved_nano_usd'],20_006_400)
            with b.tx() as db:
                row=dict(db.execute('SELECT * FROM requests').fetchone())
                self.assertIsNone(row['actual']);self.assertIsNone(row['receipt'])
            self.assertEqual([x['kind'] for x in b.audit()],['reserved','request_failed_hold_retained'])
            self.assertEqual(json.loads(b.audit()[-1]['evidence'])['unrecognized_fields'],['stream'])
            self.assertNotIn('SYNTHETIC_',e.canonical(b.audit()))
            self.assertNotIn(b'SYNTHETIC_',b.path.read_bytes())
            with self.assertRaises(ValueError):
                controller._request(ident,c.payload('Reply with OK.',16),{'purpose':'offline'},lambda:None)
            self.assertEqual(fake.send.call_count,1)


class ValidationEvidenceTests(unittest.TestCase):
    def test_diagnostics_are_backward_compatible_and_reject_provider_controlled_labels(self):
        old=d.diagnostic('authentication','response_headers','response_received',401)
        self.assertEqual(d.validate(old),old)
        for section,rule in [('SYNTHETIC_SECRET','shape'),('usage','SYNTHETIC_SECRET')]:
            bad=dict(old,validation_section=section,validation_rule=rule)
            with self.assertRaises(ValueError):d.validate(bad)
            self.assertNotIn('SYNTHETIC_',e.canonical(d.diagnostic('response_schema_invalid',
                validation_section=section,validation_rule=rule)))

    def test_structured_failure_roundtrips_through_ipc_without_values(self):
        diag=d.diagnostic('response_schema_invalid','response_validation','response_received',200,
                         validation_section='cached_tokens',validation_rule='cache_write_not_priced')
        named=d.diagnostic('response_schema_invalid','response_validation','response_received',200,
            validation_section='envelope',validation_rule='unknown_fields',
            unrecognized_fields=['stream'],other_unrecognized_fields=True)
        for evidence in (diag,named):
            context,receiver,sender,process=Mock(),Mock(),Mock(),Mock()
            context.Pipe.return_value=(receiver,sender);context.Process.return_value=process
            receiver.recv.return_value=('error',evidence)
            with patch('src.api_controller.multiprocessing.get_context',return_value=context):
                with self.assertRaises(c.APIUnavailable) as ctx:
                    c.ResponsesTransport('/never/read/key').send(e.canonical(c.payload('hello',16)).encode())
            self.assertEqual(ctx.exception.diagnostic,evidence)

    def test_audit_retains_structured_failure_and_original_reservation(self):
        # This UUID is copied into a disposable fixture ONLY; never the operator ledger.
        ident='afa8d02e954e4214aef599bd25365d02'
        with tempfile.TemporaryDirectory() as tmp:
            b=Budget(Path(tmp).resolve()/'budget.sqlite');b.initialize()
            r=fixture();r['usage']['input_tokens_details']['cache_write_tokens']=1
            class Fake:
                synthetic=True
                calls=0
                def send(self,body):self.calls+=1;return e.canonical(r).encode()
            fake=Fake();controller=c.Controller(b,fake)
            with self.assertRaises(c.APIUnavailable) as ctx:
                controller._request(ident,c.payload('Reply with OK.',16),{'purpose':'offline'},lambda:None)
            self.assertTrue(ctx.exception.audit_recorded)
            self.assertEqual(b.status()['unresolved_nano_usd'],20_006_400)
            with b.tx() as db:
                row=dict(db.execute('SELECT * FROM requests').fetchone())
                self.assertIsNone(row['actual']);self.assertIsNone(row['receipt'])
            events=b.audit();self.assertEqual([x['kind'] for x in events],['reserved','request_failed_hold_retained'])
            evidence=json.loads(events[-1]['evidence'])
            self.assertEqual(evidence['validation_section'],'cached_tokens')
            self.assertEqual(evidence['validation_rule'],'cache_write_not_priced')
            self.assertNotIn('SYNTHETIC_',e.canonical(events))
            with self.assertRaises(ValueError):
                controller._request(ident,c.payload('Reply with OK.',16),{'purpose':'offline'},lambda:None)
            self.assertEqual(fake.calls,1)
            self.assertEqual(Budget(b.path).status()['unresolved_requests'],1)

    def test_successful_fixture_reconciles_only_actual_usage_and_no_provider_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Budget(Path(tmp).resolve()/'budget.sqlite');b.initialize()
            fake=Mock();fake.send.return_value=e.canonical(fixture('envelope-all-fields.json')).encode()
            result=c.Controller(b,fake)._request('a'*32,c.payload('Reply with OK.',16),{'purpose':'offline'},lambda:None)
            self.assertEqual(b.status()['unresolved_requests'],0)
            self.assertEqual(b.status()['lifetime_encumbered_nano_usd'],result['estimated_cost_nano_usd'])
            self.assertNotIn('SYNTHETIC_',e.canonical(b.audit()))
            self.assertNotIn(b'SYNTHETIC_',b.path.read_bytes())


if __name__=='__main__':unittest.main()
