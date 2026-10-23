"""Offline only: fake API bytes and protected temporary ledgers; no real keys."""
from concurrent.futures import ProcessPoolExecutor
import copy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from src import api_controller as c, api_tools as tools
from src.api_budget import Budget, NANO
from src import orchestration_evidence as e
from test_grant_broker import Fixture


def response(**changes):
    r = dict(id='resp_synthetic', object='response', model=c.MODEL, status='completed', error=None,
        output=[dict(type='message', role='assistant', content=[dict(type='output_text', text='OK', annotations=[])])],
        usage=dict(input_tokens=20, output_tokens=10, total_tokens=30,
                   input_tokens_details=dict(cached_tokens=5), output_tokens_details=dict(reasoning_tokens=3)))
    r.update(changes)
    return e.canonical(r).encode()


class Fake:
    synthetic = True
    def __init__(self, raw=None, error=None, callback=lambda:None):
        self.raw = response() if raw is None else raw
        self.error, self.callback, self.calls = error, callback, 0
    def send(self, body):
        self.calls += 1
        self.body = e.decode(body)
        self.callback()
        if self.error: raise self.error
        return self.raw


def race(path, ident):
    try: Budget(path).reserve(ident, 'a'*64, 100); return True
    except ValueError: return False


def crash_reserve(path):
    Budget(path).reserve('a'*32, 'a'*64, 100)
    os._exit(23)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()/'budget.sqlite'
        self.b = Budget(self.path); self.b.initialize()

    def test_atomic_process_race(self):
        with ProcessPoolExecutor(4, mp_context=multiprocessing.get_context('spawn')) as pool:
            results = list(pool.map(race, [str(self.path)]*8, [f'{i:032x}' for i in range(8)]))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.b.status()['unresolved_requests'], 1)

    def test_crash_restart_does_not_reset(self):
        p = multiprocessing.get_context('spawn').Process(target=crash_reserve, args=(str(self.path),))
        p.start(); p.join(10)
        self.assertEqual(p.exitcode, 23)
        self.assertEqual(Budget(self.path).status()['unresolved_nano_usd'], 100)
        with self.assertRaises(FileExistsError): self.b.initialize()
        with self.assertRaises(ValueError): self.b.reserve('a'*32, 'a'*64, 100)

    def test_daily_and_lifetime_ceiling(self):
        self.b.reserve('a'*32, 'a'*64, 10*NANO)
        self.b.settle('a'*32, 10*NANO, dict(status='completed'))
        with self.assertRaisesRegex(ValueError, 'Budget exhausted'): self.b.reserve('b'*32, 'b'*64, 1)
        with self.assertRaises(ValueError): Budget(self.path, daily=11*NANO)
        other = self.path.parent/'lifetime.sqlite'
        b = Budget(other, daily=10*NANO, lifetime=10*NANO, clock=lambda:1780000000); b.initialize()
        b.reserve('a'*32, 'a'*64, 10*NANO); b.settle('a'*32, 10*NANO, {})
        b.clock = lambda:1780086400
        self.assertEqual(b.status()['daily_encumbered_nano_usd'], 0)
        with self.assertRaises(ValueError): b.reserve('b'*32, 'b'*64, 1)

    def test_timezone_midnight_hold_and_explicit_reconciliation(self):
        p = self.path.parent/'day.sqlite'
        from datetime import datetime
        from zoneinfo import ZoneInfo
        before = datetime(2026, 11, 1, 23, 59, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
        b = Budget(p, clock=lambda:before); b.initialize()
        b.reserve('a'*32, 'a'*64, 100)
        b.clock = lambda:before+120
        self.assertEqual(b.status()['day'], '2026-11-02')
        self.assertEqual(b.status()['daily_encumbered_nano_usd'], 100)
        with self.assertRaises(ValueError): b.reconcile('a'*32, 101, 'f'*64)
        with self.assertRaises(ValueError): b.reconcile('a'*32, 10, 'missing')
        b.reconcile('a'*32, 10, 'f'*64)
        self.assertEqual(b.status()['lifetime_encumbered_nano_usd'], 10)
        self.assertEqual(b.status()['daily_encumbered_nano_usd'], 0)
        self.assertEqual(b.audit()[-1]['kind'], 'operator-reconciled')

    def test_readonly_commands_no_write_or_reinitialize(self):
        before = self.path.read_bytes()
        self.b.status(); self.b.audit()
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(ValueError): Budget(self.path, timezone='UTC').status()
        with self.assertRaises(Exception): Budget(self.path.parent/'missing').status()

    def test_clock_rollback_and_permissions(self):
        self.b.reserve('a'*32, 'a'*64, 100)
        with self.assertRaises(ValueError): Budget(self.path, clock=lambda:0).status()
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): self.b.status()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.addCleanup(self.f.close)
        self.claim = self.f.claim()
        self.path = self.f.f.root/'api-budget.sqlite'
        self.b = Budget(self.path); self.b.initialize()
        self.fake = Fake()
        self.controller = c.Controller(self.b, self.fake)

    def run_request(self, ident='a'*32, prompt='Investigate approved maze source'):
        return self.controller.synthetic_request(self.f.broker, self.claim, 'mock', ident, prompt)

    def test_success_actual_cached_reasoning_and_duplicate(self):
        result = self.run_request()
        self.assertEqual(result['estimated_cost_nano_usd'], 15*50+5*5+10*400)
        self.assertEqual(result['usage']['reasoning_tokens'], 3)  # Already included in output; no double bill.
        self.assertEqual(self.b.status()['unresolved_requests'], 0)
        self.assertEqual(self.run_request(), result)
        self.assertEqual(self.fake.calls, 1)
        self.assertFalse(self.fake.body['store'])
        self.assertEqual(self.fake.body['tools'], [])
        with self.assertRaises(ValueError): self.run_request(prompt='changed prompt')

    def test_errors_and_ambiguous_no_retries(self):
        for error in [c.APIUnavailable('authentication'), c.APIUnavailable('rate-limit-or-exhaustion'),
                      c.APIUnavailable('api-error'), TimeoutError(), ConnectionError()]:
            with self.subTest(error=type(error)):
                # Each case has a distinct explicitly initialized test ledger.
                p = self.path.parent/('error-'+str(self.fake.calls)+'.sqlite')
                b = Budget(p); b.initialize()
                fake = Fake(error=error); self.controller = c.Controller(b, fake)
                with self.assertRaises(Exception): self.run_request()
                with self.assertRaises(ValueError): self.run_request()
                self.assertEqual(fake.calls, 1)
                self.assertEqual(Budget(p).status()['unresolved_requests'], 1)
                self.fake.calls += 1

    def test_incomplete_is_billed_and_not_retried(self):
        self.fake.raw = response(status='incomplete', incomplete_details=dict(reason='max_output_tokens'))
        r = self.run_request()
        self.assertEqual(r['status'], 'incomplete'); self.assertFalse(r['retry'])
        self.assertGreater(r['estimated_cost_nano_usd'], 0)

    def test_stop_expiry_source_change_and_principal(self):
        with self.assertRaises(ValueError): self.controller.synthetic_request(
            self.f.broker, self.claim, 'other', 'a'*32, 'hello')
        original = self.claim.copy(); self.claim['generation'] += 1
        with self.assertRaises(ValueError): self.run_request()
        self.claim = original
        self.f.broker.clock = lambda:self.claim['deadline']
        with self.assertRaises(ValueError): self.run_request()
        self.f.broker.clock = lambda:self.f.f.now
        # Trusted source freshness check, not worker-supplied revision.
        source = Path(self.f.controller.config['repositories'][self.f.controller.config['catalog']['tasks']['task-0']['repo']]['source'])
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@local', 'commit', '--allow-empty', '-qm', 'changed source'], check=True)
        with self.assertRaises(ValueError): self.run_request()
        from src.concurrency_coordinator import stopped
        self.assertFalse(stopped(self.f.broker.c))
        with patch('src.grant_broker.stopped', return_value=True):
            with self.assertRaises(ValueError): self.run_request()
        self.assertEqual(self.fake.calls, 0)
        self.assertEqual(self.b.status()['unresolved_requests'], 0)

    def test_stop_during_inference_bills_without_delivery(self):
        self.fake.callback = lambda:setattr(self.f.broker, 'clock', lambda:self.claim['deadline'])
        with self.assertRaises(ValueError): self.run_request()
        self.assertEqual(self.b.status()['unresolved_requests'], 0)
        self.assertGreater(self.b.status()['lifetime_encumbered_nano_usd'], 0)

    def test_hostile_unexpected_fields_invalid_usage_keep_hold(self):
        bad = [response(output=[dict(type='function_call', name='shell', arguments='rm -rf /')]),
               response(unknown='injected'), response(status='failed'), response(model='unreviewed'),
               b'{"object":"response","object":"response"}', b'NaN', b'[]', b'not json',
               response(usage={}), response(tools=[dict(type='web_search')]),
               response(store=True), b'x'*(c.MAX_RESPONSE+1)]
        for i, raw in enumerate(bad):
            with self.subTest(index=i):
                b = Budget(self.path.parent/f'bad-{i}.sqlite'); b.initialize()
                self.controller = c.Controller(b, Fake(raw))
                with self.assertRaises((ValueError, TypeError)): self.run_request()
                self.assertEqual(b.status()['unresolved_requests'], 1)

    def test_model_text_never_in_receipt_or_audit(self):
        marker = 'SYNTHETIC_SECRET_NEVER_A_REAL_KEY'
        self.fake.raw = response(output=[dict(type='message', role='assistant',
            content=[dict(type='output_text', text=marker, annotations=[])])], metadata={'attack':marker})
        self.assertNotIn(marker, e.canonical(self.run_request()))
        self.assertNotIn(marker, e.canonical(self.b.audit()))
        self.assertNotIn(marker.encode(), self.path.read_bytes())

    def test_live_transport_and_connectivity_default_blocked_before_credentials(self):
        with patch.object(c.ResponsesTransport, 'send', side_effect=AssertionError('real API')):
            self.controller = c.Controller(self.b, c.ResponsesTransport('/never/read/key'))
            with self.assertRaises(ValueError): self.run_request()
            with self.assertRaises(ValueError): self.controller.connectivity()
        self.assertFalse(c.readiness()['live_coding'])
        self.assertEqual(self.b.status()['unresolved_requests'], 0)

    def test_request_and_price_bounds(self):
        for prompt in ['', 'x'*2049]:
            with self.assertRaises(ValueError): c.payload(prompt)
        for output in [True, 0, 65, -1]:
            with self.assertRaises(ValueError): c.payload('hello', output)
        for p in [dict(c.DEFAULT_PRICING, model='arbitrary'), dict(c.DEFAULT_PRICING, output_nano_usd_per_token=0), {}]:
            with self.assertRaises(ValueError): c.pricing(p)
        self.assertGreaterEqual(c.maximum_charge(c.DEFAULT_PRICING, 64), c.CONTEXT*50)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.key = Path(self.temp.name).resolve()/'synthetic-key'
        self.marker = 'SYNTHETIC_NOT_A_REAL_CREDENTIAL'
        self.key.write_text(self.marker); self.key.chmod(0o600)

    def child(self, reply=None, status=200, error=None):
        from unittest.mock import Mock
        pipe, client, result = Mock(), Mock(), Mock()
        result.status = status; result.read.return_value = response() if reply is None else reply
        client.getresponse.return_value = result
        if error: client.request.side_effect = error
        with patch('src.api_controller.http.client.HTTPSConnection', return_value=client) as constructor:
            c._http_child(pipe, str(self.key), e.canonical(c.payload('hello')).encode())
        return pipe, client, constructor

    def test_documented_endpoint_no_retry_and_key_only_header(self):
        pipe, client, constructor = self.child()
        self.assertEqual(pipe.send.call_args.args[0][0], 'ok')
        self.assertEqual(constructor.call_args.args, ('api.openai.com',))
        self.assertEqual(client.request.call_args.args, ('POST', '/v1/responses'))
        self.assertEqual(client.request.call_args.kwargs['headers']['Authorization'], 'Bearer '+self.marker)
        self.assertEqual(client.request.call_count, 1)
        self.assertNotIn(self.marker, str(pipe.send.call_args))
        client.close.assert_called_once()

    def test_http_auth_rate_exhaustion_errors_no_body_exposure(self):
        for status, category in [(401,'authentication'), (403,'permission_denied'), (400,'request_rejected'), (404,'model_or_endpoint_not_found'),
                                 (429,'rate_limit_or_exhaustion'), (500,'provider_error'), (302,'redirect_rejected')]:
            with self.subTest(status=status):
                pipe, client, _ = self.child(reply=self.marker.encode(), status=status)
                self.assertEqual(pipe.send.call_args.args[0], ('error', c.diagnostic(category, 'response_headers', 'response_received', status)))
                self.assertEqual(client.request.call_count, 1)

    def test_exception_echo_and_oversize_sanitized(self):
        for raw, error in [(self.marker.encode(), None), (b'x'*(c.MAX_RESPONSE+1), None),
                           (b'', RuntimeError(self.marker))]:
            pipe, _, _ = self.child(raw, error=error)
            self.assertEqual(pipe.send.call_args.args[0][0], 'error')
            self.assertIn(pipe.send.call_args.args[0][1]['category'], {'credential_echo','response_too_large','transport_failure'})
            self.assertNotIn(self.marker, str(pipe.send.call_args))

    def test_private_file_required_before_network(self):
        self.key.chmod(0o644)
        pipe, client, constructor = self.child()
        constructor.assert_not_called()
        self.assertEqual(pipe.send.call_args.args[0][0], 'error')

    def test_whole_request_timeout_terminates_trusted_helper(self):
        from unittest.mock import Mock
        context, receiver, sender, process = Mock(), Mock(), Mock(), Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = process
        receiver.poll.return_value = False
        process.pid = 10; process.is_alive.return_value = True
        with patch('src.api_controller.multiprocessing.get_context', return_value=context):
            with self.assertRaises(c.APIUnavailable): c.ResponsesTransport(str(self.key)).send(e.canonical(c.payload('hello')).encode())
        receiver.poll.assert_called_once_with(c.DEADLINE)
        process.terminate.assert_called_once(); process.kill.assert_called_once()
        self.assertEqual(process.start.call_count, 1)

    def test_malformed_credentials_fail_before_connect_without_echo(self):
        for data in (b'', b'\xff', b' key', b'key ', b'key\nsecond', b'key\x00', b'x'*513):
            with self.subTest(data_length=len(data)):
                self.key.write_bytes(data)
                pipe, client, constructor = self.child()
                constructor.assert_not_called()
                self.assertEqual(pipe.send.call_args.args[0], ('error', c.diagnostic(
                    'credential_format', 'credential', 'not_attempted')))
                self.assertNotIn(self.marker, str(pipe.send.call_args))

    def test_supported_request_contract_and_minimum_output_limit(self):
        body = c.payload('Reply with OK.', 16)
        c.validate_request(e.canonical(body).encode())
        self.assertEqual(body['reasoning'], {'effort':'minimal'})
        self.assertFalse(body['store']); self.assertEqual(body['tools'], [])
        for invalid in [dict(body, temperature=0), dict(body, max_output_tokens=15),
                        dict(body, reasoning={'effort':'none'}), dict(body, stream=True),
                        dict(body, tools=[{'type':'web_search'}])]:
            with self.assertRaises(c.APIUnavailable) as ctx:
                c.ResponsesTransport(str(self.key)).send(e.canonical(invalid).encode())
            self.assertEqual(ctx.exception.diagnostic['category'], 'local_request_invalid')
            self.assertEqual(ctx.exception.diagnostic['dispatch'], 'not_attempted')

    def test_http_unsupported_parameter_only_exports_reviewed_fields(self):
        for parameter, expected in [('parallel_tool_calls','parallel_tool_calls'), (self.marker,None)]:
            raw = e.canonical(dict(error=dict(code='unsupported_parameter', param=parameter,
                message='Authorization Bearer '+self.marker))).encode()
            pipe, client, _ = self.child(raw, status=400)
            d = pipe.send.call_args.args[0][1]
            self.assertEqual(d, c.diagnostic('unsupported_parameter','response_headers',
                                            'response_received',400,expected))
            self.assertNotIn(self.marker, e.canonical(d))
            self.assertEqual(client.request.call_count, 1)

    def test_http_status_survives_unreadable_error_body(self):
        from unittest.mock import Mock
        response = Mock(status=400)
        response.read.side_effect = TimeoutError(self.marker)
        d = c._http_error(response)
        self.assertEqual(d['http_status'], 400)
        self.assertEqual(d['category'], 'request_rejected')
        self.assertNotIn(self.marker, e.canonical(d))

    def test_connect_request_and_read_failures_have_distinct_dispatch_evidence(self):
        from unittest.mock import Mock
        import ssl
        cases = [('connect', ConnectionRefusedError(self.marker), 'connect_failed', 'not_attempted', None),
            ('connect', TimeoutError(self.marker), 'connect_timeout', 'not_attempted', None),
            ('connect', ssl.SSLCertVerificationError(self.marker), 'tls_verification_failed', 'not_attempted', None),
            ('request', ConnectionResetError(self.marker), 'transport_failure', 'may_have_been_sent', None),
            ('getresponse', TimeoutError(self.marker), 'transport_timeout', 'may_have_been_sent', None),
            ('read', TimeoutError(self.marker), 'transport_timeout', 'response_received', 200)]
        for phase, error, category, dispatch, status in cases:
            with self.subTest(phase=phase, category=category):
                pipe, client, response = Mock(), Mock(), Mock(status=200)
                client.getresponse.return_value = response
                target = response.read if phase == 'read' else getattr(client, phase)
                target.side_effect = error
                with patch('src.api_controller.http.client.HTTPSConnection', return_value=client):
                    c._http_child(pipe, str(self.key), e.canonical(c.payload('hello')).encode())
                d = pipe.send.call_args.args[0][1]
                self.assertEqual((d['category'], d['dispatch'], d['http_status']), (category,dispatch,status))
                self.assertNotIn(self.marker, e.canonical(d))
                if phase == 'connect': client.request.assert_not_called()
                else: self.assertEqual(client.request.call_count,1)

    def test_broken_diagnostic_pipe_never_propagates_sensitive_exception_context(self):
        from unittest.mock import Mock
        pipe, client = Mock(), Mock()
        client.request.side_effect = RuntimeError(self.marker)
        pipe.send.side_effect = BrokenPipeError(self.marker)
        pipe.close.side_effect = OSError(self.marker)
        with patch('src.api_controller.http.client.HTTPSConnection', return_value=client):
            # A broken pipe cannot turn the suppressed original exception into a child traceback.
            c._http_child(pipe, str(self.key), e.canonical(c.payload('hello')).encode())
        client.close.assert_called_once()

    def test_local_helper_construction_failure_is_proven_pre_dispatch(self):
        with patch('src.api_controller.multiprocessing.get_context', side_effect=OSError(self.marker)):
            with self.assertRaises(c.APIUnavailable) as ctx:
                c.ResponsesTransport(str(self.key)).send(e.canonical(c.payload('hello')).encode())
        self.assertEqual(ctx.exception.diagnostic['dispatch'], 'not_attempted')
        self.assertEqual(ctx.exception.diagnostic['category'], 'helper_start_failed')

    def test_helper_start_failure_and_lost_helper_are_not_equated(self):
        from unittest.mock import Mock
        for started in [False, True]:
            context, receiver, sender, process = Mock(), Mock(), Mock(), Mock()
            context.Pipe.return_value = (receiver, sender); context.Process.return_value = process
            if started: receiver.recv.side_effect = EOFError(self.marker)
            else: process.start.side_effect = OSError(self.marker)
            with patch('src.api_controller.multiprocessing.get_context', return_value=context):
                with self.assertRaises(c.APIUnavailable) as ctx:
                    c.ResponsesTransport(str(self.key)).send(e.canonical(c.payload('hello')).encode())
            self.assertEqual(ctx.exception.diagnostic['dispatch'], 'may_have_been_sent')
            self.assertNotIn(self.marker, str(ctx.exception))

    def test_untrusted_helper_diagnostic_fields_cannot_escape(self):
        from unittest.mock import Mock
        context, receiver, sender, process = Mock(), Mock(), Mock(), Mock()
        context.Pipe.return_value = (receiver, sender); context.Process.return_value = process
        receiver.recv.return_value = ('error', dict(category=self.marker, phase='helper',
            dispatch='not_attempted', http_status=401, parameter=None))
        with patch('src.api_controller.multiprocessing.get_context', return_value=context):
            with self.assertRaises(c.APIUnavailable) as ctx:
                c.ResponsesTransport(str(self.key)).send(e.canonical(c.payload('hello')).encode())
        self.assertEqual(ctx.exception.diagnostic['category'], 'helper_protocol_invalid')
        self.assertNotIn(self.marker, str(ctx.exception))


class DiagnosticAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.b = Budget(Path(self.temp.name).resolve()/'budget.sqlite'); self.b.initialize()

    def test_diagnostic_audit_never_changes_reservation_or_releases_hold(self):
        ident = '33f477e596b0473b9c020ef32d69a505'
        # This is a disposable offline fixture, never the operator's ledger.
        self.b.reserve(ident, 'a'*64, 20_006_400)
        with self.b.tx() as db: before = tuple(db.execute('SELECT * FROM requests').fetchone())
        self.b.record_failure(ident, c.diagnostic('request_rejected','response_headers','response_received',400))
        with self.b.tx() as db: after = tuple(db.execute('SELECT * FROM requests').fetchone())
        self.assertEqual(before, after)
        self.assertEqual(self.b.status()['unresolved_nano_usd'], 20_006_400)
        self.assertEqual(Budget(self.b.path).status()['unresolved_requests'], 1)
        with self.assertRaises(ValueError): self.b.reserve('b'*32, 'b'*64, 1)
        self.assertEqual([r['kind'] for r in self.b.audit()], ['reserved','request_failed_hold_retained'])

    def test_controller_classifies_validation_and_http_errors_without_settlement(self):
        for i, (fake, category) in enumerate([
                (Fake(raw=b'not JSON'), 'response_json_invalid'),
                (Fake(raw=response(unexpected='sensitive')), 'response_schema_invalid'),
                (Fake(error=c.APIUnavailable('unsupported_parameter','response_headers','response_received',400)),
                 'unsupported_parameter')]):
            b = Budget(self.b.path.parent/f'case-{i}.sqlite'); b.initialize()
            controller = c.Controller(b, fake)
            with self.assertRaises(c.APIUnavailable) as ctx:
                controller._request('a'*32, c.payload('hello'), {'purpose':'offline'}, lambda:None)
            self.assertEqual(ctx.exception.diagnostic['category'], category)
            self.assertEqual(ctx.exception.request_id, 'a'*32)
            self.assertTrue(ctx.exception.audit_recorded)
            self.assertEqual(b.status()['unresolved_requests'], 1)
            self.assertEqual(b.audit()[-1]['kind'], 'request_failed_hold_retained')
            with self.assertRaises(ValueError):
                controller._request('a'*32, c.payload('hello'), {'purpose':'offline'}, lambda:None)
            self.assertEqual(fake.calls, 1)

    def test_documented_reasoning_metadata_is_discarded_without_weakening_usage(self):
        marker = 'SYNTHETIC_OPAQUE_CIPHERTEXT'
        raw = response(output=[dict(id='rs_synthetic', type='reasoning', summary=[], content=[],
                                    encrypted_content=marker, status='completed')])
        result = c.receipt(raw, c.payload('hello'), c.DEFAULT_PRICING)
        self.assertEqual(result['usage']['reasoning_tokens'],3)
        self.assertNotIn(marker, e.canonical(result))
        for unexpected in [dict(type='reasoning', summary=[], content=[{'type':'reasoning_text','text':marker}]),
                           dict(type='reasoning', summary=[], encrypted_content={'attack':marker}),
                           dict(type='function_call', name='shell')]:
            with self.assertRaises(c.APIUnavailable):
                c.receipt(response(output=[unexpected]),c.payload('hello'),c.DEFAULT_PRICING)

    def test_existing_hold_blocks_connectivity_before_any_transport_call(self):
        self.b.reserve('33f477e596b0473b9c020ef32d69a505', 'a'*64, 20_006_400)
        before = self.b.path.read_bytes()
        controller = c.Controller(self.b, c.ResponsesTransport('/never/read/key'))
        with patch.object(c.ResponsesTransport, 'send', side_effect=AssertionError('Unauthorized retry')) as send:
            with self.assertRaises(ValueError): controller.connectivity(operator_enabled=True)
        send.assert_not_called()
        self.assertEqual(before, self.b.path.read_bytes())

    def test_cli_failure_receipt_exports_diagnostic_without_exception_strings(self):
        from contextlib import redirect_stdout
        import io
        config = json.loads(Path('config/api-controller.example.json').read_text())
        config['budget_file'] = str(self.b.path)
        config['credential_file'] = '/never/read/key'
        config['connectivity_enabled'] = True
        path = self.b.path.parent/'config.json'; path.write_text(e.canonical(config)); path.chmod(0o600)
        error = c.APIUnavailable('authentication','response_headers','response_received',401)
        error.request_id = 'a'*32
        out = io.StringIO()
        with patch('sys.argv', ['api_controller','connectivity','--operator-connectivity','--config',str(path)]), \
             patch.object(c.Controller, 'connectivity', side_effect=error), redirect_stdout(out):
            self.assertEqual(c.main(),1)
        result = json.loads(out.getvalue())
        self.assertEqual(result['diagnostic']['http_status'],401)
        self.assertFalse(result['retry']); self.assertTrue(result['hold_retained'])


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.receiver = tools.SyntheticReceiver({'solver.js':'a'*64})

    def call(self, name='propose_file', args=None):
        return e.canonical(dict(type='function_call', name=name,
            arguments=e.canonical(dict(path='solver.js', content='safe') if args is None else args))).encode()

    def test_synthetic_manifest_bound_proposal(self):
        result = self.receiver.receive(self.call(), source_manifest=self.receiver.manifest)
        self.assertFalse(result['executed']); self.assertTrue(result['synthetic'])
        with self.assertRaises(ValueError): self.receiver.receive(self.call(), source_manifest='b'*64)

    def test_hostile_tools_paths_and_extra_arguments(self):
        for raw in [self.call('shell'), self.call('read_controller'), self.call('mint_grant'),
                    self.call(args=dict(path='/etc/passwd', content='x')),
                    self.call(args=dict(path='../solver.js', content='x')),
                    self.call(args=dict(path='solver.js', content='x', command='evil')),
                    self.call(args=dict(path='solver.js', content=10)), b'{}', b'{invalid',
                    self.call(args=dict(path='solver.js', content='x'*8193))]:
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                self.receiver.receive(raw, source_manifest=self.receiver.manifest)
        for args in ({}, dict(isolated=True), dict(receipt={'verified':True})):
            with self.assertRaises(ValueError): tools.executable_receiver(**args)

    def test_invalid_function_json_and_duplicates(self):
        for args in ['{invalid', '{"path":"solver.js","path":"solver.js","content":"x"}', '[]']:
            raw = e.canonical(dict(type='function_call', name='propose_file', arguments=args)).encode()
            with self.assertRaises(ValueError): self.receiver.receive(raw, source_manifest=self.receiver.manifest)


if __name__ == '__main__': unittest.main()
