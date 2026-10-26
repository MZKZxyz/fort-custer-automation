"""Bounded untrusted observations, never settlement authority or model output."""
import re
from src import orchestration_evidence as e


def identifier(value, prefix):
    return value if isinstance(value, str) and re.fullmatch(prefix+r'[A-Za-z0-9_-]{1,96}', value) else None


def observe(raw, request, prices, binding, headers=None):
    result = dict(schema='api-observation-v1', trusted=False, execution=binding.get('execution'),
                  http_status=200, provider_request_id=identifier((headers or {}).get('request_id'), 'req_'),
                  pricing_version=prices['version'], response_sha256=None)
    if type(raw) is not bytes or len(raw) > 2*1024*1024:
        return result
    import hashlib
    result['response_sha256'] = hashlib.sha256(raw).hexdigest()
    try: r = e.decode(raw)
    except Exception: return result
    if not isinstance(r, dict): return result
    result['provider_response_id'] = identifier(r.get('id'), 'resp_')
    for name, allowed in [('status', {'completed','incomplete','failed','cancelled','queued','in_progress'}),
                          ('model', {request['model']}), ('service_tier', {'default','priority','flex','auto'})]:
        value = r.get(name)
        result[name] = value if isinstance(value, str) and value in allowed else None
    usage = r.get('usage')
    if not isinstance(usage, dict): return result
    counters = {}
    for label, obj, key in [('input_tokens', usage, 'input_tokens'), ('output_tokens', usage, 'output_tokens'),
                          ('cached_input_tokens', usage.get('input_tokens_details'), 'cached_tokens'),
                          ('cache_write_tokens', usage.get('input_tokens_details'), 'cache_write_tokens'),
                          ('reasoning_tokens', usage.get('output_tokens_details'), 'reasoning_tokens')]:
        v = obj.get(key) if isinstance(obj, dict) else None
        if type(v) is int and 0 <= v <= 2_000_000: counters[label] = v
    result['observed_usage'] = counters
    # Only the strict receiver can produce a calculated charge/validated receipt.
    return result
