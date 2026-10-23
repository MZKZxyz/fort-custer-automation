"""Bounded Responses API controller. Text-only connectivity, synthetic broker tests.

No worker endpoint, model text persistence, hosted tool, shell, or live coding.
Supported public REST API: POST https://api.openai.com/v1/responses.
"""
import argparse
import http.client
import multiprocessing
import os
from pathlib import Path
import ssl
import stat
import uuid

from src import orchestration_evidence as e
from src.api_budget import Budget
from src.api_diagnostics import APIUnavailable, diagnostic, validate as validate_diagnostic, PARAMETERS

MODEL = 'gpt-5-nano-2025-08-07'
CONTEXT = 400_000  # Reserve full model context: no approximate tokenizer assumptions.
MAX_INPUT_BYTES = 2048
MAX_OUTPUT = 64
MAX_RESPONSE = 256*1024
DEADLINE = 20
DEFAULT_PRICING = dict(version='openai-standard-usd-2025-08-07-review-2026-10-23', model=MODEL,
    input_nano_usd_per_token=50, cached_nano_usd_per_token=5, output_nano_usd_per_token=400)


def pricing(value):
    e.require(isinstance(value, dict) and set(value) == set(DEFAULT_PRICING) and
              value['model'] == MODEL and isinstance(value['version'], str) and
              0 < len(value['version']) <= 100 and all(type(value[k]) is int and 0 < value[k] <= 1_000_000_000
              for k in DEFAULT_PRICING if k.endswith('_token')) and
              value['cached_nano_usd_per_token'] <= value['input_nano_usd_per_token'], 'Unreviewed pricing')
    return dict(value)


def payload(prompt, output=MAX_OUTPUT):
    e.require(isinstance(prompt, str) and 0 < len(prompt.encode()) <= MAX_INPUT_BYTES and
              type(output) is int and 16 <= output <= MAX_OUTPUT, 'Request bound exceeded')
    return dict(model=MODEL, input=prompt, max_output_tokens=output, store=False,
                background=False, stream=False, tools=[], tool_choice='none',
                parallel_tool_calls=False, truncation='disabled', service_tier='default',
                reasoning=dict(effort='minimal'), prompt_cache_retention='in_memory')


def maximum_charge(p, output):
    # Overreserve uncached input at full context, even though prompt is tiny.
    return CONTEXT*p['input_nano_usd_per_token']+output*p['output_nano_usd_per_token']


def validate_request(body):
    """Pinned text-only contract, checked offline before any connection is opened."""
    try:
        e.require(type(body) is bytes and len(body) <= 16384, 'Request ceiling')
        r = e.decode(body)
        e.require(isinstance(r, dict) and e.canonical(r) == e.canonical(payload(r.get('input'), r.get('max_output_tokens'))),
                  'Unsupported request configuration')
    except Exception:
        raise APIUnavailable('local_request_invalid', 'local_request', 'not_attempted') from None


def _http_error(response):
    status = response.status
    category = {400:'request_rejected', 401:'authentication', 403:'permission_denied',
                404:'model_or_endpoint_not_found', 429:'rate_limit_or_exhaustion'}.get(status,
                'provider_error' if 500 <= status <= 599 else
                'redirect_rejected' if 300 <= status <= 399 else 'http_error')
    parameter = None
    # Only parse a bounded error object for finite code/parameter classifications.
    # Headers, messages, arbitrary codes and raw body never leave this helper.
    try:
        raw = response.read(8193)
        error = e.decode(raw).get('error') if len(raw) <= 8192 else None
        if status == 400 and isinstance(error, dict) and error.get('code') in (
                'unsupported_parameter', 'unknown_parameter', 'unsupported_value'):
            category = 'unsupported_parameter'
            parameter = error.get('param') if error.get('param') in PARAMETERS else None
    except Exception:
        pass  # The observed HTTP status remains useful even if its body is unreadable.
    return diagnostic(category, 'response_headers', 'response_received', status, parameter)


