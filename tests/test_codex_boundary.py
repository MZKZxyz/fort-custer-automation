"""Real official executor probes plus fail-closed admission tests; never inference."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.codex_boundary_probe import probe, _Executor
from src import codex_worker, integration_control
from test_grant_broker import Fixture


class AdmissionTests(unittest.TestCase):
    def test_unknown_cli_version_rejected_before_executor_start(self):
        with tempfile.TemporaryDirectory() as root:
            binary = Path(root)/'codex'; binary.touch()
            result = subprocess.CompletedProcess([], 0, stdout=b'codex-cli 0.164.0\n')
            with patch('subprocess.run', return_value=result), \
                 patch('subprocess.Popen', side_effect=AssertionError('unreviewed executor')):
                with self.assertRaisesRegex(ValueError, 'Unreviewed Codex version'):
                    with _Executor(binary, root): pass

    def test_no_auth_mode_tool_configuration_or_receipt_unlocks_live_worker(self):
        with patch('subprocess.Popen', side_effect=AssertionError('live startup')):
            for overrides in ({}, {'auth': 'chatgpt'}, {'auth': 'api_key'},
                              {'tools': ['shell']}, {'config': {'sandbox': 'disabled'}},
                              {'approved': True, 'isolated': True}, {'receipt': {'verified': True}}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    codex_worker.CodexWorker().run(**overrides)

    def test_broker_live_refusal_does_not_consume_approval_or_start_process(self):
        f = Fixture(); self.addCleanup(f.close)
        before = f.broker.path.read_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('bypassed broker')):
            with self.assertRaises(ValueError): f.broker.dispatch_live(auth='chatgpt')
        self.assertEqual(before, f.broker.path.read_bytes())
        self.assertEqual(f.broker.inspect()['active'], 0)

    def test_readiness_cannot_relabel_same_uid_as_safe_authentication(self):
        report = codex_worker.architecture_decision()
        self.assertEqual(report['outcome'], 'technical-blocker')
        self.assertEqual(report['option_b'], 'rejected-same-uid-credential-access')
        self.assertEqual(report['live_workers'], 0)
        self.assertFalse(report['activation_override'])
        with self.assertRaises(ValueError): integration_control.block_live_dispatch()


class RealExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary = os.environ.get('FC_CODEX_PROBE_BINARY')
        if not binary:
            raise unittest.SkipTest('Set FC_CODEX_PROBE_BINARY to reviewed Codex 0.163.0 for real OS probes')
        if not Path(binary).is_absolute() or not Path(binary).is_file():
            raise ValueError('Explicit absolute official Codex binary required')
        cls.report = probe(binary)
        print(json.dumps(cls.report, sort_keys=True))

    def test_real_transport_same_uid_auth_counterexample_and_unknown_rpc(self):
        self.assertTrue(self.report['same_uid_auth_readable'])
        self.assertTrue(self.report['same_uid_process_auth_readable'])
        self.assertTrue(self.report['omitted_sandbox_reads_controller_sentinel'])
        self.assertTrue(self.report['unknown_rpc_rejected'])
        self.assertFalse(self.report['inference'])
        self.assertFalse(self.report['live_ready'])

    def test_real_platform_result_never_claims_denial_without_positive_controls(self):
        if self.report['platform_sandbox_state'] != 'verified':
            self.assertIsNone(self.report['explicit_sandbox_denials'])
            self.assertIsNone(self.report['unapproved_write_denied'])
            if os.environ.get('FC_REQUIRE_CODEX_SANDBOX') == '1':
                self.fail('Platform sandbox positive controls failed: '+str(self.report))
            self.assertEqual(self.report['enforcement'], 'unverified-positive-control-failed')
            self.assertFalse(self.report['live_ready'])
            return  # A tested blocker result, not a verified OS denial.
        self.assertTrue(self.report['explicit_sandbox_positive_read'])
        self.assertTrue(self.report['approved_write'])
        self.assertEqual(self.report['explicit_sandbox_denials'], [True]*5)
        self.assertTrue(self.report['unapproved_write_denied'])


if __name__ == '__main__':
    unittest.main()
