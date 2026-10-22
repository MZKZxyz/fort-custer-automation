"""Offline integration: disposable Git input, fake CLI, fake GitHub service."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch, MagicMock

import test_local_runner as fixtures
from test_local_runner import FAKE
from src.local_runner import LocalCLI, Runner, git, terminal_challenge
from src import local_publication as pub


class Remote:
    def __init__(self):
        self.branch = None; self.rows = []; self.calls = []; self.fail = None
        self.base = pub.BASE
    def repository(self): return pub.REPOSITORY
    def main(self): return self.base
    def commit(self, sha):
        return dict(sha=sha, tree=dict(sha=pub.TREE), parents=[dict(sha=pub.BASE)])
    def candidate(self, q, files, candidate):
        self.calls.append('objects'); return pub.publication_commit()
    def head(self, branch): return self.branch
    def prs(self, branch): return copy.deepcopy(self.rows)
    def create_branch(self, branch, commit):
        self.calls.append('branch')
        if self.fail == 'branch-before': raise ValueError('network outage')
        self.branch = commit
        if self.fail == 'branch-after': raise ValueError('lost response')
    def create_pr(self, q):
        self.calls.append('pr')
        if self.fail == 'pr-before': raise ValueError('rate limit')
        self.rows = [dict(state='open', draft=True, merged_at=None, auto_merge=None,
            head=dict(sha=self.branch, ref=q['branch'], repo=dict(full_name=pub.REPOSITORY)),
            base=dict(ref='main', repo=dict(full_name=pub.REPOSITORY)), title=q['title'], body=q['body'],
            number=17, html_url='https://github.com/'+pub.REPOSITORY+'/pull/17')]
        if self.fail == 'pr-after': raise ValueError('lost response')


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LocalRunnerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        source = f.root/'source'
        with (source/'test/analyzer.test.js').open('a') as output:
            output.write(''.join(f"test('case{i}',()=>{{}});\n" for i in range(13)))
        git(source, 'add', '.'); git(source, '-c', 'user.name=Fixture', '-c', 'user.email=f@local', 'commit', '-qm', '14 tests')
        f.config['repositories']['fort-custer-server']['sha'] = git(source, 'rev-parse', 'HEAD').decode().strip()
        f.write_policy(); f.runner = Runner(f.path, f.config['state'], lambda:f.now)
        r = f.approved(); self.run = f.runner.execute(r['id']); self.assertEqual(self.run['state'], 'validated', self.run)
        # Synthetic durable QA evidence; publication never reruns candidate code.
        self.run['qa'][3]['stdout'] = '# tests 14\n# pass 14\n# fail 0\n'
        with f.runner.tx() as db: f.runner.save(db, self.run)
        qa = self.run['qa'][-1]
        for key, value in dict(RUN=r['id'], BASE=r['spec']['source'], CANDIDATE=self.run['candidate_hash'],
                               TREE=qa['candidate_tree'], REVISION=qa['candidate_revision']).items():
            ctx = patch.object(pub, key, value); ctx.start(); self.addCleanup(ctx.stop)
        self.runner = f.runner; self.publisher = pub.Publications(self.runner)
        self.remote = Remote()
        self.prepared = self.publisher.prepare(self.run['id']); self.id = self.prepared['id']

    def approve(self):
        self.publisher.remote_inspect(self.id, self.remote)
        return self.publisher.approve(self.id, 'PUBLISH '+self.prepared['binding'])
    def execute(self): return self.publisher.execute(self.id, self.remote)
    def alter_run(self, change):
        with self.runner.tx() as db:
            r = self.runner.read(db, self.run['id']); change(r); self.runner.save(db, r)

    def test_valid_and_duplicate_restart(self):
        self.approve(); first = self.execute()
        self.publisher = pub.Publications(Runner(self.fixture.path, self.fixture.config['state'], lambda:self.fixture.now))
        self.assertEqual(self.execute(), first)
        self.assertEqual(self.remote.calls.count('pr'), 1)
        self.assertEqual(self.remote.calls.count('branch'), 1)
        self.assertEqual(first['tree'], pub.TREE)
        with self.assertRaises(ValueError): self.approve()
        self.assertEqual(self.publisher.prepare(self.run['id'])['status'], 'completed')

    def test_missing_forged_and_coding_approval(self):
        with self.assertRaises(ValueError): self.execute()
        for answer in ('yes', 'PUBLISH '+'a'*64, 'APPROVE '+self.run['binding']):
            with self.assertRaises(ValueError): self.publisher.approve(self.id, answer)
        self.assertEqual(self.remote.calls, [])

    def test_remote_preflight_required(self):
        with self.assertRaises(ValueError): self.publisher.approve(self.id, 'PUBLISH '+self.prepared['binding'])
        self.remote.branch = 'a'*40
        with self.assertRaises(ValueError): self.publisher.remote_inspect(self.id, self.remote)

    def test_expired(self):
        self.approve(); self.fixture.now += 601
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])

    def test_altered_request(self):
        self.approve()
        with self.runner.tx() as db:
            q = self.prepared['request']; q['repository'] = 'attacker/repository'
            db.execute('UPDATE publications SET request=? WHERE id=?', (json.dumps(q), self.id))
        with self.assertRaises(ValueError): self.execute()

    def test_changed_artifacts_fail_closed(self):
        self.approve()
        original = copy.deepcopy(self.run)
        mutations = [lambda r:r.update(candidate_hash='0'*64),
            lambda r:r['qa'][-1].update(patch=r['qa'][-1]['patch']+'bad patch\n'),
            lambda r:r['qa'][-1].update(candidate_tree='0'*40),
            lambda r:r.update(files=['unapproved.txt']), lambda r:r['qa'].pop(0),
            lambda r:r['spec'].update(source='0'*40), lambda r:r['spec'].update(repo='other'),
            lambda r:r['qa'][3].update(stdout='missing test evidence'),
            lambda r:r['qa'][1].update(command=['/untrusted/node'])]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.runner.tx() as db: self.runner.save(db, copy.deepcopy(original))
                self.alter_run(mutation)
                with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])

    def test_reconstruction_detects_rehashed_bad_patch(self):
        # Even a coordinated change to the ordinary ledger hashes cannot evade
        # the independently pinned experiment candidate tree/hash allowlist.
        self.alter_run(lambda r:r['qa'][-1].update(patch=r['qa'][-1]['patch'].replace('right', 'wrong')))
        with self.assertRaises(ValueError): pub.reconstruct(self.runner, self.run['id'])

    def test_base_advanced_wrong_repository_remote_change(self):
        self.approve(); self.remote.base = 'a'*40
        with self.assertRaises(ValueError): self.execute()
        self.remote.base = pub.BASE
        with patch.object(self.remote, 'repository', return_value='attacker/repo'):
            with self.assertRaises(ValueError): self.execute()
        self.remote.branch = 'b'*40
        with self.assertRaises(ValueError): self.execute()
        self.assertNotIn('branch', self.remote.calls)

    def test_interrupted_branch_creation_reconciles(self):
        self.approve(); self.remote.fail = 'branch-after'
        with self.assertRaises(ValueError): self.execute()
        self.remote.fail = None
        self.publisher = pub.Publications(self.runner)
        self.execute(); self.assertEqual(self.remote.calls.count('branch'), 1)

    def test_outage_before_branch_can_resume(self):
        self.approve(); self.remote.fail = 'branch-before'
        with self.assertRaises(ValueError): self.execute()
        self.remote.fail = None; self.execute()
        self.assertEqual(self.remote.calls.count('pr'), 1)

    def test_pr_response_lost_reconciles(self):
        self.approve(); self.remote.fail = 'pr-after'
        with self.assertRaises(ValueError): self.execute()
        self.remote.fail = None; self.execute()
        self.assertEqual(self.remote.calls.count('pr'), 1)

    def test_ambiguous_pr_never_retries_post(self):
        self.approve(); self.remote.fail = 'pr-before'
        with self.assertRaises(ValueError): self.execute()
        self.remote.fail = None
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls.count('pr'), 1)

    def test_cancel_and_stop(self):
        self.approve(); self.publisher.cancel(self.id)
        with self.assertRaises(ValueError): self.execute()
        self.runner.cancel()
        with self.assertRaises(ValueError): self.publisher.remote_inspect(self.id, self.remote)
        self.assertEqual(self.remote.calls, [])

    def test_remote_pr_must_be_exact_draft(self):
        self.approve(); self.execute(); self.remote.rows[0]['draft'] = False
        with self.assertRaises(ValueError): self.execute()

    def test_credentials_require_explicit_selection(self):
        for config in ({}, dict(repository=pub.REPOSITORY, token='fake'),
                       dict(repository='wrong/repo', security_reviewed=True, token='fake')):
            with self.assertRaises(ValueError): pub.GitHub(config)
        from src.local_runner import environment
        with patch.dict('os.environ', {'GITHUB_TOKEN':'fake-secret', 'GH_TOKEN':'fake-secret'}):
            self.assertNotIn('GITHUB_TOKEN', environment())
            self.assertNotIn('GH_TOKEN', environment())

    def test_transport_only_creates_new_refs_and_draft_pr(self):
        remote = pub.GitHub(dict(repository=pub.REPOSITORY, security_reviewed=True,
            permissions={'contents':'write', 'pull_requests':'write'}, operator_selected_identity='test-app', token='fake'))
        calls = []
        remote.api = lambda method,path,body=None: calls.append((method,path,body))
        remote.create_branch('codex/issue-3-'+pub.RUN, 'a'*40)
        remote.create_pr(self.prepared['request'])
        with self.assertRaises(ValueError): remote.create_branch('main', 'a'*40)
        self.assertEqual([x[:2] for x in calls], [('POST','/git/refs'), ('POST','/pulls')])
        self.assertTrue(calls[1][2]['draft'])
        self.assertNotIn('Closes', calls[1][2]['body'])

    def test_git_object_transport_checks_every_identity(self):
        remote = pub.GitHub(dict(repository=pub.REPOSITORY, security_reviewed=True,
            permissions={'contents':'write', 'pull_requests':'write'}, operator_selected_identity='test-app', token='fake'))
        r, files, candidate = pub.reconstruct(self.runner, self.run['id'])
        calls = []
        def api(method, path, payload=None):
            calls.append((method, path))
            if path == '/git/blobs':
                import base64
                data = base64.b64decode(payload['content'])
                return dict(sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest())
            if path == '/git/trees': return dict(sha=pub.TREE)
            if path == '/git/commits': return dict(sha=pub.publication_commit())
            return dict(tree=dict(sha='fixture-base-tree'))
        remote.api = api
        self.assertEqual(remote.candidate(self.prepared['request'], files, candidate), pub.publication_commit())
        self.assertEqual(calls.count(('POST','/git/blobs')), 2)
        for bad_path in ('/git/blobs', '/git/trees', '/git/commits'):
            remote.api = lambda method,path,payload=None: dict(sha='0'*40) if path == bad_path else api(method,path,payload)
            with self.assertRaises(ValueError): remote.candidate(self.prepared['request'], files, candidate)

    def test_api_failure_redacts_credential_and_does_not_retry(self):
        remote = pub.GitHub(dict(repository=pub.REPOSITORY, security_reviewed=True,
            permissions={'contents':'write', 'pull_requests':'write'}, operator_selected_identity='test-app', token='fake-secret'))
        remote.opener = MagicMock()
        remote.opener.open.side_effect = OSError('fake-secret permission revoked')
        with self.assertRaises(ValueError) as caught: remote.repository()
        self.assertNotIn('fake-secret', str(caught.exception))
        remote.opener.open.assert_called_once()

    def test_stop_between_network_operations(self):
        self.approve()
        original = self.remote.candidate
        def cancel_after_objects(*args):
            result = original(*args); self.publisher.cancel(self.id); return result
        self.remote.candidate = cancel_after_objects
        with self.assertRaises(ValueError): self.execute()
        self.assertNotIn('branch', self.remote.calls)

    def test_unapproved_file_patch_rejected(self):
        self.alter_run(lambda r:r['qa'][-1].update(patch=r['qa'][-1]['patch']+
            'diff --git a/unapproved.txt b/unapproved.txt\nnew file mode 100644\n'
            '--- /dev/null\n+++ b/unapproved.txt\n@@ -0,0 +1 @@\n+unauthorized\n'))
        with self.assertRaises(ValueError): pub.reconstruct(self.runner, self.run['id'])


class CompatibilityTests(unittest.TestCase):
    def test_terminal_separate_handles(self):
        inp = MagicMock(); inp.isatty.return_value=True; inp.readline.return_value='APPROVE exact\n'
        out = MagicMock(); out.isatty.return_value=True
        with patch('builtins.open', side_effect=[context(inp), context(out)]) as opening:
            self.assertEqual(terminal_challenge('APPROVE exact'), 'APPROVE exact')
        self.assertEqual([x.args for x in opening.call_args_list], [('/dev/tty','r'),('/dev/tty','w')])
        out.flush.assert_called_once()
        with patch('builtins.open', side_effect=OSError('no tty')):
            with self.assertRaises(OSError): terminal_challenge('anything')
        inp.isatty.return_value=False
        with patch('builtins.open', side_effect=[context(inp), context(out)]):
            with self.assertRaises(ValueError): terminal_challenge('anything')

    def test_telemetry_required_and_additional_counters(self):
        fixture = fixtures.LocalRunnerTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        valid = dict(input_tokens=3, cached_input_tokens=0, output_tokens=4)
        values = [dict(valid, reasoning_output_tokens=2, cache_write_input_tokens=1), {k:v for k,v in valid.items() if k!='input_tokens'},
                  dict(valid, input_tokens=-1), dict(valid, output_tokens=1.5), dict(valid, cached_input_tokens=True),
                  dict(valid, input_tokens=None), dict(valid, future_counter='bad')]
        for i, usage in enumerate(values):
            code = FAKE.replace("{'input_tokens':3,'cached_input_tokens':0,'output_tokens':4}", repr(usage))
            fixture.fake.write_text(code)
            fixture.config['cli_sha256'] = hashlib.sha256(fixture.fake.read_bytes()).hexdigest()
            runner = LocalCLI(fixture.config)
            if i == 0:
                self.assertEqual(runner.run(fixture.root/'source', 'task', lambda:False, 10), valid)
            else:
                with self.assertRaises(ValueError): runner.run(fixture.root/'source', 'task', lambda:False, 10)


def context(value):
    result=MagicMock(); result.__enter__.return_value=value; return result
