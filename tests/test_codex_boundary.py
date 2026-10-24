"""Real official executor probes plus fail-closed admission tests; never inference."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from src.codex_boundary_probe import (probe, _Executor, _process_cat,
                                      _process_counterexample, _local_counterexample)
from src import codex_worker, integration_control
from test_grant_broker import Fixture


class AdmissionTests(unittest.TestCase):
    def test_unknown_cli_version_rejected_before_executor_start(self):
        with tempfile.TemporaryDirectory() as root:
            binary = Path(root).resolve(strict=True)/'codex'; binary.touch()
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


class ProbeRegressionTests(unittest.TestCase):
    def test_process_waits_for_terminal_status_and_accumulates_chunks(self):
        server = Mock()
        def result(chunks, exited=False):
            return dict(result=dict(chunks=chunks, exited=exited,
                exitCode=0 if exited else None, failure=None, sandboxDenied=False))
        import base64
        def chunk(seq, value): return dict(seq=seq, stream='stdout', chunk=base64.b64encode(value).decode())
        server.rpc.side_effect = [dict(result=dict(sandboxType='none')), result([]),
            result([chunk(1, b'base')]), result([chunk(2, b'line')], True)]
        r = _process_cat(server, 'control', Path('/fixture/allowed.txt'), Path('/fixture'))
        self.assertTrue(r['complete']); self.assertEqual(r['stdout'], b'baseline')
        self.assertEqual(server.rpc.call_args.args[1]['afterSeq'], 1)

    def test_missing_terminal_evidence_never_counts_as_success(self):
        server = Mock()
        server.rpc.side_effect = [dict(result={})]+[dict(result=dict(chunks=[], exited=False))]*5
        r = _process_cat(server, 'control', Path('/fixture/file'), Path('/fixture'))
        self.assertFalse(r['complete']); self.assertFalse(r['denied'])

    def test_failed_process_positive_control_cannot_be_a_credential_denial(self):
        server = Mock()
        server.rpc.side_effect = [dict(result={}), dict(result=dict(chunks=[], exited=True,
            exitCode=1, failure='bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted', sandboxDenied=True))]
        r = _process_counterexample(server, Path('/fixture'), Path('/fixture/allowed'),
                                    Path('/fixture/auth'), b'marker')
        self.assertEqual(r, dict(positive_read=False, state='unavailable', auth_readable=None))
        self.assertEqual(server.rpc.call_count, 2)  # Never attempt credential read after failed control.

    def test_helper_failure_after_successful_control_is_still_unavailable(self):
        server = Mock()
        import base64
        server.rpc.side_effect = [dict(result={}), dict(result=dict(
            chunks=[dict(seq=1, stream='stdout', chunk=base64.b64encode(b'baseline').decode())],
            exited=True, exitCode=0, failure=None, sandboxDenied=False)),
            dict(result={}), dict(result=dict(chunks=[], exited=True, exitCode=1,
                failure='bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted', sandboxDenied=True))]
        r = _process_counterexample(server, Path('/fixture'), Path('/fixture/allowed'),
                                    Path('/fixture/auth'), b'marker')
        self.assertEqual(r, dict(positive_read=True, state='unavailable', auth_readable=None))

    def test_observed_denial_requires_successful_process_control(self):
        with patch('src.codex_boundary_probe._process_cat', side_effect=[
                dict(complete=True, stdout=b'baseline', denied=False),
                dict(complete=False, stdout=b'', denied=True)]):
            r = _process_counterexample(Mock(), Path('/fixture'), Path('/fixture/allowed'),
                                        Path('/fixture/auth'), b'marker')
        self.assertEqual(r, dict(positive_read=True, state='observed-denial', auth_readable=False))

    def test_local_counterexample_requires_positive_control(self):
        failed = subprocess.CompletedProcess([], 1, b'', b'control failed')
        with patch('subprocess.run', return_value=failed) as run:
            r = _local_counterexample(Path('/fixture'), Path('/fixture/allowed'), Path('/fixture/auth'), b'marker')
        self.assertFalse(r['positive_read']); self.assertIsNone(r['auth_readable'])
        run.assert_called_once()

    def simulated_probe(self, *, unavailable=False, leaked=False, write_available=True):
        import base64
        from urllib.parse import urlparse, unquote
        class Server:
            def __init__(self, binary, root): self.processes = {}; self.root = root
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def rpc(self, method, params):
                if method == 'process/start':
                    self.processes[params['processId']] = Path(params['argv'][1])
                    return dict(result=dict(sandboxType='none'))
                if method == 'process/read':
                    if unavailable:
                        return dict(result=dict(chunks=[], exited=True, exitCode=1, sandboxDenied=True,
                            failure='bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted'))
                    raw = self.processes[params['processId']].read_bytes()
                    return dict(result=dict(chunks=[dict(seq=1, stream='stdout', chunk=base64.b64encode(raw).decode())],
                        exited=True, exitCode=0, failure=None, sandboxDenied=False))
                if method.startswith('fs/'):
                    path = Path(unquote(urlparse(params['path']).path))
                    if params['sandbox'] is not None:
                        if unavailable:
                            return dict(error=dict(message='bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted'))
                        if path.name != 'allowed.txt' and not leaked:
                            return dict(error=dict(message='Permission denied'))
                    if method == 'fs/readFile':
                        return dict(result=dict(dataBase64=base64.b64encode(path.read_bytes()).decode()))
                    if not write_available: return dict(error=dict(message='setup failed'))
                    path.write_bytes(base64.b64decode(params['dataBase64']))
                    return dict(result={})
                return dict(error=dict(message='unknown method'))
        with patch('src.codex_boundary_probe._Executor', Server): return probe('/synthetic/codex')

    def test_linux_bubblewrap_network_namespace_unavailable_is_not_isolation(self):
        report = self.simulated_probe(unavailable=True)
        self.assertTrue(report['same_uid_auth_readable'])
        self.assertTrue(report['same_uid_subprocess_positive_read'])
        self.assertTrue(report['same_uid_subprocess_auth_readable'])
        self.assertIsNone(report['same_uid_process_auth_readable'])
        self.assertEqual(report['executor_process_state'], 'unavailable')
        self.assertEqual(report['platform_sandbox_state'], 'unavailable')
        self.assertIsNone(report['explicit_sandbox_denials'])
        self.assertIsNone(report['unapproved_write_denied'])
        self.assertIn('RTM_NEWADDR', report['sandbox_setup_detail'])
        self.assertFalse(report['live_ready']); self.assertFalse(report['inference'])

    def test_successful_controls_preserve_all_mac_denial_assertions(self):
        report = self.simulated_probe()
        self.assertEqual(report['platform_sandbox_state'], 'verified')
        self.assertTrue(report['executor_process_positive_read'])
        self.assertTrue(report['same_uid_process_auth_readable'])
        self.assertEqual(report['explicit_sandbox_denials'], [True]*5)
        self.assertTrue(report['approved_write']); self.assertTrue(report['unapproved_write_denied'])
        self.assertFalse(report['live_ready'])

    def test_missing_write_control_or_failed_denials_never_verify_isolation(self):
        missing = self.simulated_probe(write_available=False)
        self.assertEqual(missing['platform_sandbox_state'], 'unavailable')
        self.assertIsNone(missing['explicit_sandbox_denials'])
        leaked = self.simulated_probe(leaked=True)
        self.assertEqual(leaked['platform_sandbox_state'], 'failed-denial')
        self.assertNotEqual(leaked['explicit_sandbox_denials'], [True]*5)
        self.assertFalse(leaked['unapproved_write_denied'])
        self.assertFalse(leaked['live_ready'])


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
        self.assertTrue(self.report['same_uid_subprocess_positive_read'])
        self.assertTrue(self.report['same_uid_subprocess_auth_readable'])
        self.assertTrue(self.report['omitted_sandbox_reads_controller_sentinel'])
        self.assertTrue(self.report['unknown_rpc_rejected'])
        self.assertFalse(self.report['inference'])
        self.assertFalse(self.report['live_ready'])

    def test_real_executor_process_requires_positive_control(self):
        if self.report['executor_process_state'] == 'unavailable':
            self.assertIsNone(self.report['same_uid_process_auth_readable'])
            self.assertFalse(self.report['live_ready'])
            return  # Explicit missing execution evidence, not a successful denial.
        self.assertTrue(self.report['executor_process_positive_read'])
        self.assertEqual(self.report['executor_process_state'], 'observed-readable')
        self.assertTrue(self.report['same_uid_process_auth_readable'])

    def test_real_platform_result_never_claims_denial_without_positive_controls(self):
        if self.report['platform_sandbox_state'] != 'verified':
            self.assertEqual(self.report['platform_sandbox_state'], 'unavailable')
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
