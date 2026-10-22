"""Guarded local publication. No CLI login, model invocation, push or ref update.

The operator-owned SQLite ledger is the authority, NOT a tamper-proof signature.
The publisher must run on a trusted host separately from coding and QA.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

from src.local_runner import (ALLOWED, CHECKS, MODE, PROMPT, Runner, canonical,
                              digest, environment, git, manifest, materialize,
                              snapshot, source_files)

REPOSITORY = 'MZKZxyz/fort-custer-server'
RUN = 'd808dca82ca74d65ba0b7ba9ab7197de'
BASE = 'c4f480abb309a7a4d141b20ab462552a868ef0e3'
CANDIDATE = '1b76b0476f0cee84cefa72d93fccd4dc94f7304d85f3520beb97ee8b0dbe561a'
TREE = '2148e1f387d8eff643c1672762fae3b3c3924c76'
REVISION = '4542a5735d67cc0eb5da0447c5ea81bbcbc5a19d'
TITLE = 'Fix inherited-property maze direction lookup'
IDENTITY = dict(name='Fort Custer Publisher', email='publisher@fort-custer.local', date='2026-10-22T00:00:00Z')


def reconstruct(runner, run):
    """Read durable evidence; never depend on the original temporary workspace."""
    r = runner.inspect(run)
    spec = r['spec']
    policy = json.loads(runner.policy_path.read_text())
    if (r['state'] != 'validated' or digest(spec) != r['binding'] or
        spec['policy'] != digest(policy) or spec['mode'] != MODE or
        spec['repo'] != 'fort-custer-server' or spec['issue'] != 3 or
        spec['prompt'] != PROMPT or spec['allowed'] != ALLOWED or
        canonical(spec['checks']) != canonical(CHECKS) or
        spec['issue_snapshot'].get('html_url') != 'https://github.com/'+REPOSITORY+'/issues/3' or
        spec['issue_snapshot'].get('state') != 'open' or
        spec['issue_snapshot'].get('number') != 3 or
        'pull_request' in spec['issue_snapshot'] or
        spec['source'] != policy['repositories']['fort-custer-server']['sha'] or
        spec['branch'] != 'main' or r['files'] != ALLOWED):
        raise ValueError('Invalid validated task evidence')
    usage = r.get('usage')
    if (not isinstance(usage, dict) or not {'input_tokens', 'cached_input_tokens', 'output_tokens'} <= usage.keys() or
        any(type(v) is not int or v < 0 for v in usage.values())):
        raise ValueError('Required execution usage evidence missing')
    history = [h['event'] for h in r['history']]
    if history != ['prepared', 'approved', 'claimed', 'validated'] or r['history'][1].get('binding') != r['binding']:
        raise ValueError('Missing task authorization provenance')
    qa = r['qa']
    if ([q['name'] for q in qa] != ['diff', *[x[0] for x in CHECKS], 'candidate'] or
        any(type(q['code']) is not int or q['code'] != 0 or q['reason'] is not None for q in qa)):
        raise ValueError('Complete passing independent QA required')
    expected = [['/usr/bin/git', 'diff', '--check', 'HEAD^', 'HEAD']]
    expected += [[policy['node'], *cmd[1:]] for _, cmd in CHECKS]
    if [q['command'] for q in qa[:-1]] != expected:
        raise ValueError('QA command evidence changed')
    for q in qa[:-1]:
        if not isinstance(q['stdout'], str) or not isinstance(q['stderr'], str):
            raise ValueError('QA output missing')
    if not re.search(r'(?:#|ℹ) tests 14\b', qa[3]['stdout']) or not re.search(r'(?:#|ℹ) pass 14\b', qa[3]['stdout']) or not re.search(r'(?:#|ℹ) fail 0\b', qa[3]['stdout']):
        raise ValueError('Expected fourteen analyzer tests required')
    artifact = qa[-1]
    if (run != RUN or spec['source'] != BASE or r['candidate_hash'] != CANDIDATE or
        artifact['candidate_hash'] != CANDIDATE or artifact['candidate_tree'] != TREE or
        artifact['candidate_revision'] != REVISION or artifact['input_hash'] != spec['input_hash']):
        raise ValueError('Only the reviewed Issue 3 candidate is allowlisted')
    files = source_files(policy['repositories']['fort-custer-server']['source'], BASE)
    if manifest(files) != spec['input_hash']:
        raise ValueError('Input hash mismatch')
    patch = artifact['patch']
    if not isinstance(patch, str) or not patch or len(patch.encode()) > 8*1024*1024:
        raise ValueError('Invalid durable patch')
    with tempfile.TemporaryDirectory(prefix='publication-') as work:
        root = Path(work); materialize(files, root); git(root, 'init', '-q')
        git(root, 'add', '--all', '--force')
        source = policy['repositories']['fort-custer-server']['source']
        if git(root, 'write-tree').strip() != git(source, 'rev-parse', BASE+'^{tree}').strip():
            raise ValueError('Base Git tree mismatch')
        # Fixed Git options and no source hooks, attributes, remotes or shared objects.
        result = subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-C', work,
                                 'apply', '--index', '--binary', '--whitespace=error', '-'],
                                input=patch.encode(), env=environment(), capture_output=True, timeout=30)
        if result.returncode: raise ValueError('Stored patch does not apply exactly')
        # Git applies files under the process umask; restore the Git index modes
        # before comparing the durable byte-and-mode manifest.
        for entry in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
            if not entry: continue
            metadata, name = entry.split(b'\t')
            mode = metadata.split()[0]
            if mode not in (b'100644', b'100755'): raise ValueError('Unsafe patched mode')
            (root/name.decode()).chmod(int(mode, 8) & 0o777)
        candidate = {k:v for k,v in snapshot(root).items() if not k.startswith('.git/')}
        changed = sorted(k for k in files.keys() | candidate.keys() if files.get(k) != candidate.get(k))
        if changed != ALLOWED or manifest(candidate) != CANDIDATE or git(root, 'write-tree').decode().strip() != TREE:
            raise ValueError('Candidate files, hash or tree mismatch')
    return r, files, candidate


def publication_commit():
    raw = (f'tree {TREE}\nparent {BASE}\nauthor {IDENTITY["name"]} <{IDENTITY["email"]}> 1792627200 +0000\n'
           f'committer {IDENTITY["name"]} <{IDENTITY["email"]}> 1792627200 +0000\n\n'+TITLE+'\n').encode()
    return hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def body(r):
    return ('Issue: https://github.com/'+REPOSITORY+'/issues/3\n\n'
            'Restrict maze direction lookup to own properties and add regression tests. '
            'The broader maze-generation investigation remains open.\n\n'
            f'Original source commit: {BASE}\nValidated local revision: {REVISION}\n'
            f'Candidate hash: {CANDIDATE}\nCandidate tree: {TREE}\nLocal execution ID: {RUN}\n'
            f'Independent QA evidence SHA-256: {digest(r["qa"])}\n'
            'All six recorded QA entries passed; all 14 analyzer tests passed.\n\n'
            'Human review is required. No merge or deployment is authorized.\n\n'
            'Independent QA details:\n```json\n'+json.dumps(r['qa'][:-1], indent=2, ensure_ascii=True)+'\n```\n')


class Publications:
    def __init__(self, runner):
        self.runner = runner
        with runner.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS publication_events (sequence INTEGER PRIMARY KEY, publication TEXT NOT NULL, event TEXT NOT NULL, at REAL NOT NULL, actor INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS publications (id TEXT PRIMARY KEY, run TEXT UNIQUE NOT NULL, request TEXT NOT NULL, binding TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL)')

    def event(self, db, publication, event):
        db.execute('INSERT INTO publication_events(publication,event,at,actor) VALUES (?,?,?,?)',
                   (publication, event, self.runner.clock(), os.getuid()))

    def read(self, db, publication):
        row = db.execute('SELECT request,binding,status,result FROM publications WHERE id=?', (publication,)).fetchone()
        if row is None: raise ValueError('Unknown publication')
        history = [dict(event=x[0], at=x[1], actor=x[2]) for x in db.execute(
            'SELECT event,at,actor FROM publication_events WHERE publication=? ORDER BY sequence', (publication,))]
        return dict(request=json.loads(row[0]), binding=row[1], status=row[2], result=json.loads(row[3]), history=history)

    def inspect(self, publication):
        with self.runner.tx() as db: return self.read(db, publication)

    def check(self, p, expiry=True):
        if p['status'] == 'cancelled': raise ValueError('Publication cancelled')
        if self.runner.state.joinpath('STOP').exists(): raise ValueError('Persistent kill switch active')
        if digest(p['request']) != p['binding']: raise ValueError('Publication request altered')
        if expiry and p['request']['expires'] <= self.runner.clock(): raise ValueError('Publication approval expired')
        r, files, candidate = reconstruct(self.runner, p['request']['run'])
        if p['request'] != self.request(r, p['request']['expires']):
            raise ValueError('Artifact or publication action changed')
        return r, files, candidate

    def request(self, r, expires):
        return dict(run=r['id'], artifact=digest(r), candidate_hash=CANDIDATE, tree=TREE,
                    base=BASE, repository=REPOSITORY, branch='codex/issue-3-'+RUN,
                    title=TITLE, body=body(r), commit=publication_commit(), action='create-new-branch-and-draft-pr-against-main',
                    expires=expires, author=IDENTITY, message=TITLE+'\n', draft=True,
                    provenance_limit='trusted operator ledger; no privileged-tamper signature')

    def prepare(self, run):
        r, _, _ = reconstruct(self.runner, run)
        request = self.request(r, self.runner.clock()+600)
        publication = digest(dict(run=run, candidate=CANDIDATE))
        with self.runner.tx() as db:
            row = db.execute('SELECT id FROM publications WHERE run=?', (run,)).fetchone()
            if row:
                return dict(self.read(db, row[0]), id=row[0], patch=r['qa'][-1]['patch'], qa=r['qa'])
            if self.runner.state.joinpath('STOP').exists(): raise ValueError('Persistent kill switch active')
            db.execute('INSERT INTO publications VALUES (?,?,?,?,?,?)',
                       (publication, run, canonical(request), digest(request), 'prepared', '{}'))
            self.event(db, publication, 'prepared')
        p = self.inspect(publication)
        return dict(p, id=publication, patch=r['qa'][-1]['patch'], qa=r['qa'],
                    remote_check='Required via dedicated publisher inspect before approval; offline preparation cannot establish remote absence')

    def remote_inspect(self, publication, remote):
        p = self.inspect(publication); self.check(p)
        q = p['request']
        result = dict(repository=remote.repository(), main=remote.main(), branch=remote.head(q['branch']),
                      prs=remote.prs(q['branch']))
        if p['status'] == 'prepared':
            if result != dict(repository=REPOSITORY, main=BASE, branch=None, prs=[]):
                raise ValueError('Remote destination already exists or base changed')
            with self.runner.tx() as db:
                current = self.read(db, publication); self.check(current)
                if current['status'] != 'prepared': raise ValueError('Publication status changed')
                db.execute('UPDATE publications SET result=? WHERE id=?',
                           (canonical(dict(preflight_binding=p['binding'], checked=self.runner.clock())), publication))
                self.event(db, publication, 'remote-preflight')
        return result

    def approve(self, publication, response):
        with self.runner.tx() as db:
            p = self.read(db, publication); self.check(p)
            if (p['status'] != 'prepared' or response != 'PUBLISH '+p['binding'] or
                p['result'].get('preflight_binding') != p['binding'] or
                not 0 <= self.runner.clock()-p['result'].get('checked', 0) < 600):
                raise ValueError('Fresh separate exact publication approval required')
            db.execute("UPDATE publications SET status='approved' WHERE id=?", (publication,))
            self.event(db, publication, 'approved')
        return self.inspect(publication)

    def cancel(self, publication):
        with self.runner.tx() as db:
            self.read(db, publication)
            db.execute("UPDATE publications SET status='cancelled' WHERE id=?", (publication,))
            self.event(db, publication, 'cancelled')
        return self.inspect(publication)

    def execute(self, publication, remote):
        with open(self.runner.state/'publisher.lock', 'a') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Publisher already active') from None
            return self._execute(publication, remote)

    def _execute(self, publication, remote):
        with self.runner.tx() as db:
            p = self.read(db, publication)
            r, files, candidate = self.check(p, expiry=p['status'] != 'completed')
            if p['status'] not in ('approved', 'publishing', 'pr-requested', 'completed'):
                raise ValueError('Unused publication authorization required')
            if p['status'] == 'approved':
                db.execute("UPDATE publications SET status='publishing' WHERE id=?", (publication,))
                self.event(db, publication, 'publishing')
        q = p['request']
        if remote.repository() != q['repository'] or remote.main() != BASE:
            raise ValueError('Destination or main advanced; new human review required')
        if remote.commit(BASE)['sha'] != BASE: raise ValueError('Base commit unavailable')
        commit = publication_commit()
        if p['status'] != 'completed':
            self.check(self.inspect(publication))
            if remote.candidate(q, files, candidate) != commit: raise ValueError('Candidate commit mismatch')
        # Candidate is a new publication commit with original base as sole parent.
        info = remote.commit(commit)
        if info['sha'] != commit or info['tree']['sha'] != TREE or [x['sha'] for x in info['parents']] != [BASE]:
            raise ValueError('Published commit provenance mismatch')
        head = remote.head(q['branch'])
        prs = remote.prs(q['branch'])
        if head not in (None, commit) or len(prs) > 1: raise ValueError('Remote state conflict')
        if head is None:
            if prs or p['status'] in ('pr-requested', 'completed'): raise ValueError('Remote branch disappeared')
            self.check(self.inspect(publication))
            remote.create_branch(q['branch'], commit)
        if remote.head(q['branch']) != commit: raise ValueError('Remote branch verification failed')
        if not prs:
            if p['status'] in ('pr-requested', 'completed'):
                raise ValueError('Ambiguous PR creation; reconcile manually, never repeat POST')
            with self.runner.tx() as db:
                current = self.read(db, publication); self.check(current)
                if current['status'] != 'publishing': raise ValueError('Publication cancelled')
                db.execute("UPDATE publications SET status='pr-requested' WHERE id=?", (publication,))
                self.event(db, publication, 'pr-requested')
            remote.create_pr(q)
            prs = remote.prs(q['branch'])
        if len(prs) != 1: raise ValueError('PR creation unresolved')
        pr = prs[0]
        if (pr.get('state') != 'open' or pr.get('draft') is not True or pr.get('merged_at') or pr.get('auto_merge') or
            pr['head']['sha'] != commit or pr['head']['ref'] != q['branch'] or
            pr['head']['repo']['full_name'] != REPOSITORY or pr['base']['ref'] != 'main' or
            pr['base']['repo']['full_name'] != REPOSITORY or pr['title'] != TITLE or pr['body'] != q['body'] or
            remote.head(q['branch']) != commit or remote.main() != BASE):
            raise ValueError('Draft PR identity mismatch')
        result = dict(branch=q['branch'], commit=commit, tree=TREE, number=pr['number'], url=pr['html_url'])
        with self.runner.tx() as db:
            current = self.read(db, publication)
            if current['status'] == 'cancelled': raise ValueError('Cancelled; inspect remote state')
            db.execute("UPDATE publications SET status='completed', result=? WHERE id=?", (canonical(result), publication))
            self.event(db, publication, 'completed')
        return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class GitHub:
    """Only Git object creation, new refs and draft PRs; no update-ref capability."""
    def __init__(self, credential):
        if (credential.get('repository') != REPOSITORY or credential.get('security_reviewed') is not True or
            credential.get('permissions') != {'contents': 'write', 'pull_requests': 'write'} or
            not credential.get('operator_selected_identity') or not credential.get('token')):
            raise ValueError('Explicit reviewed narrow publisher credential required')
        self.token = credential['token']
        self.opener = urllib.request.build_opener(NoRedirect())

    def api(self, method, path, body=None):
        req = urllib.request.Request('https://api.github.com/repos/'+REPOSITORY+path,
            data=None if body is None else canonical(body).encode(), method=method,
            headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self.opener.open(req, timeout=30) as response:
                data = response.read(8*1024*1024+1)
                if len(data) > 8*1024*1024: raise ValueError('Oversized response')
                return json.loads(data)
        except Exception:
            raise ValueError('GitHub unavailable or permission/rate limit failure; reconcile before retry') from None

    def repository(self): return self.api('GET', '')['full_name']
    def main(self): return self.api('GET', '/git/ref/heads/main')['object']['sha']
    def commit(self, sha): return self.api('GET', '/git/commits/'+sha)
    def head(self, branch):
        rows = self.api('GET', '/git/matching-refs/heads/'+branch)
        if len(rows) > 1 or rows and rows[0]['ref'] != 'refs/heads/'+branch: raise ValueError('Ambiguous branch')
        return rows[0]['object']['sha'] if rows else None
    def prs(self, branch):
        rows = self.api('GET', '/pulls?state=all&per_page=100&head='+urllib.parse.quote('MZKZxyz:'+branch, safe=''))
        if len(rows) >= 100: raise ValueError('Unverifiable PR pagination')
        return rows
    def candidate(self, q, files, candidate):
        entries = []
        for name in ALLOWED:
            mode, data = candidate[name]
            blob = self.api('POST', '/git/blobs', dict(content=base64.b64encode(data).decode(), encoding='base64'))
            expected = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if blob['sha'] != expected: raise ValueError('Blob mismatch')
            entries.append(dict(path=name, mode='100755' if mode & 0o111 else '100644', type='blob', sha=expected))
        tree = self.api('POST', '/git/trees', dict(base_tree=self.commit(BASE)['tree']['sha'], tree=entries))
        if tree['sha'] != TREE: raise ValueError('Uploaded tree mismatch')
        # Verify the deterministic Git commit identity independently of GitHub.
        expected = publication_commit()
        commit = self.api('POST', '/git/commits', dict(message=q['message'], tree=TREE, parents=[BASE], author=IDENTITY, committer=IDENTITY))
        if commit['sha'] != expected: raise ValueError('Uploaded commit mismatch')
        return expected
    def create_branch(self, branch, commit):
        if branch != 'codex/issue-3-'+RUN: raise ValueError('Dedicated new branch required')
        self.api('POST', '/git/refs', dict(ref='refs/heads/'+branch, sha=commit))
    def create_pr(self, q):
        self.api('POST', '/pulls', dict(head=q['branch'], base='main', title=q['title'], body=q['body'],
                                     draft=True, maintainer_can_modify=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True); parser.add_argument('--state', required=True)
    parser.add_argument('--credential', required=True, help='Explicit operator-selected protected JSON file; never a CLI login')
    parser.add_argument('command', choices=['prepare', 'inspect', 'execute']); parser.add_argument('publication')
    args = parser.parse_args()
    credential = Path(args.credential)
    if credential.is_symlink() or not credential.is_file() or credential.stat().st_mode & 0o077:
        raise ValueError('Credential must be a private regular file')
    remote = GitHub(json.loads(credential.read_text()))
    publications = Publications(Runner(args.policy, args.state))
    if args.command == 'prepare':
        result = publications.prepare(args.publication)
        publication = digest(dict(run=args.publication, candidate=CANDIDATE))
        result['remote'] = publications.remote_inspect(publication, remote)
    elif args.command == 'execute': result = publications.execute(args.publication, remote)
    else:
        result = publications.remote_inspect(args.publication, remote)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        raise SystemExit('Publisher blocked. Inspect durable and remote state; no automatic fallback.')
