"""Subscription observations never convey tokens, billing finality or dispatch authority."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from execution_modes import read_modes, validate_modes, SubscriptionUsageMonitor
from readiness import ROOT, audit
from trust import require_live


class ExecutionModeTests(unittest.TestCase):
    def test_modes_explicit_disabled_and_initial_subscription_selected(self):
        config, mode = read_modes(ROOT)
        self.assertEqual(mode, 'chatgpt_subscription')
        for name in ('chatgpt_subscription', 'api_billing'):
            self.assertFalse(config['modes'][name]['live_enabled'])
            with self.assertRaises(RuntimeError): require_live()

    def test_reject_live_refills_fallback_token_proxy_and_weakened_api_caps(self):
        config,_=read_modes(ROOT)
        changes=[('chatgpt_subscription','live_enabled',True),('api_billing','live_enabled',True),
                 ('chatgpt_subscription','automatic_credit_purchase',True),('chatgpt_subscription','paid_refills',True),
                 ('chatgpt_subscription','api_billing_fallback',True),('chatgpt_subscription','custom_model_broker',True),
                 ('chatgpt_subscription','quota_is_per_task_cutoff',True),('chatgpt_subscription','credential_transport','token_proxy'),
                 ('api_billing','daily_cents',1001),('api_billing','task_reservation_cents',301),
                 ('api_billing','hard_cap_guarantee_required',False),('api_billing','authoritative_reconciliation_required',False),
                 ('api_billing','fail_closed',False),('chatgpt_subscription','paid_refills',0)]
        for mode,key,value in changes:
            changed=copy.deepcopy(config);changed['modes'][mode][key]=value
            with self.subTest(mode=mode,key=key),self.assertRaises(ValueError):validate_modes(changed)
        changed=copy.deepcopy(config);changed['automatic_mode_switch']=True
        with self.assertRaises(ValueError):validate_modes(changed)
        with self.assertRaises(ValueError):validate_modes(config,'unknown')

    def test_readiness_modes_do_not_share_financial_or_auth_evidence(self):
        sub,api=audit(mode='chatgpt_subscription'),audit(mode='api_billing')
        self.assertFalse(sub['ready']);self.assertFalse(api['ready'])
        self.assertNotEqual(sub['context'],api['context'])
        checks={c['id']:c for c in sub['checks']}
        self.assertEqual(checks['billing']['status'],'not_applicable')
        self.assertFalse(checks['billing']['mandatory'])
        self.assertEqual(checks['subscription_transport']['status'],'blocked')
        checks={c['id']:c for c in api['checks']}
        self.assertTrue(checks['billing']['mandatory'])
        self.assertEqual(checks['subscription_authentication']['status'],'not_applicable')
        self.assertEqual(api['policy']['daily_cents'],1000);self.assertEqual(api['policy']['task_cents'],300)
        for mode in ('chatgpt_subscription','api_billing'):
            result=subprocess.run([sys.executable,str(ROOT/'src/readiness.py'),'check','--mode',mode],capture_output=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(json.loads(result.stdout)['execution_mode'],mode)

    def test_invalid_mode_configuration_fails_closed_without_api_default(self):
        with patch('readiness.read_modes',side_effect=ValueError('invalid')):
            report=audit()
        self.assertIsNone(report['execution_mode'])
        checks={c['id']:c for c in report['checks']}
        self.assertEqual(checks['execution_configuration']['status'],'blocked')
        self.assertTrue(checks['billing']['mandatory'])
        self.assertFalse(report['ready'])

    def test_quota_observations_are_not_cutoff_or_dispatch_authority(self):
        m=SubscriptionUsageMonitor('thread1','turn1')
        result=m.observe(dict(method='account/rateLimits/updated',params=dict(rateLimits=dict(primary=dict(usedPercent=20),secondary=None))), 'app_server')
        self.assertEqual(result['state'],'quota_observed')
        self.assertFalse(result['may_dispatch']);self.assertFalse(result['guaranteed_per_task_cutoff'])
        result=m.observe(dict(method='account/rateLimits/updated',params=dict(rateLimits=dict(primary=dict(usedPercent=100)))), 'app_server')
        self.assertEqual(result['state'],'exhausted');self.assertTrue(result['stop'])
        result=m.observe(dict(method='account/rateLimits/updated',params=dict(rateLimits=dict(primary=dict(usedPercent=0)))), 'app_server')
        self.assertEqual(result['state'],'exhausted')
        self.assertFalse(result['automatic_retry']);self.assertFalse(result['buy_credits'])
        self.assertFalse(result['paid_refill']);self.assertIsNone(result['fallback_mode'])

    def test_app_server_usage_error_and_secondary_or_multibucket_limits(self):
        error=dict(method='error',params=dict(threadId='thread1',turnId='turn1',error=dict(codexErrorInfo='usageLimitExceeded')))
        self.assertEqual(SubscriptionUsageMonitor('thread1','turn1').observe(error,'app_server')['state'],'exhausted')
        completed=dict(method='turn/completed',params=dict(threadId='thread1',turn=dict(id='turn1',status='failed',error=dict(codexErrorInfo='usageLimitExceeded'))))
        self.assertEqual(SubscriptionUsageMonitor('thread1','turn1').observe(completed,'app_server')['state'],'exhausted')
        snapshots=[dict(secondary=dict(usedPercent=100)),dict(spendControlReached=True)]
        snapshots += [dict(rateLimitReachedType=value) for value in ('rate_limit_reached', 'workspace_owner_credits_depleted',
            'workspace_member_credits_depleted', 'workspace_owner_usage_limit_reached', 'workspace_member_usage_limit_reached')]
        for snapshot in snapshots:
            event=dict(method='account/rateLimits/updated',params=dict(rateLimits=None,rateLimitsByLimitId=dict(other=snapshot)))
            self.assertEqual(SubscriptionUsageMonitor('thread1','turn1').observe(event,'app_server')['state'],'exhausted')

    def test_cli_message_only_failure_and_malformed_data_do_not_invent_limits(self):
        cases=[('cli_jsonl',dict(type='turn.failed',error=dict(message='Usage limit reached; synthetic credential-like content'))),
               ('cli_jsonl',dict(type='error',message='unknown')),
               ('app_server',dict(method='error',params=dict(threadId='other',turnId='turn1',error=dict(codexErrorInfo='usageLimitExceeded')))),
               ('app_server',dict(method='account/rateLimits/updated',params=dict(rateLimits=dict(primary=dict(usedPercent=True))))),
               ('app_server',dict(method='account/rateLimits/updated',params=dict(rateLimits=dict(primary=dict(usedPercent=float('nan'))))))]
        for interface,event in cases:
            result=SubscriptionUsageMonitor('thread1','turn1').observe(event,interface)
            self.assertEqual(result['state'],'failed_unknown');self.assertTrue(result['stop'])
            self.assertNotIn('credential',json.dumps(result))

    def test_synthetic_broker_cannot_accept_subscription_auth_or_paid_provider(self):
        from model_broker import ModelBroker
        with self.assertRaises(RuntimeError):ModelBroker(Path('/nonexistent'),object(),lambda:0)
        # Even a synthetically successful model response cannot clear transport.
        with patch('readiness.require_live',return_value=None):
            self.assertFalse(audit(mode='chatgpt_subscription')['ready'])


if __name__=='__main__':unittest.main()
