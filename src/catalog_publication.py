"""Human-authorized catalog draft publication; never executes candidate commands.

Policy, ledger, source and controller are operator-trusted, not signed evidence.
Use a separate publisher OS identity/host, never merely a same-user process.
"""
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

from src.local_catalog import PROTOCOL as TASK_PROTOCOL, REPOSITORIES, path_ok, resolve
from src.local_publication import Publications as LegacyPublications, NoRedirect, IDENTITY
from src.local_runner import (Runner, canonical, digest, environment, git, manifest,
                              materialize, snapshot, terminal_challenge)

PROTOCOL = 'catalog-draft-v1'
SHA = r'[0-9a-f]{40}'


def branch_ok(branch):
    return (isinstance(branch, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_/-]{0,150}', branch))
            and all(p and not p.startswith('-') for p in branch.split('/')))


def reconstruct(runner, run):
    """Rebuild from exact source objects and durable patch, without coding/QA."""
    if not re.fullmatch(r'[0-9a-f]{32}', run): raise ValueError('Invalid execution ID')
    r = runner.inspect(run)
    spec = r['spec']
    if spec.get('protocol') != TASK_PROTOCOL:
        raise ValueError('Only explicit local-catalog-v1 executions supported')
    policy = json.loads(runner.policy_path.read_text())
    expected, files = resolve(policy, spec['task_id'])
    if (r['id'] != run or r['state'] != 'validated' or expected != spec or
        digest(spec) != r['binding'] or not branch_ok(spec['branch'])):
        raise ValueError('Validated reviewed specification required')
    history = r['history']
    if ([h['event'] for h in history] != ['prepared', 'approved', 'claimed', 'validated'] or
        history[1].get('binding') != r['binding'] or
        any(type(h['at']) not in (int, float) or not math.isfinite(h['at']) for h in history) or
        [h['at'] for h in history] != sorted(h['at'] for h in history) or
        not history[0]['at'] <= history[1]['at'] < r['expires'] or
        not history[2]['at'] < r['expires'] or history[-1]['at'] >= r['deadline']):
        raise ValueError('Original authorization history invalid')
    usage = r.get('usage')
    if (not isinstance(usage, dict) or not {'input_tokens', 'cached_input_tokens', 'output_tokens'} <= usage.keys() or
        any(type(v) is not int or v < 0 for v in usage.values())):
        raise ValueError('Required controller usage evidence missing')
    qa = r['qa']
    commands = [['/usr/bin/git', 'diff', '--check', 'HEAD^', 'HEAD']]
    commands += [[policy['node'], *c['argv'][1:]] for c in spec['checks']]
    if ([q['name'] for q in qa] != ['diff', *[c['name'] for c in spec['checks']], 'candidate'] or
        any(type(q['code']) is not int or q['code'] != 0 or q['reason'] is not None for q in qa) or
        [q['command'] for q in qa[:-1]] != commands or
        any(not isinstance(q.get(k), str) for q in qa[:-1] for k in ('stdout', 'stderr'))):
        raise ValueError('Complete successful independent QA records required')
    artifact = qa[-1]
    if (artifact['input_hash'] != spec['input_hash'] or artifact['candidate_hash'] != r['candidate_hash'] or
        not re.fullmatch(SHA, artifact['candidate_tree']) or
        not re.fullmatch(SHA, artifact['candidate_revision'])):
        raise ValueError('Candidate evidence mismatch')
    patch = artifact['patch']
    if not isinstance(patch, str) or not patch or len(patch.encode()) > 8*1024*1024:
        raise ValueError('Invalid durable patch')
    with tempfile.TemporaryDirectory(prefix='catalog-publication-') as work:
        root = Path(work)
        materialize(files, root); git(root, 'init', '-q'); git(root, 'add', '--all', '--force')
        base_tree = git(root, 'write-tree').decode().strip()
        source = policy['repositories'][spec['repo']]['source']
        if base_tree != git(source, 'rev-parse', spec['source']+'^{tree}').decode().strip():
            raise ValueError('Trusted source tree mismatch')
        result = subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-C', work,
                                 'apply', '--index', '--binary', '--whitespace=error', '-'],
                                input=patch.encode(), env=environment(), capture_output=True, timeout=30)
        if result.returncode: raise ValueError('Stored patch does not apply exactly')
        for entry in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
            if not entry: continue
            metadata, name = entry.split(b'\t'); mode = metadata.split()[0]
            if mode not in (b'100644', b'100755') or name.decode() not in files:
                raise ValueError('Unsafe patched entry')
            (root/name.decode()).chmod(int(mode, 8) & 0o777)
        candidate = {k:v for k,v in snapshot(root).items() if not k.startswith('.git/')}
        changed = sorted(k for k in files.keys() | candidate.keys() if files.get(k) != candidate.get(k))
        if (not changed or changed != r['files'] or not set(changed) <= set(spec['allowed']) or
            files.keys() != candidate.keys() or manifest(candidate) != r['candidate_hash'] or
            git(root, 'write-tree').decode().strip() != artifact['candidate_tree'] or
            git(root, 'diff', '--cached', '--binary', '--full-index', base_tree, '--').decode() != patch):
            raise ValueError('Patch, candidate manifest, changed files or tree mismatch')
    return r, files, candidate


