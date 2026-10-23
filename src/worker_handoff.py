"""Bounded immutable wire documents, not a sandbox or a dispatch capability.

Only the trusted controller creates requests and captures output bytes. Workers
receive no controller path, executable choice, policy file, or ledger handle.
The controller must retain the exact request bytes outside worker storage.
"""
import hashlib
from pathlib import PurePosixPath

from src import orchestration_evidence as e

PROTOCOL = 'worker-handoff-v2-synthetic'
MAXIMUM = 1024 * 1024


def paths(names):
    e.require(isinstance(names, list) and bool(names) and len(set(names)) == len(names),
              'Exact file allowlist required')
    for name in names:
        e.require(isinstance(name, str) and bool(name) and
                  str(PurePosixPath(name)) == name and not name.startswith('/') and
                  all(p not in ('..', '.', '.git', '.codex') for p in name.split('/')) and
                  not any(p.startswith('.env') for p in name.split('/')) and
                  '\\' not in name and all(ord(c) >= 32 for c in name),
                  'Unsafe handoff path')


def request(authorization, claim):
    a = authorization
    e.require(claim['task'] == a['task'] and claim['execution'] == a['execution'] and
              claim['authorization'] == e.digest(a), 'Claim/authorization mismatch')
    paths(a['allowed'])
    doc = dict(schema=PROTOCOL, task=a['task'], execution=a['execution'],
               repository=a['repository'], source=a['source'], source_manifest=a['source_manifest'],
               policy_digest=a['policy_digest'], allowed=a['allowed'],
               instructions=a['spec']['prompt'], limits=a['spec']['limits'],
               worker=claim['worker'], token=claim['token'], generation=claim['generation'],
               deadline=claim['deadline'], max_artifact_bytes=MAXIMUM)
    e.require(e.sha(doc['source'], 40) and e.sha(doc['source_manifest']) and
              e.sha(doc['policy_digest']) and e.sha(doc['token'], 32) and
              type(doc['generation']) is int and doc['generation'] > 0 and
              e.finite(doc['deadline']) and claim['started'] < doc['deadline'] and
              doc['deadline'] <= a['expires'], 'Invalid handoff binding or expiry')
    raw = e.canonical(doc).encode()
    e.require(len(raw) <= MAXIMUM, 'Request too large')
    return raw


def response(request_bytes, files):
    """Synthetic fixture encoder; real output remains untrusted."""
    doc = e.decode(request_bytes)
    paths(list(files))
    payload = {name: [mode, data.hex()] for name, (mode, data) in files.items()}
    artifact = e.canonical(payload).encode()
    raw = e.canonical(dict(schema=PROTOCOL, request=hashlib.sha256(request_bytes).hexdigest(),
        token=doc['token'], generation=doc['generation'], artifact=payload,
        artifact_digest=hashlib.sha256(artifact).hexdigest())).encode()
    e.require(len(raw) <= MAXIMUM, 'Response too large')
    return raw


def ingest(request_bytes, response_bytes, now):
    """Validate exact response before existing independent source reconstruction."""
    e.require(type(request_bytes) is bytes and type(response_bytes) is bytes and
              len(request_bytes) <= MAXIMUM and len(response_bytes) <= MAXIMUM,
              'Bounded immutable wire bytes required')
    req, out = e.decode(request_bytes), e.decode(response_bytes)
    e.require(req['schema'] == PROTOCOL and set(out) ==
              {'schema', 'request', 'token', 'generation', 'artifact', 'artifact_digest'} and
              out['schema'] == PROTOCOL and out['request'] == hashlib.sha256(request_bytes).hexdigest() and
              out['token'] == req['token'] and type(out['generation']) is int and
              out['generation'] == req['generation'] and
              e.finite(now) and now < req['deadline'], 'Stale or forged worker response')
    e.require(len(response_bytes) <= MAXIMUM and isinstance(out['artifact'], dict),
              'Oversized or invalid artifact')
    paths(list(out['artifact']))
    e.require(set(out['artifact']) <= set(req['allowed']) and
              out['artifact_digest'] == hashlib.sha256(e.canonical(out['artifact']).encode()).hexdigest(),
              'Artifact scope or digest mismatch')
    result = {}
    for name, value in out['artifact'].items():
        e.require(isinstance(value, list) and len(value) == 2 and
                  type(value[0]) is int and value[0] in (0o644, 0o755) and
                  isinstance(value[1], str), 'Unsafe artifact')
        result[name] = (value[0], bytes.fromhex(value[1]))
    e.require(sum(len(data) for _, data in result.values()) <= req['max_artifact_bytes'],
              'Artifact limit')
    return result