def _http_child(connection, credential_file, body):
    """Trusted controller helper only. Key never appears in argv/environment/results."""
    key, client, status = None, None, None
    phase, dispatch = 'local_request', 'not_attempted'
    def send(message):
        try: connection.send(message)
        except BaseException: pass  # Never leak an active sensitive exception via a broken IPC pipe.
    try:
        validate_request(body)
        phase = 'credential'
        try:
            path = e.regular(credential_file)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                e.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                          info.st_nlink == 1 and not info.st_mode & 0o077, 'Private credential required')
                data = os.read(fd, 513)
            finally: os.close(fd)
        except Exception:
            raise APIUnavailable('credential_unreadable', phase, dispatch) from None
        try:
            e.require(0 < len(data) <= 512, 'Credential bound')
            decoded = data.decode('ascii')
            key = decoded.removesuffix('\r\n').removesuffix('\n')
            e.require(key and all(33 <= ord(c) <= 126 for c in key), 'Credential format')
        except Exception:
            raise APIUnavailable('credential_format', phase, dispatch) from None
        phase = 'connect'
        # Connect/TLS completes before we attempt to send a POST. No redirects,
        # retries, proxy/env URL overrides or header/exception logging.
        client = http.client.HTTPSConnection('api.openai.com', timeout=10,
                                             context=ssl.create_default_context())
        client.connect()
        client.auto_open = 0  # A broken connection must never trigger an implicit reconnect.
        phase, dispatch = 'request', 'may_have_been_sent'
        client.request('POST', '/v1/responses', body=body,
            headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
        phase = 'response_headers'
        response = client.getresponse()
        status = response.status
        e.require(type(status) is int and 100 <= status <= 599, 'Invalid status')
        dispatch = 'response_received'
        if status != 200:
            send(('error', _http_error(response)))
            return
        phase = 'response_body'
        raw = response.read(MAX_RESPONSE+1)
        if len(raw) > MAX_RESPONSE:
            raise APIUnavailable('response_too_large', phase, dispatch, status)
        if key.encode() in raw:
            raise APIUnavailable('credential_echo', phase, dispatch, status)
        send(('ok', raw))
    except APIUnavailable as exc:
        send(('error', exc.diagnostic))
    except ssl.SSLCertVerificationError:
        send(('error', diagnostic('tls_verification_failed', phase, dispatch, status)))
    except TimeoutError:
        send(('error', diagnostic('connect_timeout' if phase == 'connect' else
                                            'transport_timeout', phase, dispatch, status)))
    except BaseException:
        send(('error', diagnostic('connect_failed' if phase == 'connect' else
                                            'transport_failure', phase, dispatch, status)))
    finally:
        key = None
        if client is not None:
            try: client.close()
            except Exception: pass
        try: connection.close()
        except BaseException: pass


class ResponsesTransport:
    """Single attempt with a whole-helper wall deadline, including DNS/read/write."""
    synthetic = False

    def __init__(self, credential_file):
        path = Path(credential_file).expanduser().absolute()
        e.require(not path.resolve().is_relative_to(Path(__file__).resolve().parents[1]),
                  'External credential path required')
        self.credential_file = str(path)

    def send(self, body):
        validate_request(body)
        process = receiver = sender = None
        started = start_attempted = False
        try:
            context = multiprocessing.get_context('spawn')
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=_http_child, args=(sender, self.credential_file, body), daemon=True)
            start_attempted = True
            process.start(); started = True; sender.close()
            if not receiver.poll(DEADLINE):
                raise APIUnavailable('helper_deadline')  # Lost phase evidence is always ambiguous.
            message = receiver.recv()
            if not isinstance(message, tuple) or len(message) != 2:
                raise APIUnavailable('helper_protocol_invalid')
            kind, result = message
            if kind == 'error':
                try: d = validate_diagnostic(result)
                except Exception: raise APIUnavailable('helper_protocol_invalid') from None
                raise APIUnavailable(**d)
            if kind != 'ok' or type(result) is not bytes:
                raise APIUnavailable('helper_protocol_invalid')
            return result
        except APIUnavailable:
            raise
        except Exception:
            raise APIUnavailable('helper_disconnected' if started else 'helper_start_failed',
                                 'helper' if started else 'helper_start',
                                 'may_have_been_sent' if start_attempted else 'not_attempted') from None
        finally:
            for pipe in (sender, receiver):
                if pipe is not None:
                    try: pipe.close()
                    except Exception: pass
            if started:
                if process.is_alive(): process.terminate()
                process.join(timeout=1)
                if process.is_alive(): process.kill(); process.join(timeout=1)