def commit_identity(tree, base, message):
    raw = (f'tree {tree}\nparent {base}\nauthor {IDENTITY["name"]} <{IDENTITY["email"]}> 1792627200 +0000\n'
           f'committer {IDENTITY["name"]} <{IDENTITY["email"]}> 1792627200 +0000\n\n'+message).encode()
    return hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


class Publications(LegacyPublications):
    """Shared SQLite schema/lock/challenge, explicit new request protocol only."""
    def read(self, db, publication):
        p = super().read(db, publication)
        if p['request'].get('protocol') != PROTOCOL:
            raise ValueError('Unsupported catalog publication protocol')
        return p

    def request(self, r, expires):
        spec, artifact = r['spec'], r['qa'][-1]
        title = 'Reviewed catalog task: '+spec['task_id']
        body = (f'Issue: {spec["issue_snapshot"]["html_url"]}\n\n'
                f'Execution: {r["id"]}\nTask binding: {r["binding"]}\n'
                f'Policy digest: {spec["policy"]}\nSource: {spec["source"]}\n'
                f'Validated local revision: {artifact["candidate_revision"]}\n'
                f'Candidate manifest: {r["candidate_hash"]}\nTree: {artifact["candidate_tree"]}\n'
                f'Complete execution evidence SHA-256: {digest(r)}\n'
                f'Independent QA SHA-256: {digest(r["qa"])}\n'
                'Recorded controller checks succeeded. Human review required; no merge or deployment authorized.\n\n'
                'Changed files:\n'+canonical(r['files'])+'\n\nIndependent QA records:\n```json\n'+
                json.dumps(r['qa'][:-1], indent=2, ensure_ascii=True)+'\n```\n')
        if len(body.encode()) > 60000: raise ValueError('QA evidence exceeds reviewable PR body limit')
        message = title+'\n\nExecution evidence: '+digest(r)+'\n'
        return dict(protocol=PROTOCOL, run=r['id'], spec=spec, artifact=digest(r),
                    input_hash=spec['input_hash'], candidate_hash=r['candidate_hash'],
                    tree=artifact['candidate_tree'], files=r['files'],
                    approval=digest(r['history']), qa=digest(r['qa']),
                    base=spec['source'], base_branch=spec['branch'], repository=spec['task']['repository'],
                    branch='codex/catalog-'+r['id'], title=title, body=body,
                    commit=commit_identity(artifact['candidate_tree'], spec['source'], message),
                    action='create-new-branch-and-draft-pr', expires=expires,
                    operator=os.getuid(), author=IDENTITY, message=message, draft=True,
                    provenance_limit='trusted operator ledger; no privileged-tamper signature')

    def prepare(self, run):
        r, _, _ = reconstruct(self.runner, run)
        request = self.request(r, self.runner.clock()+600)
        publication = digest(dict(protocol=PROTOCOL, run=run))
        with self.runner.tx() as db:
            row = db.execute('SELECT id FROM publications WHERE run=?', (run,)).fetchone()
            if row:
                return dict(self.read(db, row[0]), id=row[0], patch=r['qa'][-1]['patch'], qa=r['qa'])
            if self.runner.state.joinpath('STOP').exists(): raise ValueError('Persistent kill switch active')
            db.execute('INSERT INTO publications VALUES (?,?,?,?,?,?)',
                       (publication, run, canonical(request), digest(request), 'prepared', '{}'))
            self.event(db, publication, 'prepared')
        return dict(self.inspect(publication), id=publication, patch=r['qa'][-1]['patch'], qa=r['qa'])

    def check(self, p, expiry=True):
        q = p['request']
        if q.get('protocol') != PROTOCOL: raise ValueError('Unsupported catalog publication protocol')
        if p['status'] == 'cancelled' or self.runner.state.joinpath('STOP').exists():
            raise ValueError('Publication cancelled or STOP active')
        if digest(q) != p['binding']: raise ValueError('Publication request altered')
        if expiry and q['expires'] <= self.runner.clock(): raise ValueError('Publication approval expired')
        r, files, candidate = reconstruct(self.runner, q['run'])
        if q != self.request(r, q['expires']): raise ValueError('Artifact or publication action changed')
        if (not p['history'] or not p['history'][0]['at'] < q['expires'] <= p['history'][0]['at']+600 or
            any(h['actor'] != q['operator'] for h in p['history']) or
            any(h['at'] >= q['expires'] for h in p['history'] if h['event'] != 'completed')):
            raise ValueError('Publication operator or expiration audit invalid')
        events = [h['event'] for h in p['history']]
        # Successful preflights can repeat, but approval and claims cannot.
        events = [e for e in events if e != 'remote-preflight']
        sequence = ['prepared', 'approved', 'publishing', 'branch-requested', 'pr-requested', 'completed']
        if p['status'] not in sequence or events != sequence[:sequence.index(p['status'])+1]:
            raise ValueError('Publication authorization audit history invalid')
        return r, files, candidate

    def remote_state(self, q, remote):
        if remote.repository() != q['repository'] or remote.base(q['base_branch']) != q['base']:
            raise ValueError('Repository identity or destination base changed')
        return remote.head(q['branch']), remote.prs(q['branch'])

    def remote_inspect(self, publication, remote):
        p = self.inspect(publication); self.check(p, expiry=p['status'] != 'completed')
        q = p['request']; head, prs = self.remote_state(q, remote)
        if p['status'] == 'prepared':
            if head is not None or prs: raise ValueError('Remote branch or PR already exists')
            with self.runner.tx() as db:
                current = self.read(db, publication); self.check(current)
                if current['status'] != 'prepared': raise ValueError('Publication status changed')
                db.execute('UPDATE publications SET result=? WHERE id=?',
                           (canonical(dict(preflight_binding=p['binding'], checked=self.runner.clock())), publication))
                self.event(db, publication, 'remote-preflight')
        elif p['status'] == 'completed':
            self.verify_commit(q, remote); self.verify_pr(q, head, prs)
        return dict(repository=q['repository'], base=q['base'], branch=head, prs=prs)

    def verify_commit(self, q, remote):
        info = remote.commit(q['commit'])
        if (info['sha'] != q['commit'] or info['tree']['sha'] != q['tree'] or
            [x['sha'] for x in info['parents']] != [q['base']] or
            info['message'].rstrip('\n') != q['message'].rstrip('\n') or
            any(info[k] != q['author'] for k in ('author', 'committer'))):
            raise ValueError('Remote commit identity mismatch')

    def verify_pr(self, q, head, prs):
        if len(prs) != 1: raise ValueError('PR creation unresolved or conflicting')
        pr = prs[0]
        if (head != q['commit'] or pr.get('state') != 'open' or pr.get('draft') is not True or
            pr.get('merged_at') or pr.get('auto_merge') or pr.get('maintainer_can_modify') is not False or
            pr['head']['sha'] != q['commit'] or pr['head']['ref'] != q['branch'] or
            pr['head']['repo']['full_name'] != q['repository'] or
            pr['base']['ref'] != q['base_branch'] or pr['base']['sha'] != q['base'] or
            pr['base']['repo']['full_name'] != q['repository'] or
            pr['title'] != q['title'] or pr['body'] != q['body'] or
            type(pr['number']) is not int or pr['number'] <= 0 or
            pr['html_url'] != 'https://github.com/'+q['repository']+'/pull/'+str(pr['number'])):
            raise ValueError('Remote draft PR identity mismatch')
        return dict(branch=q['branch'], commit=q['commit'], tree=q['tree'], number=pr['number'], url=pr['html_url'])

    def transition(self, publication, old, new):
        with self.runner.tx() as db:
            p = self.read(db, publication); self.check(p)
            if p['status'] != old: raise ValueError('Publication status changed')
            db.execute('UPDATE publications SET status=? WHERE id=?', (new, publication))
            self.event(db, publication, new)

    def _execute(self, publication, remote):
        p = self.inspect(publication)
        _, files, candidate = self.check(p, expiry=p['status'] != 'completed')
        q, status = p['request'], p['status']
        if status not in ('approved', 'publishing', 'branch-requested', 'pr-requested', 'completed'):
            raise ValueError('Separate unused publication authorization required')
        head, prs = self.remote_state(q, remote)
        if status in ('approved', 'publishing') and (head is not None or prs):
            raise ValueError('Branch or PR collision before durable branch claim')
        if head not in (None, q['commit']): raise ValueError('Unexpected remote commit')
        if status in ('branch-requested', 'pr-requested', 'completed'):
            if status == 'branch-requested' and prs: raise ValueError('PR appeared before durable PR claim')
            if status in ('pr-requested', 'completed') and head is None:
                raise ValueError('Claimed remote branch disappeared')
            if prs: self.verify_pr(q, head, prs)
            if status == 'pr-requested' and not prs:
                raise ValueError('Ambiguous PR creation; reconcile manually, never repeat POST')
        if status == 'completed':
            self.verify_commit(q, remote)
            return self.verify_pr(q, head, prs)
        if status == 'approved':
            self.transition(publication, 'approved', 'publishing'); status = 'publishing'
        # Every individual API write checks durable cancellation, expiry and evidence.
        def guard():
            current = self.inspect(publication); self.check(current)
            current_head, current_prs = self.remote_state(q, remote)
            if (current_prs or current_head not in (None, q['commit']) or
                current['status'] == 'publishing' and current_head is not None or
                current['status'] == 'pr-requested' and current_head != q['commit']):
                raise ValueError('Remote conflict before write')
        if head is None:
            guard()
            if remote.candidate(q, files, candidate, guard) != q['commit']:
                raise ValueError('Uploaded commit mismatch')
        self.verify_commit(q, remote)
        if status == 'publishing':
            head, prs = self.remote_state(q, remote)
            if head is not None or prs: raise ValueError('Remote collision before branch claim')
            self.transition(publication, 'publishing', 'branch-requested'); status = 'branch-requested'
        head, prs = self.remote_state(q, remote)
        if head is None:
            if prs or status != 'branch-requested': raise ValueError('Remote branch disappeared')
            guard(); remote.create_branch(q, guard)
        elif head != q['commit']: raise ValueError('Remote branch moved')
        head, prs = self.remote_state(q, remote)
        if head != q['commit']: raise ValueError('Remote branch verification failed')
        if status == 'branch-requested':
            if prs: raise ValueError('PR appeared before durable PR claim')
            self.transition(publication, 'branch-requested', 'pr-requested')
            guard(); remote.create_pr(q, guard)
        # An ambiguous POST is never repeated, even if the list is empty.
        head, prs = self.remote_state(q, remote)
        result = self.verify_pr(q, head, prs)
        self.verify_commit(q, remote)
        with self.runner.tx() as db:
            current = self.read(db, publication); self.check(current)
            if current['status'] != 'pr-requested': raise ValueError('Publication status changed')
            db.execute("UPDATE publications SET status='completed', result=? WHERE id=?", (canonical(result), publication))
            self.event(db, publication, 'completed')
        return result


