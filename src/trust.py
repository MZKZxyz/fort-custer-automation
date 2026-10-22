"""Control-plane capabilities. Keys and this module must never enter worker mounts.

The issuer is a separately deployed authenticated human approval service. HMAC
verifies its assertion, not the identity of a caller supplying a username.
"""
import hashlib
import hmac
import json
import re


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('Exact commit SHA required')
    return value


class Verifier:
    def __init__(self, key, issuer, audience, humans):
        if not isinstance(key, bytes) or len(key) < 32 or not issuer or not audience or not humans:
            raise ValueError('Trusted issuer configuration required')
        self.key, self.issuer, self.audience, self.humans = key, issuer, audience, frozenset(humans)

    def verify(self, envelope, action, binding, now):
        try:
            payload, signature = envelope['payload'], envelope['signature']
            expected = hmac.new(self.key, canonical(payload).encode(), hashlib.sha256).hexdigest()
            valid = (hmac.compare_digest(signature, expected)
                     and payload['issuer'] == self.issuer and payload['audience'] == self.audience
                     and payload['subject'] in self.humans and payload['action'] == action
                     and payload['binding'] == binding and type(payload['issued']) is int
                     and type(payload['expires']) is int
                     and payload['issued'] <= now < payload['expires'] <= payload['issued'] + 900
                     and isinstance(payload['nonce'], str) and len(payload['nonce']) >= 32)
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError('Unverifiable authorization')
        return payload

    def consume(self, db, envelope, action, binding, now):
        payload = self.verify(envelope, action, binding, now)
        # UNIQUE nonce enforces one use, in the same transaction as the action.
        db.execute('INSERT INTO s53_grants VALUES (?,?,?)',
                   (payload['nonce'], action, canonical(envelope)))
        return payload['subject']


LIVE_BLOCKERS = (
    'api_billing: authoritative reconciliation and strict $10/day and $3/task guarantees unavailable',
    'chatgpt_subscription: supported credential isolation and subscription-only execution remain unverified; no paid refills or API fallback',
    'External sandbox and credential-free model transport need deployment attestation',
    'First live canary and publication require separately reviewed activation',
)


def require_live():
    # Deliberate code gate: no config, grant, worker output or environment toggle
    # can enable live execution/publication in this release.
    raise RuntimeError('Live activation blocked: ' + '; '.join(LIVE_BLOCKERS))
