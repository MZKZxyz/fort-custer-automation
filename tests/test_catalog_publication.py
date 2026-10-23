"""Offline publication uses synthetic sources, mock coding and fake GitHub only."""
import base64
import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
import io
from contextlib import redirect_stdout
from unittest.mock import patch, MagicMock

import test_local_catalog as fixtures
from src import catalog_publication as pub
from src import local_publication as legacy
from src.local_runner import LocalCLI, Runner, canonical, digest, git, manifest, source_files


class Remote:
    def __init__(self, q):
        self.q = q; self.base_sha = q['base']; self.identity = q['repository']
        self.branch = None; self.rows = []; self.calls = []; self.fail = None
    def repository(self): return self.identity
    def base(self, branch):
        assert branch == self.q['base_branch']
        return self.base_sha
    def head(self, branch):
        assert branch == self.q['branch']
        return self.branch
    def prs(self, branch): return copy.deepcopy(self.rows)
    def commit(self, sha):
        return dict(sha=sha, tree=dict(sha=self.q['tree']), parents=[dict(sha=self.q['base'])],
                    author=self.q['author'], committer=self.q['author'], message=self.q['message'])
    def candidate(self, q, files, candidate, guard):
        guard(); self.calls.append('objects')
        assert manifest(candidate) == q['candidate_hash']
        return q['commit']
    def create_branch(self, q, guard):
        guard(); self.calls.append('branch')
        if self.fail == 'branch-before': raise ValueError('outage')
        self.branch = q['commit']
        if self.fail == 'branch-after': raise ValueError('lost response')
    def create_pr(self, q, guard):
        guard(); self.calls.append('pr')
        if self.fail == 'pr-before': raise ValueError('ambiguous outage')
        self.rows = [dict(state='open', draft=True, merged_at=None, auto_merge=None, maintainer_can_modify=False,
            head=dict(sha=self.branch, ref=q['branch'], repo=dict(full_name=q['repository'])),
            base=dict(sha=q['base'], ref=q['base_branch'], repo=dict(full_name=q['repository'])),
            title=q['title'], body=q['body'], number=17, html_url='https://github.com/'+q['repository']+'/pull/17')]
        if self.fail == 'pr-after': raise ValueError('lost response')


class CatalogPublicationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CatalogTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.runner = self.f.runner
        self.run = self.validated('constant')
        self.publisher = pub.Publications(self.runner)
        self.prepared = self.publisher.prepare(self.run['id']); self.id = self.prepared['id']
        self.q = self.prepared['request']; self.remote = Remote(self.q)

    def validated(self, task):
        r = self.f.approved(task)
        with patch.object(LocalCLI, 'run', side_effect=self.f.worker):
            result = self.f.runner.execute(r['id'])
        self.assertEqual(result['state'], 'validated', result)
        return result
    def approve(self):
        self.publisher.remote_inspect(self.id, self.remote)
        return self.publisher.approve(self.id, 'PUBLISH '+self.prepared['binding'])
    def execute(self): return self.publisher.execute(self.id, self.remote)
    def save(self, r):
        with self.runner.tx() as db: self.runner.save(db, r)

    def test_two_distinct_tasks_are_distinct_drafts(self):
        self.approve(); first = self.execute()
        second = self.validated('test-case')
        p = self.publisher.prepare(second['id']); remote = Remote(p['request'])
        self.publisher.remote_inspect(p['id'], remote)
        self.publisher.approve(p['id'], 'PUBLISH '+p['binding'])
        result = self.publisher.execute(p['id'], remote)
        for field in ('branch', 'commit', 'tree'):
            self.assertNotEqual(first[field], result[field])
        self.assertNotEqual(self.q['body'], p['request']['body'])
        self.assertEqual(self.remote.calls.count('pr'), 1)
        self.assertEqual(remote.calls.count('pr'), 1)

    def test_second_allowlisted_repository_and_non_main_base(self):
        source = self.f.root/'client'; source.mkdir()
        (source/'demo.js').write_text('const fixture = 1;\n')
        git(source, 'init', '-q'); git(source, 'add', '.')
        git(source, '-c', 'user.name=Fixture', '-c', 'user.email=f@local', 'commit', '-qm', 'client')
        identity = 'MZKZxyz/fort-custer-client'
        git(source, 'remote', 'add', 'origin', 'https://github.com/'+identity+'.git')
        sha = git(source, 'rev-parse', 'HEAD').decode().strip()
        self.f.config['repositories']['fort-custer-client'] = dict(identity=identity, source=str(source),
            sha=sha, branch='review/base', reviewed_issues=[7])
        e = copy.deepcopy(self.f.entry())
        e.update(repo='fort-custer-client', repository=identity, source=sha,
                 input_hash=manifest(source_files(source, sha, ['demo.js'])), allowed=['demo.js'], issue=7,
                 issue_snapshot=dict(number=7, state='open', html_url='https://github.com/'+identity+'/issues/7'),
                 checks=[dict(name='syntax', argv=['node', '--check', 'demo.js'], timeout_seconds=3)])
        self.f.config['catalog']['tasks']['client'] = e; self.f.reload()
        r = self.f.approved('client')
        def worker(root, *args):
            (root/'demo.js').write_text('const fixture = 2;\n')
            return dict(input_tokens=1, cached_input_tokens=0, output_tokens=1)
        with patch.object(LocalCLI, 'run', side_effect=worker): result = self.f.runner.execute(r['id'])
        self.assertEqual(result['state'], 'validated', result)
        publisher = pub.Publications(self.f.runner); p = publisher.prepare(r['id']); remote = Remote(p['request'])
        publisher.remote_inspect(p['id'], remote); publisher.approve(p['id'], 'PUBLISH '+p['binding'])
        self.assertIn(identity, publisher.execute(p['id'], remote)['url'])
        self.assertEqual(p['request']['base_branch'], 'review/base')
        server_run = self.validated('test-case')
        server_p = publisher.prepare(server_run['id']); server_remote = Remote(server_p['request'])
        publisher.remote_inspect(server_p['id'], server_remote)
        publisher.approve(server_p['id'], 'PUBLISH '+server_p['binding'])
        self.assertIn('MZKZxyz/fort-custer-server', publisher.execute(server_p['id'], server_remote)['url'])
        # The original, separately policy-bound server execution
        # remains independently inspectable; policy changes cannot republish it.
        with self.assertRaises(ValueError): self.publisher.check(self.prepared)

    def test_reconstruction_after_workspace_removal_and_restart(self):
        before = self.runner.inspect(self.run['id'])
        self.assertEqual(list(self.runner.scratch.iterdir()), [])
        runner = Runner(self.f.path, self.f.config['state'], lambda:self.f.now)
        with patch.object(LocalCLI, 'run', side_effect=AssertionError('Publisher invoked model')):
            r, files, candidate = pub.reconstruct(runner, self.run['id'])
        self.assertEqual(r, before)
        self.assertEqual(manifest(files), self.q['input_hash'])
        self.assertEqual(manifest(candidate), self.q['candidate_hash'])
        self.assertEqual(self.runner.inspect(self.run['id']), before)
        self.assertEqual(set(files), set(candidate))

    def test_publisher_subprocesses_are_credential_free_git_only(self):
        run = subprocess.run
        commands = []
        def observed(command, *args, **kwargs):
            commands.append((command, kwargs.get('env', {})))
            return run(command, *args, **kwargs)
        with patch('subprocess.run', side_effect=observed), patch.dict('os.environ', {'GITHUB_TOKEN':'fake-secret'}):
            pub.reconstruct(self.runner, self.run['id'])
        self.assertTrue(commands)
        for command, env in commands:
            self.assertEqual(command[0], '/usr/bin/git')
            self.assertNotIn('GITHUB_TOKEN', env)
            self.assertNotIn('GH_TOKEN', env)
            self.assertIn('core.hooksPath=/dev/null', command)

    def test_publication_binding_contains_entire_action_and_artifacts(self):
        self.assertEqual(self.q['spec'], self.run['spec'])
        self.assertEqual(self.q['artifact'], digest(self.run))
        self.assertEqual(self.q['qa'], digest(self.run['qa']))
        self.assertEqual(self.q['approval'], digest(self.run['history']))
        self.assertEqual(self.q['files'], self.run['files'])
        self.assertEqual(self.q['commit'], pub.commit_identity(self.q['tree'], self.q['base'], self.q['message']))
        self.assertEqual(self.q['expires'], self.f.now+600)
        self.assertTrue(self.q['draft'])
        self.assertEqual(self.prepared['binding'], digest(self.q))

    def test_no_publication_without_separate_approval(self):
        with self.assertRaises(ValueError): self.execute()
        for answer in ('yes', 'APPROVE '+self.run['binding'], 'PUBLISH '+'a'*64):
            with self.assertRaises(ValueError): self.publisher.approve(self.id, answer)
        with self.assertRaises(ValueError):
            self.publisher.approve(self.id, 'PUBLISH '+self.prepared['binding'])
        self.assertEqual(self.remote.calls, [])

    def test_expiration_replay_and_no_renewal(self):
        self.approve()
        with self.assertRaises(ValueError): self.approve()
        self.f.now += 601
        with self.assertRaises(ValueError): self.execute()
        again = self.publisher.prepare(self.run['id'])
        self.assertEqual(again['request'], self.q)
        with self.assertRaises(ValueError): self.publisher.approve(self.id, 'PUBLISH '+again['binding'])
        self.assertEqual(self.remote.calls, [])

    def test_historical_coding_expiry_does_not_expire_validated_artifact(self):
        self.f.now += 601
        self.assertEqual(pub.reconstruct(self.runner, self.run['id'])[0], self.run)

    def test_changed_evidence_is_rejected_before_writes(self):
        self.approve()
        mutations = [lambda r:r.update(candidate_hash='0'*64),
            lambda r:r['spec'].update(source='0'*40), lambda r:r['spec'].update(allowed=['test/analyzer.test.js']),
            lambda r:r['qa'][-1].update(patch=r['qa'][-1]['patch']+'junk\n'),
            lambda r:r['qa'][-1].update(input_hash='0'*64), lambda r:r['qa'][-1].update(candidate_tree='0'*40),
            lambda r:r.update(files=['not-reviewed.js']), lambda r:r['qa'].pop(0),
            lambda r:r['qa'][1].update(command=['node', '--eval', 'true']),
            lambda r:r['qa'][1].update(code=True), lambda r:r['qa'][1].update(reason='timeout'),
            lambda r:r['qa'][1].update(stdout=None), lambda r:r['qa'][1].update(stdout='tampered output'),
            lambda r:r['history'][1].update(binding='0'*64), lambda r:r['history'].pop(1),
            lambda r:r.update(usage={}), lambda r:r.update(state='failed'), lambda r:r.update(state='cancelled')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                r = copy.deepcopy(self.run); mutate(r); self.save(r)
                with self.assertRaises(ValueError): self.execute()
        self.save(self.run)
        self.assertEqual(self.remote.calls, [])

    def test_invalid_evidence_rejected_even_before_publication_binding(self):
        for field, value in (('patch', self.run['qa'][-1]['patch']+'junk\n'),
                             ('candidate_tree', 'a'*40), ('candidate_hash', 'a'*64),
                             ('input_hash', 'a'*64), ('candidate_revision', 'not-a-sha')):
            r = copy.deepcopy(self.run); r['qa'][-1][field] = value; self.save(r)
            with self.assertRaises(ValueError): pub.reconstruct(self.runner, r['id'])
        r = copy.deepcopy(self.run); r['qa'][1]['code'] = 1; self.save(r)
        with self.assertRaises(ValueError): pub.reconstruct(self.runner, r['id'])

    def test_policy_changes_rejected_even_on_existing_runner(self):
        self.approve()
        self.f.config['catalog']['tasks']['constant']['instructions'] = 'changed policy'
        self.f.path.write_text(json.dumps(self.f.config))
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])

    def test_unvalidated_task_cannot_be_prepared(self):
        r = self.f.runner.task_prepare('test-case')
        with self.assertRaises(ValueError): self.publisher.prepare(r['id'])
        self.assertEqual(self.remote.calls, [])

    def test_missing_source_objects_block(self):
        self.approve()
        with patch('src.local_runner.git', side_effect=ValueError('source unavailable')):
            with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])

    def test_tampered_request_even_with_rehashed_binding(self):
        self.approve()
        for field, value in (('repository', 'evil/repo'), ('base_branch', 'other'), ('branch', 'main'),
                             ('body', 'changed'), ('title', 'changed'), ('commit', 'a'*40),
                             ('operator', -1), ('files', []), ('qa', 'a'*64), ('protocol', 'future-v2')):
            q = dict(self.q, **{field:value})
            with self.runner.tx() as db:
                db.execute('UPDATE publications SET request=?, binding=? WHERE id=?', (canonical(q), digest(q), self.id))
            with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])

    def test_audit_history_is_required(self):
        self.approve()
        with self.runner.tx() as db:
            db.execute("DELETE FROM publication_events WHERE publication=? AND event='approved'", (self.id,))
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])

    def test_collision_and_base_change_before_objects(self):
        self.approve()
        for head in ('a'*40, self.q['commit']):
            self.remote.branch = head
            with self.assertRaises(ValueError): self.execute()
        self.remote.branch = None
        for state in ('open', 'closed'):
            self.remote.rows = [dict(state=state)]
            with self.assertRaises(ValueError): self.execute()
        self.remote.rows = []; self.remote.base_sha = 'a'*40
        with self.assertRaises(ValueError): self.execute()
        self.remote.base_sha = self.q['base']; self.remote.identity = 'evil/repo'
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])

    def test_preflight_rejects_closed_pr_and_matching_branch(self):
        self.remote.rows = [dict(state='closed')]
        with self.assertRaises(ValueError): self.publisher.remote_inspect(self.id, self.remote)
        self.remote.rows = []; self.remote.branch = self.q['commit']
        with self.assertRaises(ValueError): self.publisher.remote_inspect(self.id, self.remote)

    def test_branch_response_loss_and_restart_reconcile(self):
        self.approve(); self.remote.fail = 'branch-after'
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.publisher.inspect(self.id)['status'], 'branch-requested')
        self.remote.fail = None; self.publisher = pub.Publications(self.runner)
        result = self.execute(); self.assertEqual(self.execute(), result)
        self.assertEqual(self.remote.calls.count('branch'), 1)
        self.assertEqual(self.remote.calls.count('pr'), 1)
        before = list(self.remote.calls)
        self.publisher.remote_inspect(self.id, self.remote)
        self.assertEqual(self.remote.calls, before)

    def test_branch_before_write_failure_can_resume_atomic_creation(self):
        self.approve(); self.remote.fail = 'branch-before'
        with self.assertRaises(ValueError): self.execute()
        self.remote.fail = None; self.execute()
        self.assertEqual(self.remote.calls.count('pr'), 1)

    def test_pr_response_loss_reconciles_without_post(self):
        self.approve(); self.remote.fail = 'pr-after'
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.publisher.inspect(self.id)['status'], 'pr-requested')
        self.remote.fail = None; self.execute()
        self.assertEqual(self.remote.calls.count('pr'), 1)

    def test_ambiguous_pr_is_never_posted_again(self):
        self.approve(); self.remote.fail = 'pr-before'
        with self.assertRaises(ValueError): self.execute()
        self.remote.fail = None
        for _ in range(2):
            with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls.count('pr'), 1)
        self.assertEqual(self.publisher.prepare(self.run['id'])['status'], 'pr-requested')
        with self.assertRaises(ValueError): self.approve()

    def test_expired_recovery_does_not_reset_hold(self):
        self.approve(); self.remote.fail = 'branch-after'
        with self.assertRaises(ValueError): self.execute()
        calls = list(self.remote.calls); self.f.now += 601
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, calls)
        self.assertEqual(self.publisher.prepare(self.run['id'])['status'], 'branch-requested')

    def test_cancel_stop_and_mid_upload_cancellation(self):
        self.approve()
        def upload(q, files, candidate, guard):
            self.publisher.cancel(self.id); guard()
        self.remote.candidate = upload
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, [])
        self.assertEqual(self.publisher.prepare(self.run['id'])['status'], 'cancelled')
        self.runner.cancel()
        with self.assertRaises(ValueError): pub.Publications(self.runner).remote_inspect(self.id, self.remote)

    def test_stop_between_each_individual_transport_write(self):
        self.approve(); r, files, candidate = pub.reconstruct(self.runner, self.run['id'])
        remote = pub.GitHub(self.credential(), self.q['repository'])
        calls = []
        def api(method, path, payload=None):
            calls.append(path); self.publisher.cancel(self.id)
            data = base64.b64decode(payload['content'])
            return dict(sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest())
        remote.api = api
        with self.assertRaises(ValueError):
            remote.candidate(self.q, files, candidate, lambda:self.publisher.check(self.publisher.inspect(self.id)))
        self.assertEqual(calls, ['/git/blobs'])

    def test_remote_base_change_during_upload_blocks_branch(self):
        self.approve()
        upload = self.remote.candidate
        def change_base(*args):
            result = upload(*args); self.remote.base_sha = 'a'*40; return result
        self.remote.candidate = change_base
        with self.assertRaises(ValueError): self.execute()
        self.assertNotIn('branch', self.remote.calls)
        self.assertNotIn('pr', self.remote.calls)
        self.assertEqual(self.publisher.inspect(self.id)['status'], 'publishing')

    def test_remote_metadata_is_verified_read_only(self):
        self.approve(); self.execute()
        original = copy.deepcopy(self.remote.rows[0]); calls = list(self.remote.calls)
        changes = [lambda p:p.update(draft=False), lambda p:p.update(state='closed'),
                   lambda p:p.update(merged_at='now'), lambda p:p.update(auto_merge={"enabled":True}),
                   lambda p:p.update(maintainer_can_modify=True), lambda p:p.update(body='changed'),
                   lambda p:p.update(title='changed'), lambda p:p['base'].update(ref='other'),
                   lambda p:p['base'].update(sha='a'*40), lambda p:p['head'].update(sha='a'*40),
                   lambda p:p['head']['repo'].update(full_name='evil/repo'),
                   lambda p:p.update(html_url='https://evil.example/')]
        for mutate in changes:
            row = copy.deepcopy(original); mutate(row); self.remote.rows = [row]
            with self.assertRaises(ValueError): self.publisher.remote_inspect(self.id, self.remote)
            with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.remote.calls, calls)

    def test_remote_commit_and_moved_branch_rejected(self):
        self.approve(); self.execute()
        self.remote.branch = 'a'*40
        with self.assertRaises(ValueError): self.execute()
        self.remote.branch = self.q['commit']
        original = self.remote.commit
        for field, value in (('sha', 'a'*40), ('tree', dict(sha='a'*40)), ('parents', []),
                             ('message', 'changed'), ('author', {})):
            with patch.object(self.remote, 'commit', side_effect=lambda sha:dict(original(sha), **{field:value})):
                with self.assertRaises(ValueError): self.publisher.remote_inspect(self.id, self.remote)

    def test_legacy_and_unknown_protocol_separation(self):
        with self.assertRaises(ValueError): legacy.reconstruct(self.runner, self.run['id'])
        with self.assertRaises(ValueError): legacy.Publications(self.runner).prepare(self.run['id'])
        with self.assertRaises(ValueError): legacy.Publications(self.runner).execute(self.id, self.remote)
        r = copy.deepcopy(self.run); r['spec'].pop('protocol'); self.save(r)
        with self.assertRaises(ValueError): pub.reconstruct(self.runner, r['id'])
        r['spec']['protocol'] = 'future-v99'; self.save(r)
        with self.assertRaises(ValueError): pub.reconstruct(self.runner, r['id'])
        # Legacy requests are readable only by their own implementation.
        with self.runner.tx() as db:
            db.execute('UPDATE publications SET request=? WHERE id=?', (canonical(dict(run=r['id'])), self.id))
        with self.assertRaises(ValueError): self.publisher.inspect(self.id)

    def credential(self):
        return dict(repository=self.q['repository'], security_reviewed=True,
                    operator_selected_identity='reviewed-app', permissions={'contents':'write', 'pull_requests':'write'},
                    token='synthetic-never-real')

    def test_credential_repository_and_permission_mismatch(self):
        for change in ({'repository':'MZKZxyz/fort-custer-client'}, {'security_reviewed':False},
                       {'permissions':{'contents':'write', 'pull_requests':'write', 'actions':'write'}},
                       {'operator_selected_identity':''}, {'token':''}):
            with self.assertRaises(ValueError): pub.GitHub(dict(self.credential(), **change), self.q['repository'])
        with self.assertRaises(ValueError): pub.GitHub(self.credential(), 'evil/repo')

    def test_transport_object_identity_and_only_approved_mutations(self):
        remote = pub.GitHub(self.credential(), self.q['repository']); calls = []
        _, files, candidate = pub.reconstruct(self.runner, self.run['id'])
        def api(method, path, payload=None):
            calls.append((method,path,payload))
            if path == '/git/blobs':
                data = base64.b64decode(payload['content'])
                return dict(sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest())
            if path == '/git/trees': return dict(sha=self.q['tree'])
            if path == '/git/commits': return dict(sha=self.q['commit'])
            return dict(tree=dict(sha='base-tree'))
        remote.api = api
        self.assertEqual(remote.candidate(self.q, files, candidate, lambda:None), self.q['commit'])
        remote.create_branch(self.q, lambda:None); remote.create_pr(self.q, lambda:None)
        writes = [c for c in calls if c[0] == 'POST']
        self.assertEqual([c[1] for c in writes], ['/git/blobs','/git/trees','/git/commits','/git/refs','/pulls'])
        self.assertEqual(writes[-2][2]['ref'], 'refs/heads/'+self.q['branch'])
        self.assertEqual(writes[-1][2]['base'], self.q['base_branch'])
        self.assertTrue(writes[-1][2]['draft'])
        for field,value in (('branch', 'main'), ('draft', False), ('repository','evil/repo')):
            with self.assertRaises(ValueError): remote.create_pr(dict(self.q, **{field:value}), lambda:None)
        for bad in ('/git/blobs', '/git/trees', '/git/commits'):
            remote.api = lambda method,path,payload=None: dict(sha='a'*40) if path == bad else api(method,path,payload)
            with self.assertRaises(ValueError): remote.candidate(self.q, files, candidate, lambda:None)

    def test_api_rejects_updates_merge_deployment_and_redacts_failures(self):
        remote = pub.GitHub(self.credential(), self.q['repository'])
        remote.opener = MagicMock(); remote.opener.open.side_effect = OSError('synthetic-never-real')
        for method,path in (('PATCH','/git/refs/heads/main'), ('PUT','/pulls/1/merge'),
                            ('POST','/pulls/1/reviews'), ('POST','/deployments'), ('POST','/releases'),
                            ('DELETE','/git/refs/heads/main'), ('GET','/../other')):
            with self.assertRaises(ValueError): remote.api(method,path,{})
        for path,payload in (('/git/refs', dict(ref='refs/heads/main', sha='a'*40)),
                             ('/pulls', dict(head=self.q['branch'], base='main', title='x', body='x',
                                            draft=False, maintainer_can_modify=False))):
            with self.assertRaises(ValueError): remote.api('POST', path, payload)
        remote.opener.open.assert_not_called()
        with self.assertRaises(ValueError) as error: remote.repository()
        self.assertNotIn('synthetic-never-real', str(error.exception))
        remote.opener.open.assert_called_once()

    def test_cli_has_no_approval_flag_or_stdin_fallback(self):
        command = [sys.executable, '-m', 'src.catalog_publication', '--policy', str(self.f.path),
                   '--state', self.f.config['state']]
        result = subprocess.run([*command, 'approve', self.id, '--yes'], input='PUBLISH '+self.prepared['binding'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        # No controlling terminal in the test subprocess; piped approval is ignored.
        with patch('src.catalog_publication.terminal_challenge', side_effect=OSError('no tty')):
            with patch.object(sys, 'argv', [*command[2:], 'approve', self.id]), redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError): pub.main()
        self.assertEqual(self.publisher.inspect(self.id)['status'], 'prepared')


if __name__ == '__main__': unittest.main()
