"""Terminal review of retained externally verifiable provider billing evidence.

This validates linkage and completeness, not provider authenticity. The operator
must verify the external artifact in the provider account/support channel.
"""
import argparse
import hashlib
from pathlib import Path
from urllib.parse import urlparse

from src import api_controller as api, orchestration_evidence as e
from src.api_evidence import identifier
from src.local_runner import terminal_challenge

FIELDS = {'schema','request_id','execution','provider_request_id','provider_response_id',
          'account_project','source','reference','artifact_sha256','actual_nano_usd',
          'currency','final','provider_terminal','outcome','model','service_tier','pricing_version','usage'}


def validate_amount(m):
    """Verify supported billing arithmetic; provider authenticity stays external."""
    from src.coding_api import MODEL, PRICING, CONTEXT, OUTPUT, charge
    e.require(type(m['actual_nano_usd']) is int and m['actual_nano_usd'] >= 0,
              'Integer final charge required')
    if m['outcome'] == 'confirmed-no-charge':
        e.require(m['actual_nano_usd'] == 0, 'No-charge evidence cannot carry a charge')
        return
    u = m['usage']
    e.require(m['outcome'] == 'billed' and m['actual_nano_usd'] > 0 and
              m['model'] == MODEL and m['service_tier'] == 'default' and
              m['pricing_version'] == PRICING['version'] and isinstance(u,dict) and
              set(u) == {'input_tokens','cached_input_tokens','cache_write_tokens','output_tokens','reasoning_tokens'} and
              all(type(v) is int and v >= 0 for v in u.values()) and
              u['cached_input_tokens']+u['cache_write_tokens'] <= u['input_tokens'] <= CONTEXT and
              u['reasoning_tokens'] <= u['output_tokens'] <= OUTPUT,
              'Reviewed model, pricing and consistent full usage required')
    calculated = charge(dict(input_tokens=u['input_tokens'],output_tokens=u['output_tokens'],
        input_tokens_details=dict(cached_tokens=u['cached_input_tokens'],cache_write_tokens=u['cache_write_tokens'])))
    e.require(calculated == m['actual_nano_usd'], 'Provider amount does not match reviewed pricing')


def reconcile(budget, manifest_file, artifact_file):
    raw = e.regular(manifest_file).read_bytes()
    e.require(len(raw) <= 8192, 'Evidence manifest ceiling')
    m = e.decode(raw)
    e.require(isinstance(m, dict) and set(m) == FIELDS and m['schema'] == 'provider-billing-evidence-v1',
              'Complete external evidence manifest required')
    artifact = e.regular(artifact_file)
    e.require(0 < artifact.stat().st_size <= 8*1024*1024, 'External evidence artifact ceiling')
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    e.require(digest == m['artifact_sha256'] and artifact != Path(manifest_file).absolute(),
              'Separate retained provider artifact required')
    link = urlparse(m['reference'])
    e.require(link.scheme == 'https' and link.hostname in {'platform.openai.com','help.openai.com','support.openai.com'}
              and not link.username and not link.password and not link.query and not link.fragment and len(m['reference']) <= 512,
              'Provider-verifiable reference required')
    e.require(e.sha(m['request_id'],32) and e.sha(m['execution'],32) and
              (identifier(m['provider_request_id'],'req_') is not None or
               identifier(m['provider_response_id'],'resp_') is not None) and
              m['source'] in {'provider-request-export','provider-support-confirmation'} and
              isinstance(m['account_project'],str) and 0 < len(m['account_project']) <= 128 and
              m['final'] is True and m['provider_terminal'] is True and m['currency'] == 'USD' and
              type(m['actual_nano_usd']) is int and m['actual_nano_usd'] >= 0 and
              m['outcome'] in {'billed','confirmed-no-charge'} and
              (m['actual_nano_usd'] > 0 or m['outcome'] == 'confirmed-no-charge'),
              'Final attributable provider outcome required')
    validate_amount(m)
    with budget.tx() as db:
        r = db.execute('SELECT * FROM requests WHERE id=?',(m['request_id'],)).fetchone()
        e.require(r is not None and r['actual'] is None and m['actual_nano_usd'] <= r['reserved'],
                  'Existing unresolved reservation and bounded charge required')
        events = [dict(x) for x in db.execute('SELECT * FROM events WHERE request=? ORDER BY seq',(m['request_id'],))]
        reservation = next(e.decode(x['evidence']) for x in events if x['kind'] == 'reserved')
        provenance = reservation.get('provenance') or {}
        execution = (provenance.get('binding') or {}).get('execution')
        e.require(execution is None or execution == m['execution'], 'Execution linkage mismatch')
        for event in events:
            if event['kind'] != 'response_observed_untrusted': continue
            observation = e.decode(event['evidence'])
            for key in ('provider_request_id','provider_response_id'):
                if observation.get(key) is not None:
                    e.require(m[key] == observation[key], 'Provider identifier conflict')
    review = dict(request_id=m['request_id'], execution=m['execution'],
                  actual_nano_usd=m['actual_nano_usd'], manifest_sha256=hashlib.sha256(raw).hexdigest(),
                  artifact_sha256=digest, reference=m['reference'], retry=False)
    print(e.canonical(review))
    challenge = 'VERIFIED EXTERNAL PROVIDER BILLING '+e.digest(review)
    e.require(terminal_challenge(challenge) == challenge, 'Operator must independently verify provider evidence')
    e.require(e.regular(manifest_file).read_bytes() == raw and
              hashlib.sha256(e.regular(artifact_file).read_bytes()).hexdigest() == digest,
              'Evidence changed during terminal review')
    # The retained artifacts, account identity and linkage are reviewed externally;
    # only hashes and finite billing evidence enter the accounting audit.
    budget.settle(m['request_id'], m['actual_nano_usd'],
                  dict(status='operator-reconciled', estimated_cost_nano_usd=m['actual_nano_usd'],
                       retry=False, manifest_sha256=review['manifest_sha256']), evidence=review)
    return review


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api-config',required=True); p.add_argument('--manifest',required=True)
    p.add_argument('--artifact',required=True)
    a = p.parse_args()
    try:
        result = reconcile(api.configuration(a.api_config)[2],a.manifest,a.artifact)
        print(e.canonical(result)); return 0
    except Exception:
        print(e.canonical(dict(status='unresolved',retry=False,instruction='preserve hold; verify complete provider evidence')))
        return 1


if __name__ == '__main__': raise SystemExit(main())
