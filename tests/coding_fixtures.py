"""Offline verified Git objects, real edit, and deterministic provider envelopes."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from src import coding_canary as canary, orchestration_evidence as e
from src.local_runner import git, environment

ROOT = Path(__file__).parent/'fixtures/coding'
FIXTURE_SHA256 = 'af0f2f5c66f10b5763de321f35486d11eb59f9c530d435c03e43ef647f9ed211'


def capture():
    raw = (ROOT/'real_sol_low_comment.json').read_bytes()
    e.require(hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256, 'Real fixture bytes changed')
    value = e.decode(raw)
    e.require(value['provenance']['source_commit'] == canary.SOURCE, 'Fixture source mismatch')
    e.require(value['provenance']['model'] == 'gpt-6.1-sol', 'Fixture model mismatch')
    e.require(value['provenance']['reasoning_effort'] == 'low', 'Fixture effort mismatch')
    return value


def source(root):
    root.mkdir()
    git(root, 'init', '-q')
    objects = json.loads(gzip.decompress((ROOT/'source-objects.json.gz').read_bytes()))
    for sha, (kind, encoded) in objects.items():
        data = base64.b64decode(encoded, validate=True)
        e.require(hashlib.sha1((kind+' '+str(len(data))).encode()+b'\0'+data).hexdigest() == sha, 'Git object mismatch')
        result = subprocess.check_output(['/usr/bin/git', '-C', str(root), 'hash-object', '-w',
                                          '-t', kind, '--stdin'], input=data, env=environment())
        e.require(result.decode().strip() == sha, 'Imported Git object mismatch')
    (root/'.git/shallow').write_text(canary.SOURCE+'\n')
    git(root, 'update-ref', 'refs/heads/main', canary.SOURCE)
    git(root, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    git(root, 'reset', '--hard', '-q', canary.SOURCE)
    git(root, 'remote', 'add', 'origin', 'https://github.com/MZKZxyz/fort-custer-server.git')
    return root


def envelope(text=None, **overrides):
    value = capture()
    result = dict(object='response', model='gpt-6.1-sol', status='completed', error=None,
                  incomplete_details=None, usage=value['usage'], output=[
                      dict(type='message', role='assistant', status='completed', content=[
                          dict(type='output_text', text=e.canonical(value['model_output']) if text is None else text,
                               annotations=[])])])
    result.update(overrides)
    return e.canonical(result).encode()