def _receipt(raw, request, p):
    e.require(type(raw) is bytes and len(raw) <= MAX_RESPONSE, 'Response size rejected')
    r = e.decode(raw)
    allowed = {'id','object','created_at','status','error','incomplete_details','instructions',
        'max_output_tokens','model','output','parallel_tool_calls','previous_response_id',
        'reasoning','store','temperature','text','tool_choice','tools','top_p','truncation',
        'usage','user','metadata','service_tier','background','max_tool_calls','safety_identifier',
        'prompt_cache_key','prompt_cache_retention','top_logprobs','completed_at','conversation',
        'prompt','prompt_cache_diagnostics','prompt_cache_options','access_programs','moderation'}
    e.require(isinstance(r, dict) and set(r) <= allowed and r.get('object') == 'response' and
              r.get('model') == MODEL and r.get('status') in {'completed','incomplete'} and
              r.get('error') is None and r.get('tools', []) == [] and
              r.get('store', False) is False and r.get('background', False) is False and
              r.get('conversation') is None and r.get('previous_response_id') is None and
              r.get('prompt') is None and r.get('access_programs') is None and
              r.get('moderation') is None and r.get('prompt_cache_options') is None and
              r.get('service_tier', 'default') == 'default',
              'Unexpected response; hold retained')
    u = r.get('usage')
    e.require(isinstance(u, dict) and set(u) == {'input_tokens','output_tokens','total_tokens',
        'input_tokens_details','output_tokens_details'}, 'Invalid usage')
    i, o = u['input_tokens'], u['output_tokens']
    e.require(type(i) is int and type(o) is int and 0 <= i <= CONTEXT and
              0 <= o <= request['max_output_tokens'] and type(u['total_tokens']) is int and
              u['total_tokens'] == i+o, 'Unbounded usage')
    e.require(isinstance(u['input_tokens_details'], dict) and
              set(u['input_tokens_details']) == {'cached_tokens'} and
              isinstance(u['output_tokens_details'], dict) and
              set(u['output_tokens_details']) == {'reasoning_tokens'}, 'Unknown pricing dimension')
    cached, reasoning = u['input_tokens_details']['cached_tokens'], u['output_tokens_details']['reasoning_tokens']
    e.require(type(cached) is int and 0 <= cached <= i and type(reasoning) is int and
              0 <= reasoning <= o, 'Invalid token detail')
    output = r.get('output')
    e.require(isinstance(output, list) and len(output) <= MAX_OUTPUT, 'Invalid output')
    for item in output:
        if isinstance(item, dict) and item.get('type') == 'reasoning':
            e.require(set(item) <= {'id','type','summary','status','content','encrypted_content'} and
                      item.get('summary') == [] and item.get('content') in (None, []) and
                      (item.get('encrypted_content') is None or isinstance(item['encrypted_content'], str)),
                      'Unexpected reasoning content')
            continue
        e.require(isinstance(item, dict) and set(item) <= {'id','type','status','role','content','phase'} and
                  item.get('phase') in (None, 'commentary', 'final_answer') and
                  item.get('type') == 'message' and item.get('role') == 'assistant' and
                  isinstance(item.get('content'), list), 'Executable or unexpected model output rejected')
        for part in item['content']:
            e.require(isinstance(part, dict) and part.get('type') in {'output_text','refusal'} and
                      set(part) <= {'type','text','annotations','logprobs','refusal'} and
                      part.get('annotations', []) == [], 'Unexpected content rejected')
    cost = (i-cached)*p['input_nano_usd_per_token']+cached*p['cached_nano_usd_per_token']+o*p['output_nano_usd_per_token']
    # No raw text, response id, errors, metadata, headers, or function arguments.
    return dict(status=r['status'], usage=dict(input_tokens=i, cached_input_tokens=cached,
        output_tokens=o, reasoning_tokens=reasoning), estimated_cost_nano_usd=cost,
        pricing_version=p['version'], model=MODEL, retry=False, tools_executed=0)


def receipt(raw, request, p):
    try:
        # JSON parse errors are distinct from valid JSON with an unsupported schema.
        e.decode(raw) if type(raw) is bytes and len(raw) <= MAX_RESPONSE else None
    except Exception:
        raise APIUnavailable('response_json_invalid', 'response_validation', 'response_received', 200) from None
    try:
        return _receipt(raw, request, p)
    except Exception:
        raise APIUnavailable('response_schema_invalid', 'response_validation', 'response_received', 200) from None