class GitHub:
    """Narrow API surface; no ref updates, merges, approvals or deployments."""
    def __init__(self, credential, repository):
        if (repository not in REPOSITORIES.values() or credential.get('repository') != repository or
            credential.get('security_reviewed') is not True or
            credential.get('permissions') != {'contents': 'write', 'pull_requests': 'write'} or
            not isinstance(credential.get('operator_selected_identity'), str) or
            not credential['operator_selected_identity'].strip() or
            not isinstance(credential.get('token'), str) or not credential['token']):
            raise ValueError('Explicit reviewed repository-restricted publisher credential required')
        self.identity, self.token = repository, credential['token']
        self.opener = urllib.request.build_opener(NoRedirect())

    def api(self, method, path, body=None):
        reads = (path == '' or re.fullmatch(r'/git/ref/heads/[A-Za-z0-9_/-]+', path) or
                 re.fullmatch(r'/git/matching-refs/heads/codex/catalog-[0-9a-f]{32}', path) or
                 re.fullmatch(r'/git/commits/'+SHA, path) or
                 re.fullmatch(r'/pulls\?state=all&per_page=100&head=[A-Za-z0-9%_-]+', path))
        if not ((method == 'GET' and reads and body is None) or
                (method == 'POST' and path in ('/git/blobs', '/git/trees', '/git/commits', '/git/refs', '/pulls'))):
            raise ValueError('Unsupported publisher API operation')
        if method == 'POST': self.write_payload(path, body)
        req = urllib.request.Request('https://api.github.com/repos/'+self.identity+path,
            data=None if body is None else canonical(body).encode(), method=method,
            headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self.opener.open(req, timeout=30) as response:
                data = response.read(8*1024*1024+1)
                if len(data) > 8*1024*1024: raise ValueError('Oversized response')
                return json.loads(data)
        except Exception:
            raise ValueError('GitHub unavailable; inspect durable and remote state before recovery') from None

    def write_payload(self, path, body):
        if not isinstance(body, dict): raise ValueError('Invalid publisher payload')
        if path == '/git/refs':
            if set(body) != {'ref', 'sha'} or not body['ref'].startswith('refs/heads/'):
                raise ValueError('Only new feature refs supported')
            self.feature(body['ref'][len('refs/heads/'):])
            valid = bool(re.fullmatch(SHA, body['sha']))
        elif path == '/pulls':
            if set(body) != {'head', 'base', 'title', 'body', 'draft', 'maintainer_can_modify'}:
                raise ValueError('Only draft PR creation supported')
            self.feature(body['head'])
            valid = (body['draft'] is True and body['maintainer_can_modify'] is False and
                     branch_ok(body['base']) and body['head'] != body['base'] and
                     isinstance(body['title'], str) and isinstance(body['body'], str))
        elif path == '/git/blobs':
            valid = set(body) == {'content', 'encoding'} and body['encoding'] == 'base64'
        elif path == '/git/trees':
            valid = (set(body) == {'base_tree', 'tree'} and re.fullmatch(SHA, body['base_tree']) and
                     isinstance(body['tree'], list) and bool(body['tree']) and
                     all(set(e) == {'path', 'mode', 'type', 'sha'} and path_ok(e['path']) and
                         e['mode'] in ('100644', '100755') and e['type'] == 'blob' and
                         re.fullmatch(SHA, e['sha']) for e in body['tree']))
        else:
            valid = (set(body) == {'message', 'tree', 'parents', 'author', 'committer'} and
                     isinstance(body['message'], str) and re.fullmatch(SHA, body['tree']) and
                     isinstance(body['parents'], list) and len(body['parents']) == 1 and
                     re.fullmatch(SHA, body['parents'][0]) and body['author'] == IDENTITY and
                     body['committer'] == IDENTITY)
        if not valid: raise ValueError('Unsupported publisher write payload')

    def repository(self): return self.api('GET', '')['full_name']
    def base(self, branch):
        if not branch_ok(branch): raise ValueError('Invalid reviewed base branch')
        return self.api('GET', '/git/ref/heads/'+branch)['object']['sha']
    def commit(self, sha):
        if not re.fullmatch(SHA, sha): raise ValueError('Invalid commit')
        return self.api('GET', '/git/commits/'+sha)
    def head(self, branch):
        self.feature(branch)
        rows = self.api('GET', '/git/matching-refs/heads/'+branch)
        if len(rows) > 1 or rows and rows[0]['ref'] != 'refs/heads/'+branch:
            raise ValueError('Ambiguous branch')
        return rows[0]['object']['sha'] if rows else None
    def prs(self, branch):
        self.feature(branch)
        rows = self.api('GET', '/pulls?state=all&per_page=100&head='+
                        urllib.parse.quote(self.identity.split('/')[0]+':'+branch, safe=''))
        if len(rows) >= 100: raise ValueError('Unverifiable PR pagination')
        return rows
    @staticmethod
    def feature(branch):
        if not re.fullmatch(r'codex/catalog-[0-9a-f]{32}', branch):
            raise ValueError('Dedicated new catalog branch required')
    def action(self, q):
        if (q.get('protocol') != PROTOCOL or q['repository'] != self.identity or
            q['draft'] is not True or not branch_ok(q['base_branch']) or
            q['branch'] == q['base_branch'] or q['author'] != IDENTITY or
            q['commit'] != commit_identity(q['tree'], q['base'], q['message'])):
            raise ValueError('Unsupported publication action')
        self.feature(q['branch'])
    def candidate(self, q, files, candidate, guard):
        self.action(q)
        changed = sorted(k for k in files.keys() | candidate.keys() if files.get(k) != candidate.get(k))
        if changed != q['files'] or manifest(candidate) != q['candidate_hash']:
            raise ValueError('Candidate changed at transport boundary')
        entries = []
        for name in changed:
            mode, data = candidate[name]
            guard()
            blob = self.api('POST', '/git/blobs', dict(content=base64.b64encode(data).decode(), encoding='base64'))
            expected = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if blob['sha'] != expected: raise ValueError('Blob mismatch')
            entries.append(dict(path=name, mode='100755' if mode & 0o111 else '100644', type='blob', sha=expected))
        guard()
        base_tree = self.commit(q['base'])['tree']['sha']
        guard()
        tree = self.api('POST', '/git/trees', dict(base_tree=base_tree, tree=entries))
        if tree['sha'] != q['tree']: raise ValueError('Tree mismatch')
        guard()
        commit = self.api('POST', '/git/commits', dict(message=q['message'], tree=q['tree'], parents=[q['base']],
                                                   author=q['author'], committer=q['author']))
        if commit['sha'] != q['commit']: raise ValueError('Commit mismatch')
        return commit['sha']
    def create_branch(self, q, guard):
        self.action(q); guard()
        self.api('POST', '/git/refs', dict(ref='refs/heads/'+q['branch'], sha=q['commit']))
    def create_pr(self, q, guard):
        self.action(q); guard()
        self.api('POST', '/pulls', dict(head=q['branch'], base=q['base_branch'], title=q['title'], body=q['body'],
                                     draft=True, maintainer_can_modify=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True); parser.add_argument('--state', required=True)
    parser.add_argument('--credential', help='Private operator-selected JSON; required for remote operations')
    parser.add_argument('command', choices=['prepare', 'inspect', 'approve', 'cancel', 'preflight', 'execute', 'verify'])
    parser.add_argument('id', help='Execution ID for prepare; publication ID otherwise')
    args = parser.parse_args()
    publisher = Publications(Runner(args.policy, args.state))
    if args.command == 'prepare': result = publisher.prepare(args.id)
    elif args.command == 'inspect': result = publisher.inspect(args.id)
    elif args.command == 'cancel': result = publisher.cancel(args.id)
    elif args.command == 'approve':
        p = publisher.inspect(args.id); print(json.dumps(p, indent=2, ensure_ascii=True))
        result = publisher.approve(args.id, terminal_challenge('PUBLISH '+p['binding']))
    else:
        if not args.credential: raise ValueError('Separate publisher credential required')
        path = Path(args.credential)
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError('Credential must be a private regular file')
        p = publisher.inspect(args.id); publisher.check(p, expiry=p['status'] != 'completed')
        if args.command == 'verify' and p['status'] != 'completed':
            raise ValueError('Read-only result verification requires a completed publication')
        remote = GitHub(json.loads(path.read_text()), p['request']['repository'])
        result = (publisher.execute(args.id, remote) if args.command == 'execute'
                  else publisher.remote_inspect(args.id, remote))
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        raise SystemExit('Catalog publisher blocked. Inspect durable and remote state; no fallback or automatic renewal.')
