"""Reviewed Sol Low text-only profile and billing; never dispatches by itself."""
from src import orchestration_evidence as e

MODEL = 'gpt-6.1-sol'
CONTEXT = 1_050_000
OUTPUT = 4000
PRICING = dict(version='sol-standard-global-2026-10-23-v1', model=MODEL,
               input_nano_usd_per_token=2000, cached_nano_usd_per_token=100,
               output_nano_usd_per_token=10000, cache_write_nano_usd_per_token=2500)
# Full context, long-input multiplier, and all input written at default 30m TTL.
# No tokenizer estimate, cached-input discount, or short-prompt assumption.
MAXIMUM_CHARGE = CONTEXT*5000+OUTPUT*15000


def payload(prompt):
    e.require(isinstance(prompt, str) and 0 < len(prompt.encode()) <= 24000,
              'Coding prompt ceiling')
    return dict(model=MODEL, input=prompt, reasoning=dict(effort='low'),
                max_output_tokens=OUTPUT, store=False, background=False, stream=False,
                tools=[], tool_choice='none', parallel_tool_calls=False,
                truncation='disabled', service_tier='default')


def cache_writes(details):
    from src.api_controller import _schema
    _schema('cache_write_tokens' in details, 'cached_tokens', 'shape')
    writes = details.get('cache_write_tokens', 0)
    _schema(type(writes) is int and writes >= 0, 'cached_tokens', 'token_bounds')
    breakdown = details.get('cache_write_tokens_details')
    _schema(breakdown is None or isinstance(breakdown, dict) and
            set(breakdown) == {'ttl_30m_tokens', 'ttl_12h_tokens'} and
            type(breakdown['ttl_30m_tokens']) is int and
            type(breakdown['ttl_12h_tokens']) is int and
            breakdown['ttl_30m_tokens'] == writes and breakdown['ttl_12h_tokens'] == 0,
            'cached_tokens', 'cache_write_not_priced')
    return writes


def charge(usage):
    i, o = usage['input_tokens'], usage['output_tokens']
    details = usage['input_tokens_details']
    cached, writes = details['cached_tokens'], cache_writes(details)
    # Cache writes replace the uncached input rate; reasoning is already in output.
    input_cost = (i-cached-writes)*2000+cached*100+writes*2500
    return input_cost*(2 if i > 272000 else 1)+o*(15000 if i > 272000 else 10000)


def visible_edit(raw):
    """Called only after validated receipt settlement; no observation classifier."""
    from src.coding_contract import MAXIMUM
    r = e.decode(raw)
    e.require(r['status'] == 'completed' and r.get('incomplete_details') is None,
              'Completed coding response required')
    messages = [x for x in r['output'] if x['type'] != 'reasoning']
    e.require(len(messages) == 1 and messages[0]['type'] == 'message' and
              messages[0].get('status', 'completed') == 'completed' and
              messages[0].get('phase') in (None, 'final_answer') and
              len(messages[0]['content']) == 1, 'One final coding message required')
    part = messages[0]['content'][0]
    e.require(part['type'] == 'output_text' and
              0 < len(part['text'].encode()) <= MAXIMUM, 'Bounded coding text required')
    raw_edit = part['text'].encode()
    value = e.decode(raw_edit)
    e.require(isinstance(value, dict) and set(value) == {'old', 'new'} and
              all(isinstance(v, str) and v for v in value.values()), 'Coding edit schema')
    return raw_edit