class Controller:
    def __init__(self, budget, transport, prices=None):
        self.budget, self.transport = budget, transport
        self.prices = pricing(DEFAULT_PRICING if prices is None else prices)

    def _request(self, ident, request, binding, guard):
        guard()
        old = self.budget.reserve(ident, e.digest(dict(binding=binding, request=request, pricing=self.prices)),
                                  maximum_charge(self.prices, request['max_output_tokens']),
                                  provenance=dict(binding=binding, pricing=self.prices,
                                      model_config={k:v for k,v in request.items() if k != 'input'},
                                      prompt_digest=e.digest(request['input'])))
        if old is not None: return old
        guard()  # Failure after reservation intentionally leaves durable hold.
        try:
            raw = self.transport.send(e.canonical(request).encode())
            result = receipt(raw, request, self.prices)
        except Exception as error:
            exc = error if isinstance(error, APIUnavailable) else APIUnavailable('transport_failure')
            exc.request_id = ident
            try:
                self.budget.record_failure(ident, exc.diagnostic)
                exc.audit_recorded = True
            except Exception:
                pass  # Diagnostic-write failure cannot release a hold or trigger another request.
            raise exc from None
        # Reconcile billing even if STOP arrives while inference is in flight.
        self.budget.settle(ident, result['estimated_cost_nano_usd'], result)
        guard()  # Never deliver model output on revoked/expired/source-changed grant.
        return result

    def connectivity(self, *, operator_enabled=False):
        e.require(operator_enabled is True and type(self.transport) is ResponsesTransport,
                  'Explicit operator-only connectivity activation required')
        return self._request(uuid.uuid4().hex, payload('Reply with OK.', 16),
                             dict(purpose='operator-text-only-connectivity'), lambda:None)

    def synthetic_request(self, broker, claim, principal, ident, prompt):
        e.require(getattr(self.transport, 'synthetic', False) is True,
                  'Live task API integration unavailable; synthetic transport required')
        # Trust actual broker state, immutable source/policy, STOP, deadline/fence.
        from src.grant_broker import Broker
        e.require(type(broker) is Broker, 'Trusted broker required')
        def guard():
            with broker.tx() as db:
                row = broker._owned(db, claim, {'claimed'})
                broker._guard(claim); broker._fresh(row['authorization'])
                e.require(claim['worker'] == principal, 'Execution principal mismatch')
                return row['authorization']
        a = guard()
        binding = dict(execution=claim['execution'], claim=e.digest(claim), principal=principal,
            task=a['task'], authorization=e.digest(a), source_manifest=a['source_manifest'],
            prompt=e.digest(prompt), tools=[], receiver='synthetic-only-no-execution')
        return self._request(ident, payload(prompt), binding, guard)


def readiness():
    return dict(schema='api-controller-readiness-v1', live_coding=False, live_workers=0,
        tools_executable=False, connectivity_default=False, local_budget_only=True,
        missing=['live broker admission/migration', 'verified isolated tool and QA receivers',
                 'target host denial/network/resource/watchdog evidence',
                 'separately authorized draft publisher', 'operator pricing and connectivity review'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['readiness','init-budget','status','audit','connectivity','reconcile'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--operator-connectivity', action='store_true')
    parser.add_argument('--request-id')
    parser.add_argument('--actual-nano-usd', type=int)
    parser.add_argument('--evidence-sha256')
    args = parser.parse_args()
    try:
        if args.command == 'readiness': result = readiness()
        else:
            c = e.decode(e.regular(args.config).read_bytes())
            e.require(set(c) == {'schema','connectivity_enabled','credential_file','budget_file',
                'timezone','daily_nano_usd','lifetime_nano_usd','pricing'} and
                c['schema'] == 'responses-controller-v1' and type(c['connectivity_enabled']) is bool,
                'Unreviewed controller configuration')
            p = pricing(c['pricing'])
            key_path = Path(c['credential_file']).expanduser().absolute()
            budget_path = Path(c['budget_file']).expanduser().absolute()
            e.require(key_path != budget_path and not budget_path.resolve().is_relative_to(
                      Path(__file__).resolve().parents[1]), 'External distinct budget/credential paths required')
            budget = Budget(Path(c['budget_file']).expanduser(), timezone=c['timezone'],
                daily=c['daily_nano_usd'], lifetime=c['lifetime_nano_usd'])
            if args.command == 'init-budget': budget.initialize(); result = budget.status()
            elif args.command == 'status': result = budget.status()
            elif args.command == 'audit': result = budget.audit()
            elif args.command == 'reconcile':
                result = budget.reconcile(args.request_id, args.actual_nano_usd, args.evidence_sha256)
            else:
                e.require(c['connectivity_enabled'] and args.operator_connectivity,
                          'Connectivity disabled; explicit operator activation required')
                result = Controller(budget, ResponsesTransport(c['credential_file']), p).connectivity(operator_enabled=True)
        print(e.canonical(result))
        return 0
    except APIUnavailable as exc:
        print(e.canonical(dict(status='blocked-or-unknown', retry=False, hold_retained=True,
            request_id=exc.request_id, diagnostic=exc.diagnostic, audit_recorded=exc.audit_recorded,
            instruction='preserve hold; inspect status/audit and verify billing; no retry authorized')))
        return 1
    except Exception:
        # Never print exception text/traceback from credential/network paths.
        print(e.canonical(dict(status='blocked-or-unknown', retry=False,
                               diagnostic=diagnostic('controller_error', 'controller'),
                               instruction='inspect budget status/audit; preserve unresolved holds')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
