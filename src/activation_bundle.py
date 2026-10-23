"""Bounded source/candidate handoffs. Data preparation confers no live authority.

The trusted broker retains these bytes; neither worker nor QA supplies policy,
source paths, commands, source revisions, or an activation receipt.
"""
import hashlib
from pathlib import PurePosixPath

from src import orchestration_evidence as e, worker_handoff as wire
from src.source_observation import source_files, manifest

PROTOCOL = 'activation-bundle-v1-preparation'
MAXIMUM = wire.MAXIMUM
MAX_FILES = 2048


def pack(doc):
    raw = e.canonical(doc).encode()
    e.require(0 < len(raw) <= MAXIMUM, 'Bundle ceiling')
    return raw


def encode_files(files):
    return {name: [mode, data.hex()] for name, (mode, data) in files.items()}


def decode_files(doc):
    e.require(isinstance(doc, dict) and 0 < len(doc) <= MAX_FILES, 'File count ceiling')
    files = {}
    for name, value in doc.items():
        e.require(isinstance(name, str) and str(PurePosixPath(name)) == name and
                  not name.startswith('/') and '\\' not in name and
                  all(p not in ('', '.', '..', '.git', '.codex', '.gitattributes', '.gitmodules', 'AGENTS.md')
                      and not p.startswith('.env') for p in name.split('/')) and
                  all(ord(c) >= 32 for c in name), 'Unsafe source path')
        e.require(isinstance(value, list) and len(value) == 2 and type(value[0]) is int and
                  value[0] in (0o644, 0o755) and isinstance(value[1], str) and
                  len(value[1]) <= MAXIMUM*2, 'Unsafe file or permissions')
        data = bytes.fromhex(value[1])
        e.require(data.hex() == value[1], 'Noncanonical file encoding')
        files[name] = (value[0], data)
    e.require(sum(len(data) for _, data in files.values()) <= MAXIMUM, 'Workspace input ceiling')
    return files


def worker_bundle(a, claim):
    """Read exact trusted Git objects, with no .git, account files or host paths."""
    request = wire.request(a, claim)
    policy, _, specs = e.catalog(a['policy_path'])
    e.require(e.digest(policy) == a['policy_digest'] and specs[a['task']] == a['spec'],
              'Changed approved policy')
    from src.source_observation import git
    source = policy['repositories'][a['spec']['repo']]['source']
    e.require(git(source, 'rev-parse', 'HEAD').decode().strip() == a['source'], 'Changed source HEAD')
    files = source_files(source, a['source'], a['allowed'])
    e.require(manifest(files) == a['source_manifest'], 'Changed source manifest')
    # Fail rather than silently strip unsafe files and change the source identity.
    decode_files(encode_files(files))
    return pack(dict(schema=PROTOCOL, kind='worker', request=request.decode(),
                     source=encode_files(files)))


def unpack_worker(raw):
    e.require(type(raw) is bytes and 0 < len(raw) <= MAXIMUM, 'Bundle ceiling')
    doc = e.decode(raw)
    e.require(set(doc) == {'schema', 'kind', 'request', 'source'} and doc['schema'] == PROTOCOL and
              doc['kind'] == 'worker' and isinstance(doc['request'], str), 'Unknown worker bundle')
    req = e.decode(doc['request'])
    e.require(set(req) == {'schema', 'task', 'execution', 'repository', 'source', 'source_manifest',
                          'policy_digest', 'allowed', 'instructions', 'limits', 'worker', 'token',
                          'generation', 'deadline', 'max_artifact_bytes'} and
              req['schema'] == wire.PROTOCOL and e.sha(req['source'], 40) and
              e.sha(req['policy_digest']) and e.sha(req['token'], 32) and
              type(req['generation']) is int and req['generation'] > 0 and
              e.finite(req['deadline']), 'Invalid worker request')
    wire.paths(req['allowed'])
    files = decode_files(doc['source'])
    e.require(manifest(files) == req['source_manifest'] and set(req['allowed']) <= set(files),
              'Source snapshot mismatch')
    return req, files


