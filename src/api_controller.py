"""Bounded Responses controller with separate observation and coding receivers.

No hosted tool, shell, model-selected path, publication, or automatic retry.
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
from src import api_response_envelope as envelope
from src.api_diagnostics import APIUnavailable, diagnostic, validate as validate_diagnostic, PARAMETERS

MODEL = 'gpt-5-nano-2025-08-07'
CONTEXT = 400_000  # Reserve full model context: no approximate tokenizer assumptions.
MAX_INPUT_BYTES = 2048
MAX_OUTPUT = 64
OBSERVATION_OUTPUT = 512
CONNECTIVITY_OUTPUT = 256
MAX_RESPONSE = 256*1024
DEADLINE = 20
DEFAULT_PRICING = dict(version='openai-standard-usd-2025-08-07-review-2026-10-23', model=MODEL,
    input_nano_usd_per_token=50, cached_nano_usd_per_token=5, output_nano_usd_per_token=400)


def pricing(value):
    from src.coding_api import PRICING
    if value == PRICING:
        return dict(value)
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


def observation_payload(prompt):
    request = payload(prompt)
    request['max_output_tokens'] = OBSERVATION_OUTPUT
    return request


def maximum_charge(p, output):
    from src.coding_api import PRICING, MAXIMUM_CHARGE
    if p == PRICING:
        e.require(output == 4000, 'Coding output profile changed')
        return MAXIMUM_CHARGE
    # Overreserve uncached input at full context, even though prompt is tiny.
    return CONTEXT*p['input_nano_usd_per_token']+output*p['output_nano_usd_per_token']


def connectivity_payload():
    request = payload('Reply with OK.')
    request['max_output_tokens'] = CONNECTIVITY_OUTPUT
    return request


def validate_request(body):
    """Pinned text-only contract, checked offline before any connection is opened."""
    try:
        e.require(type(body) is bytes and len(body) <= 32768, 'Request ceiling')
        r = e.decode(body)
        from src.coding_api import MODEL as CODING_MODEL, payload as coding_payload
        if isinstance(r, dict) and r.get('model') == CODING_MODEL:
            e.require(e.canonical(r) == e.canonical(coding_payload(r.get('input'))),
                      'Unsupported coding request')
            return
        e.require(len(body) <= 16384, 'Legacy request ceiling')
        expected = (observation_payload(r.get('input')) if isinstance(r, dict) and
                    r.get('max_output_tokens') == OBSERVATION_OUTPUT else
                    connectivity_payload() if isinstance(r, dict) and
                    r.get('max_output_tokens') == CONNECTIVITY_OUTPUT else
                    payload(r.get('input'), r.get('max_output_tokens')))
        e.require(isinstance(r, dict) and e.canonical(r) == e.canonical(expected),
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


def _schema(condition, section, rule):
    if not condition:
        raise APIUnavailable('response_schema_invalid', 'response_validation', 'response_received', 200,
                             validation_section=section, validation_rule=rule)


def _fields(value, allowed, section, required=()):
    _schema(isinstance(value, dict), section, 'shape')
    _schema(set(value) <= set(allowed), section, 'unknown_fields')
    _schema(set(required) <= set(value), section, 'shape')


def _tool_usage(value):
    # Exact operator-observed response shape. No tool pricing model or execution
    # authority is inferred from these counters; validated metadata is discarded.
    schema = {
        'image_gen': {
            'input_tokens': None,
            'input_tokens_details': {'image_tokens': None, 'text_tokens': None},
            'output_tokens': None,
            'output_tokens_details': {'image_tokens': None, 'text_tokens': None},
            'total_tokens': None,
        },
        'web_search': {'num_requests': None},
    }
    def check(node, expected):
        if expected is None:
            _schema(type(node) is int, 'tool_usage','counter_type')
            _schema(node >= 0, 'tool_usage','counter_bounds')
            _schema(node == 0, 'tool_usage','activity_disabled')
            return
        _schema(isinstance(node, dict), 'tool_usage','shape')
        _schema(set(node) <= set(expected), 'tool_usage','unknown_dimension')
        _schema(set(node) == set(expected), 'tool_usage','shape')
        for key, child in expected.items():
            check(node[key], child)
    check(value, schema)


def _metadata(r, request):
    # These are discarded response echoes, never configuration or authority.
    _schema(not any(name in r for name in envelope.REQUEST_ONLY_FIELDS),
            'metadata','unsupported_configuration')
    if 'tool_usage' in r:
        _tool_usage(r['tool_usage'])
    for name in envelope.DISCARDED_TEXT_FIELDS:
        _schema(r.get(name) is None or isinstance(r[name], str), 'metadata','field_type')
    for name in ('id','user','safety_identifier','prompt_cache_key'):
        if name in r:
            _schema(r[name] is None and name != 'id' or isinstance(r[name], str), 'metadata','field_type')
    for name in ('created_at','completed_at','temperature','top_p'):
        if name == 'created_at' and name in r or r.get(name) is not None:
            _schema(e.finite(r[name]) and r[name] >= 0, 'metadata','field_type')
    for name in ('frequency_penalty','presence_penalty'):
        if name in r:
            _schema(e.finite(r[name]), 'metadata','field_type')
    for name in ('max_output_tokens','max_tool_calls','top_logprobs'):
        if r.get(name) is not None:
            _schema(type(r[name]) is int and r[name] >= 0, 'metadata','field_type')
    if r.get('max_output_tokens') is not None:
        _schema(r['max_output_tokens'] == request['max_output_tokens'], 'metadata','unsupported_configuration')
    for name in ('tools','tool_choice','parallel_tool_calls','store'):
        if name in r:
            expected = {'tools': [], 'tool_choice':'none','parallel_tool_calls':False,'store':False}[name]
            _schema(e.canonical(r[name]) == e.canonical(expected), 'metadata','unsupported_configuration')
    _schema(r.get('background') is None or r['background'] is False, 'metadata','unsupported_configuration')
    _schema(r.get('service_tier') in (None,'default'), 'metadata','service_tier')
    from src.coding_api import MODEL as CODING_MODEL, payload as coding_payload
    coding_profile = (request.get('model') == CODING_MODEL and
                      request == coding_payload(request.get('input')))
    _schema(r.get('prompt_cache_retention') is None or
            (request['model'] == MODEL or coding_profile) and
            r['prompt_cache_retention'] == 'in_memory', 'metadata','cache_policy')
    # Nonempty state/access/new-model cache settings require a separate review.
    for name in ('conversation','previous_response_id','prompt','access_programs','moderation'):
        _schema(r.get(name) is None, 'metadata','unsupported_configuration')
    cache_options = r.get('prompt_cache_options')
    _schema(cache_options is None or coding_profile and
            cache_options == {'mode':'implicit', 'ttl':'30m'}, 'metadata','unsupported_configuration')
    _schema(r.get('truncation') in (None,'disabled'), 'metadata','unsupported_configuration')
    meta = r.get('metadata')
    _schema(meta is None or isinstance(meta, dict) and
            all(isinstance(k,str) and isinstance(v,str) for k,v in meta.items()), 'metadata','field_type')
    instructions = r.get('instructions')
    _schema(instructions is None or isinstance(instructions,str) or instructions == [], 'metadata','field_type')
    text = r.get('text')
    if text is not None:
        _schema(isinstance(text,dict) and set(text) <= {'format','verbosity'}, 'metadata','field_type')
        _schema(text.get('format') in (None, {'type':'text'}) and
                text.get('verbosity') in (None,'low','medium','high'), 'metadata','unsupported_configuration')
    reasoning = r.get('reasoning')
    if reasoning is not None:
        _schema(isinstance(reasoning,dict) and set(reasoning) <=
                {'effort','summary','generate_summary','context','mode'}, 'metadata','field_type')
        _schema(reasoning.get('effort') in (None,'minimal','low','medium','high') and
                reasoning.get('summary') in (None,'auto','concise','detailed') and
                reasoning.get('generate_summary') in (None,'auto','concise','detailed') and
                reasoning.get('context') in (None,'auto','current_turn','all_turns') and
                reasoning.get('mode') in (None,'standard'), 'metadata','unsupported_configuration')
    cache = r.get('prompt_cache_diagnostics')
    if cache is not None:
        _schema(isinstance(cache,dict), 'metadata','field_type')
        kind = cache.get('type')
        if kind == 'cache_miss':
            _schema(set(cache) <= {'type','reason','cache_missed_tokens','comparison_reusable_tokens'} and
                cache.get('reason') in ('model_changed','prompt_cache_key_changed','tools_changed',
                    'text_format_changed','reasoning_effort_changed','verbosity_changed','context_compacted',
                    'input_changed','service_tier_changed') and type(cache.get('cache_missed_tokens')) is int and
                cache['cache_missed_tokens'] >= 0 and (cache.get('comparison_reusable_tokens') is None or
                    type(cache['comparison_reusable_tokens']) is int and cache['comparison_reusable_tokens'] >= 0),
                'metadata','field_type')
        else:
            _schema(kind in ('cache_hit','comparison_response_not_found','unavailable') and set(cache) == {'type'},
                    'metadata','field_type')


def _completion(r):
    _schema(r.get('status') in ('completed','incomplete'), 'completion','response_status')
    _schema(r.get('error') is None, 'completion','provider_error')
    details = r.get('incomplete_details')
    if details is not None:
        _schema(isinstance(details,dict) and set(details) <= {'reason'}, 'completion','incomplete_details')
        reason = details.get('reason')
        _schema(reason is None or r['status'] == 'incomplete' and
                reason in ('max_output_tokens','max_messages','content_filter','steered'),
                'completion','incomplete_details')


def _usage(r, request):
    from src.coding_api import MODEL as CODING_MODEL, CONTEXT as CODING_CONTEXT
    coding = request['model'] == CODING_MODEL
    u = r.get('usage')
    _schema(isinstance(u,dict), 'usage','shape')
    keys = {'input_tokens','output_tokens','total_tokens','input_tokens_details','output_tokens_details'}
    _schema(set(u) <= keys, 'usage','unknown_dimension')
    _schema(set(u) == keys, 'usage','shape')
    i, o, total = u['input_tokens'], u['output_tokens'], u['total_tokens']
    _schema(all(type(v) is int for v in (i,o,total)), 'usage','token_type')
    _schema(0 <= i <= (CODING_CONTEXT if coding else CONTEXT) and 0 <= o <= request['max_output_tokens'] and total >= 0,
            'usage','token_bounds')
    _schema(total == i+o, 'usage','total_mismatch')
    cached = u['input_tokens_details']
    _schema(isinstance(cached,dict) and 'cached_tokens' in cached, 'cached_tokens','shape')
    _schema(set(cached) <= ({'cached_tokens','cache_write_tokens','cache_write_tokens_details'} if coding
            else {'cached_tokens','cache_write_tokens'}), 'cached_tokens','unknown_dimension')
    c = cached['cached_tokens']
    _schema(type(c) is int, 'cached_tokens','token_type')
    _schema(0 <= c <= i, 'cached_tokens','token_bounds')
    if 'cache_write_tokens' in cached:
        writes = cached['cache_write_tokens']
        _schema(type(writes) is int, 'cached_tokens','token_type')
        _schema(writes >= 0, 'cached_tokens','token_bounds')
        # A documented zero-valued dimension adds no charge. Nonzero writes
        # require a separately reviewed pricing model; never silently price them.
        _schema(coding or writes == 0, 'cached_tokens','cache_write_not_priced')
        _schema(writes+c <= i, 'cached_tokens','token_bounds')
    if coding:
        from src.coding_api import cache_writes
        cache_writes(cached)
    reason = u['output_tokens_details']
    _schema(isinstance(reason,dict) and 'reasoning_tokens' in reason, 'reasoning_tokens','shape')
    _schema(set(reason) == {'reasoning_tokens'}, 'reasoning_tokens','unknown_dimension')
    n = reason['reasoning_tokens']
    _schema(type(n) is int, 'reasoning_tokens','token_type')
    _schema(0 <= n <= o, 'reasoning_tokens','token_bounds')
    return i, o, c, n


def _item_status(item, outer, nullable=False):
    if 'status' in item:
        value = item['status']
        _schema(value is None and nullable or value in ('completed','incomplete') or
                outer == 'incomplete' and value == 'in_progress', 'output','item_status')
    if 'id' in item:
        _schema(isinstance(item['id'],str), 'output','shape')


def _reasoning_item(item):
    _fields(item, {'id','type','summary','status','content','encrypted_content'}, 'reasoning', {'summary'})
    _schema(isinstance(item['summary'],list), 'reasoning','summary')
    for part in item['summary']:
        _schema(isinstance(part,dict) and set(part) == {'type','text'} and
                part['type'] == 'summary_text' and isinstance(part['text'],str), 'reasoning','summary')
    if item.get('content') is not None:
        _schema(isinstance(item['content'],list), 'reasoning','content')
        for part in item['content']:
            _schema(isinstance(part,dict) and set(part) == {'type','text'} and
                    part['type'] == 'reasoning_text' and isinstance(part['text'],str), 'reasoning','content')
    _schema(item.get('encrypted_content') is None or isinstance(item['encrypted_content'],str),
            'reasoning','encrypted_content')
    # All summaries, reasoning text, IDs and ciphertext are discarded, never
    # stored, forwarded to another turn, decrypted, displayed or executed.


def _output(r):
    output = r.get('output')
    _schema(isinstance(output,list) and len(output) <= MAX_OUTPUT, 'output','shape')
    for item in output:
        _schema(isinstance(item,dict), 'output','shape')
        kind = item.get('type')
        _schema(kind in ('message','reasoning'), 'output','item_type')
        _item_status(item, r['status'], nullable=kind == 'reasoning')
        if kind == 'reasoning':
            _reasoning_item(item)
            continue
        _fields(item, {'id','type','status','role','content','phase'}, 'message', {'role','content'})
        _schema(item['role'] == 'assistant', 'message','role')
        _schema(item.get('phase') in (None,'commentary','final_answer'), 'message','phase')
        _schema(isinstance(item['content'],list), 'message','shape')
        for part in item['content']:
            _schema(isinstance(part,dict), 'content','shape')
            if part.get('type') == 'output_text':
                _fields(part, {'type','text','annotations','logprobs'}, 'content', {'text'})
                _schema(isinstance(part['text'],str), 'content','text_type')
                _schema(part.get('annotations',[]) == [], 'content','annotations')
                _schema(part.get('logprobs') is None or part['logprobs'] == [], 'content','logprobs')
            elif part.get('type') == 'refusal':
                _fields(part, {'type','refusal'}, 'content', {'refusal'})
                _schema(isinstance(part['refusal'],str), 'content','text_type')
            else:
                _schema(False, 'content','shape')


def _receipt(raw, request, p):
    _schema(type(raw) is bytes and len(raw) <= MAX_RESPONSE, 'envelope','size')
    r = e.decode(raw)
    _schema(isinstance(r, dict), 'envelope','shape')
    # Select only reviewed receipt/security fields. Unknown top-level names and
    # values are never interpreted, traversed, forwarded, priced or diagnosed.
    # Nested authoritative structures retain their exact validation below.
    r = {name: r[name] for name in envelope.REVIEWED_FIELDS | envelope.REQUEST_ONLY_FIELDS if name in r}
    _schema(r.get('object') == 'response', 'envelope','object')
    _schema(request['model'] in (MODEL, 'gpt-6.1-sol') and
            r.get('model') == request['model'], 'envelope','model')
    _metadata(r, request)
    _completion(r)
    i, o, cached, reasoning = _usage(r, request)
    _output(r)
    cost = (i-cached)*p['input_nano_usd_per_token']+cached*p['cached_nano_usd_per_token']+o*p['output_nano_usd_per_token']
    if request['model'] == 'gpt-6.1-sol':
        from src.coding_api import charge, PRICING
        _schema(p == PRICING, 'metadata', 'unsupported_configuration')
        cost = charge(r['usage'])
    result = dict(status=r['status'], usage=dict(input_tokens=i, cached_input_tokens=cached,
        output_tokens=o, reasoning_tokens=reasoning), estimated_cost_nano_usd=cost,
        pricing_version=p['version'], model=request['model'], retry=False, tools_executed=0)
    if request['model'] == 'gpt-6.1-sol':
        result['usage']['cache_write_tokens'] = r['usage']['input_tokens_details']['cache_write_tokens']
    return result


def receipt(raw, request, p):
    try:
        e.decode(raw) if type(raw) is bytes and len(raw) <= MAX_RESPONSE else None
    except Exception:
        raise APIUnavailable('response_json_invalid', 'response_validation', 'response_received', 200,
                             validation_section='envelope', validation_rule='json') from None
    try:
        return _receipt(raw, request, p)
    except APIUnavailable:
        raise
    except Exception:
        raise APIUnavailable('response_schema_invalid', 'response_validation', 'response_received', 200,
            validation_section='internal', validation_rule='unexpected_validation_error') from None

class Controller:
    def __init__(self, budget, transport, prices=None):
        self.budget, self.transport = budget, transport
        self.prices = pricing(DEFAULT_PRICING if prices is None else prices)

    def _request(self, ident, request, binding, guard, *, _observation=False, _coding=False, _phase=None):
        # Internal finite progress markers only; never pass response data to a callback.
        def phase(value):
            if (_observation or _coding) and _phase is not None:
                _phase(value)
        from src.coding_api import PRICING, visible_edit
        e.require(type(_coding) is bool and not (_coding and _observation), 'Separate response contract required')
        if _coding:
            e.require(self.prices == PRICING and (
                type(self.transport) is ResponsesTransport and binding.get('receiver') == 'live-coding-only' or
                getattr(self.transport, 'synthetic', False) is True and binding.get('receiver') == 'synthetic-coding-only'),
                'Trusted coding transport required')
            validate_request(e.canonical(request).encode())
        else:
            e.require(self.prices['model'] == MODEL, 'Coding requires dedicated receiver')
        e.require(type(_observation) is bool and (not _observation or
                  getattr(self.transport, 'synthetic', False) is True and
                  binding.get('receiver') == 'synthetic-observation-only' or
                  _observation and binding.get('receiver') == 'live-observation-only' and
                  type(self.transport) is ResponsesTransport),
                  'Trusted observation transport required')
        guard()
        old = self.budget.reserve(ident, e.digest(dict(binding=binding, request=request, pricing=self.prices)),
                                  maximum_charge(self.prices, request['max_output_tokens']),
                                  provenance=dict(binding=binding, pricing=self.prices,
                                      model_config={k:v for k,v in request.items() if k != 'input'},
                                      prompt_digest=e.digest(request['input'])))
        if old is not None:
            e.require(not (_observation or _coding), 'Request already attempted; no replay or redispatch')
            return old
        guard()  # Failure after reservation intentionally leaves durable hold.
        try:
            phase('provider_transport')
            raw = self.transport.send(e.canonical(request).encode())
            phase('response_validation')
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
        phase('settlement')
        self.budget.settle(ident, result['estimated_cost_nano_usd'], result)
        phase('post_settlement_authorization')
        guard()  # Never deliver model output on revoked/expired/source-changed grant.
        if _coding:
            phase('coding_response')
            edit = visible_edit(raw)
            phase('post_settlement_authorization')
            guard()
            return edit
        if _observation:
            # A fixed internal boundary, never a raw-response callback/passthrough.
            from src.observation_planning import _classification
            phase('classification')
            classification = _classification(raw)
            phase('post_settlement_authorization')
            guard()
            return classification
        return result

    def connectivity(self, *, operator_enabled=False):
        e.require(operator_enabled is True and type(self.transport) is ResponsesTransport,
                  'Explicit operator-only connectivity activation required')
        return self._request(uuid.uuid4().hex, connectivity_payload(),
                             dict(purpose='operator-text-only-connectivity'), lambda:None)

    def _synthetic_authority(self, broker, claim, principal):
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
        return guard(), guard

    def synthetic_request(self, broker, claim, principal, ident, prompt):
        a, guard = self._synthetic_authority(broker, claim, principal)
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


def configuration(path):
    c = e.decode(e.regular(path).read_bytes())
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
    return c, p, budget


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
            c, p, budget = configuration(args.config)
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


