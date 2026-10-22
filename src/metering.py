"""Codex provider events are observed telemetry, never authoritative invoices."""
import json
from decimal import Decimal, ROUND_CEILING
from trust import digest


def parse_events(lines, execution, model, pricing_version=None):
    if not execution or not model:
        raise ValueError('Execution/model provenance required')
    thread=None; usage=None; completed=0
    for line in lines:
        event=json.loads(line)
        if event.get('type') in ('error','turn.failed'):
            raise ValueError('Incomplete execution telemetry')
        if event.get('type')=='thread.started':
            if thread or not event.get('thread_id'):
                raise ValueError('Ambiguous provider execution')
            thread=event['thread_id']
        if event.get('type')=='turn.completed':
            completed+=1; usage=event['usage']
    required={'input_tokens','cached_input_tokens','output_tokens'}
    optional={'cache_write_input_tokens','reasoning_output_tokens'}
    if not thread or completed!=1 or not isinstance(usage,dict) or not required<=set(usage) or set(usage)-required-optional:
        raise ValueError('Missing, repeated or unsupported usage')
    if any(type(v) is not int or v<0 for v in usage.values()) or usage['cached_input_tokens']>usage['input_tokens'] or usage.get('reasoning_output_tokens',0)>usage['output_tokens']:
        raise ValueError('Inconsistent usage')
    return dict(execution=execution,provider_execution=thread,model=model,pricing_version=pricing_version,
                tokens=usage,kind='observed',billed=False,model_identity_source='controller_requested',actual_model=None)


def estimate(usage, price, now):
    # No shipped model prices: caller must supply a verified versioned schedule.
    if (price.get('model')!=usage['model'] or price.get('version')!=usage['pricing_version']
            or not price.get('version') or not price.get('verified') or not price.get('issued',now+1)<=now<price.get('expires',0)):
        raise ValueError('Reliable current pricing unavailable')
    tokens=usage['tokens']
    if tokens.get('cache_write_input_tokens',0):
        raise ValueError('Cache-write pricing unsupported')
    rates=[Decimal(str(price[k])) for k in ('input_per_million','cached_per_million','output_per_million')]
    if any(not r.is_finite() or r<0 for r in rates):
        raise ValueError('Invalid rates')
    amount=((tokens['input_tokens']-tokens['cached_input_tokens'])*rates[0]+tokens['cached_input_tokens']*rates[1]+tokens['output_tokens']*rates[2])/Decimal(1000000)
    return dict(kind='estimated',usd=str(amount),cents=int((amount*100).to_integral_value(rounding=ROUND_CEILING)),
                pricing_version=price['version'],evidence=digest(usage),billed=False)


def verify_authoritative_billing(evidence, run, now):
    # No sufficiently authoritative billing adapter established. Never accept
    # arbitrary cents, worker JSON or a CLI token count as an invoice.
    raise ValueError('Authoritative provider billing and hard ceiling unavailable')