def qa_bundle(a, claim, retained_worker_bundle, response, now):
    """Controller selects checks and reconstructs candidate; never executes it."""
    req, files = unpack_worker(retained_worker_bundle)
    exact = wire.request(a, claim)
    e.require(e.decode(retained_worker_bundle)['request'].encode() == exact, 'Changed retained request')
    delta = wire.ingest(exact, response, now)
    e.require(set(delta) == set(a['allowed']), 'Missing or unexpected output')
    e.require(all(delta[name][0] == files[name][0] for name in delta), 'Changed permissions')
    candidate = dict(files); candidate.update(delta)
    changed = sorted(name for name in files if files[name] != candidate[name])
    e.require(bool(changed), 'Empty candidate')
    return pack(dict(schema=PROTOCOL, kind='qa', worker_bundle=retained_worker_bundle.decode(),
                     worker_response=response.decode(), checks=a['checks'],
                     candidate_manifest=manifest(candidate), authorization=e.digest(a)))


def unpack_qa(raw, now):
    """QA reconstructs solely from controller-retained source and captured bytes."""
    e.require(type(raw) is bytes and 0 < len(raw) <= MAXIMUM, 'Bundle ceiling')
    doc = e.decode(raw)
    e.require(set(doc) == {'schema', 'kind', 'worker_bundle', 'worker_response', 'checks',
                          'candidate_manifest', 'authorization'} and
              doc['schema'] == PROTOCOL and doc['kind'] == 'qa' and e.sha(doc['authorization']),
              'Unknown QA bundle')
    req, files = unpack_worker(doc['worker_bundle'].encode())
    worker = e.decode(doc['worker_bundle'])
    delta = wire.ingest(worker['request'].encode(), doc['worker_response'].encode(), now)
    e.require(set(delta) == set(req['allowed']) and
              all(delta[name][0] == files[name][0] for name in delta), 'Unsafe candidate delta')
    candidate = dict(files); candidate.update(delta)
    e.require(manifest(candidate) == doc['candidate_manifest'] and candidate != files,
              'Candidate manifest mismatch')
    checks = doc['checks']
    e.require(isinstance(checks, list) and 0 < len(checks) <= 32, 'Missing bounded QA specification')
    names = set()
    for check in checks:
        e.require(isinstance(check, dict) and set(check) == {'name', 'argv', 'timeout_seconds'},
                  'Unknown QA specification')
        argv = check['argv']
        e.require(isinstance(check['name'], str) and check['name'] not in names and
                  isinstance(argv, list) and len(argv) == 3 and argv[:2] in
                  (['node', '--check'], ['node', '--test']) and argv[2] in files and
                  argv[2].endswith(('.js', '.mjs', '.cjs')) and
                  type(check['timeout_seconds']) is int and 0 < check['timeout_seconds'] <= 2400,
                  'Unapproved QA command grammar')
        names.add(check['name'])
    return req, candidate, checks


def verify_qa_response(request, response, now):
    """Accept only an authenticated QA peer's exact successful reconstruction.

    The caller must authenticate the peer before transferring request bytes.
    A matching hash supplied by a worker is never independent QA evidence.
    This validator does not import results into historical publisher ledgers.
    """
    req, candidate, checks = unpack_qa(request, now)
    e.require(type(response) is bytes and len(response) <= MAXIMUM, 'QA receipt ceiling')
    doc = e.decode(response)
    expected = dict(schema=PROTOCOL, kind='qa-result',
                    request=hashlib.sha256(request).hexdigest(), token=req['token'],
                    generation=req['generation'], candidate_manifest=manifest(candidate),
                    checks=[dict(name=c['name'], argv=c['argv'], code=0, reason=None) for c in checks],
                    candidate_unchanged=True, publication='separate-authorization-required')
    e.require(e.canonical(doc) == e.canonical(expected) and now < req['deadline'],
              'Untrusted, incomplete or failed QA receipt')
    return doc


class IsolatedQA:
    """Controller client only; no candidate subprocess can run on this side.

    The installed QA service/VM relay must authorize the controller in the
    opposite direction and durably fence requests before executing any tests.
    That deployment is an explicit activation blocker in this release.
    """
    def __init__(self, endpoint, worker_uid):
        import os
        from src.worker_transport import IsolatedEndpoint
        e.require(type(endpoint) is IsolatedEndpoint and type(worker_uid) is int and
                  worker_uid > 0 and worker_uid != os.getuid() and endpoint.uid != worker_uid,
                  'QA must be distinct from controller and worker')
        self.endpoint = endpoint

    def check(self, request, now, guard):
        # guard rechecks the durable broker fence/STOP before and after IPC.
        req, _, _ = unpack_qa(request, now())
        guard()
        remaining = req['deadline']-now()
        e.require(0 < remaining <= 2400, 'QA deadline')
        response = self.endpoint.exchange(request, remaining)
        guard()
        return verify_qa_response(request, response, now())
