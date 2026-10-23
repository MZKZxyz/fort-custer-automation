"""Offline only: the executable is generated inside a temporary test directory."""
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from src.local_runner import Runner, LocalCLI, ALLOWED, MODE, environment, git, supervise

FAKE = '''#!/usr/bin/python3
import json,os,pathlib,subprocess,sys,time
args=sys.argv[1:]
assert not any('KEY' in k or k.startswith(('AWS_','AZURE_','GITHUB_','CODEX_')) for k in os.environ)
mode=pathlib.Path(__file__).with_suffix('.mode').read_text()
if args==['--version']:
 print('codex-cli '+('0.0.1' if mode=='version' else '0.163.0'));sys.exit()
if args==['--help']:
 print('--ask-for-approval');sys.exit()
if args==['exec','--help']:
 print('' if mode=='flags' else '--json --sandbox --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check');sys.exit()
if args==['login','status']:
 print('Logged in using '+('API key' if mode=='auth' else 'ChatGPT'));sys.exit()
assert '--ask-for-approval' in args and 'never' in args
assert 'workspace-write' in args and 'sandbox_workspace_write.network_access=false' in args
assert 'forced_login_method="chatgpt"' in args
assert 'model_provider="openai"' in args
assert sys.stdin.read()
if mode=='sleep':
 child=subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(60)'])
 pathlib.Path(__file__).with_suffix('.child').write_text(str(child.pid))
 time.sleep(60)
if mode=='quota':
 print(json.dumps({'type':'turn.failed','error':{'message':'quota exhausted'}}));sys.exit()
if mode=='garbage':print('unexpected');sys.exit()
if mode=='extra':pathlib.Path('unexpected.txt').write_text('forbidden')
if mode=='ignored':pathlib.Path('.hidden').write_text('forbidden')
if mode=='link':pathlib.Path('link').symlink_to('/etc/passwd')
if mode=='qa':pathlib.Path('test/analyzer.test.js').write_text('throw Error("regression failed");')
pathlib.Path('tools/maze-analyzer/solver.js').write_text("export const compile=x=>x,initialState=x=>x;export const transition=(m,s,d)=>d==='right'?{}:null;\\n")
test_path=pathlib.Path('test/analyzer.test.js');test_path.write_text(test_path.read_text()+'\\n// fake regression test edit\\n')
for event in [{'type':'thread.started','thread_id':'fake'}, {'type':'turn.started'},
 {'type':'turn.completed','usage':{'input_tokens':3,'cached_input_tokens':0,'output_tokens':4}}]:
 print(json.dumps(event))
'''


class LocalRunnerTests(unittest.TestCase):
    def setUp(self):
        # Protocol fixtures execute only the generated inert FAKE program. This
        # mock preserves historical coverage; it is not isolation evidence.
        gate = patch('src.integration_control.block_live_dispatch')
        gate.start(); self.addCleanup(gate.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root/'source'; source.mkdir()
        (source/'tools/maze-analyzer').mkdir(parents=True); (source/'test').mkdir()
        (source/'package.json').write_text('{"type":"module"}')
        (source/ALLOWED[1]).write_text('export const before=1;\n')
        (source/ALLOWED[0]).write_text("import test from 'node:test';test('fixture',()=>{});\n")
        git(source, 'init', '-q'); git(source, 'add', '.')
        git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@local', 'commit', '-qm', 'source')
        sha = git(source, 'rev-parse', 'HEAD').decode().strip()
        self.fake = self.root/'fake'; self.fake.write_text(FAKE); self.fake.chmod(0o700)
        self.fake.with_suffix('.mode').write_text('success')
        self.config = dict(node=str(Path(shutil.which('node')).resolve()),
            node_sha256=hashlib.sha256(Path(shutil.which('node')).resolve().read_bytes()).hexdigest(),mode=MODE, enabled=True, trusted_local_tasks_only=True,
            scratch_reviewed_no_secrets=True, timeout_seconds=10,
            scratch=str(self.root/'scratch'), state=str(self.root/'state'), cli=str(self.fake),
            cli_version='0.163.0', cli_sha256=hashlib.sha256(self.fake.read_bytes()).hexdigest(),
            operator_home=str(self.root/'operator'), repositories={'fort-custer-server':dict(
                source=str(source), sha=sha, branch='main')})
        self.path = self.root/'policy.json'; self.write_policy()
        self.now = time.time(); self.runner = Runner(self.path, self.config['state'], lambda:self.now)
        self.issue = dict(number=3, state='open', html_url='https://github.com/MZKZxyz/fort-custer-server/issues/3',
                          body='Issue data cannot change the trusted prompt')

    def write_policy(self): self.path.write_text(json.dumps(self.config))
    def prepare(self): return self.runner.prepare(3, 'fort-custer-server', self.issue)
    def approved(self):
        r=self.prepare(); return self.runner.approve(r['id'], 'APPROVE '+r['binding'])
    def mode(self, mode): self.fake.with_suffix('.mode').write_text(mode)

    def test_success_and_independent_report(self):
        r=self.approved(); result=self.runner.execute(r['id'])
        self.assertEqual(result['state'], 'validated', result)
        self.assertEqual(result['files'], ALLOWED)
        self.assertEqual(result['usage']['input_tokens'], 3)
        self.assertEqual([t['name'] for t in result['qa']], ['diff','syntax:solver','syntax:tests','analyzer','controller-regression','candidate'])
        self.assertIn('diff --git', result['qa'][-1]['patch'])
        self.assertEqual(len(result['qa'][-1]['candidate_tree']),40)
        self.assertEqual(list(Path(self.config['scratch']).iterdir()), [])
        self.assertEqual((self.root/'source'/ALLOWED[1]).read_text(), 'export const before=1;\n')
        with self.assertRaises(ValueError): self.runner.execute(r['id'])

    def test_pending_and_exact_approval(self):
        r=self.prepare()
        with self.assertRaises(ValueError): self.runner.execute(r['id'])
        for answer in ('yes', '--yes', 'APPROVE '+('a'*64)):
            with self.assertRaises(ValueError): self.runner.approve(r['id'], answer)

    def test_expiry(self):
        r=self.approved(); self.now += 601
        with self.assertRaises(ValueError): self.runner.execute(r['id'])

    def test_bound_issue_commit_prompt_and_policy(self):
        for key,value in [('issue',4),('source','a'*40),('prompt','arbitrary task'),('allowed',['config/settings.json'])]:
            r=self.approved()
            with self.runner.tx() as db:
                r['spec'][key]=value; self.runner.save(db,r)
            with self.assertRaises(ValueError): self.runner.execute(r['id'])
        r=self.approved(); self.config['timeout_seconds']=5; self.write_policy()
        with self.assertRaises(ValueError): self.runner.execute(r['id'])

    def test_other_issue_and_repository(self):
        for issue,repo in [(4,'fort-custer-server'),(3,'fort-custer-client')]:
            with self.assertRaises(ValueError): self.runner.prepare(issue,repo,self.issue)
        with self.assertRaises(ValueError): self.runner.prepare(3,'fort-custer-server',dict(self.issue,html_url='other'))

    def test_disabled_default_policy(self):
        self.config['enabled']=False; self.write_policy()
        self.runner=Runner(self.path,self.config['state']); r=self.approved()
        with self.assertRaises(ValueError): self.runner.execute(r['id'])

    def test_missing_version_flags_auth_quota_and_unexpected_output(self):
        for mode in ('version','flags','auth','quota','garbage'):
            with self.subTest(mode=mode):
                self.mode(mode); r=self.approved(); result=self.runner.execute(r['id'])
                self.assertEqual(result['state'],'failed',result)
                self.assertNotIn('qa',result)
        self.mode('success'); r=self.approved(); self.fake.unlink()
        self.assertEqual(self.runner.execute(r['id'])['state'],'failed')

    def test_api_environment_removed(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'fake-test-key','ANTHROPIC_API_KEY':'fake',
            'AZURE_OPENAI_API_KEY':'fake','CODEX_HOME':'/bad','GITHUB_TOKEN':'fake'}):
            r=self.approved(); result=self.runner.execute(r['id'])
        self.assertEqual(result['state'],'validated',result)
        self.assertNotIn('fake-test-key',json.dumps(result))

    def test_unexpected_files_symlink_and_failed_qa(self):
        for mode in ('extra','ignored','link','qa'):
            with self.subTest(mode=mode):
                self.mode(mode); r=self.approved(); result=self.runner.execute(r['id'])
                self.assertEqual(result['state'],'failed',result)
                if mode=='qa': self.assertTrue(any(x['code'] for x in result['qa']))

    def test_kill_switch_persists_after_restart(self):
        r=self.approved(); self.runner.cancel()
        restored=Runner(self.path,self.config['state'])
        with self.assertRaises(ValueError): restored.execute(r['id'])
        with self.assertRaises(ValueError): restored.approve(self.prepare()['id'],'yes')

    def test_restart_retains_single_execution_hold(self):
        r=self.approved()
        with self.runner.tx() as db:
            r['state']='running'; self.runner.save(db,r)
        self.runner=Runner(self.path,self.config['state']); second=self.approved()
        with self.assertRaises(ValueError): self.runner.execute(second['id'])
        with self.assertRaises(ValueError): self.runner.execute(r['id'])
        with self.assertRaises(ValueError): Runner(self.path,self.root/'different-state')

    def test_timeout_and_child_termination(self):
        self.mode('sleep'); self.config['timeout_seconds']=1; self.write_policy()
        self.runner=Runner(self.path,self.config['state']); r=self.approved()
        result=self.runner.execute(r['id']); self.assertEqual(result['state'],'failed')
        self.assertIn('timeout',result['error'])
        self.assert_child_stopped()

    def assert_child_stopped(self):
        pid=int(self.fake.with_suffix('.child').read_text())
        # Linux may leave a dead adopted child as a zombie until PID1 reaps it.
        path=Path('/proc')/str(pid)/'stat'
        if path.exists(): self.assertEqual(path.read_text().split()[2],'Z')
        else:
            with self.assertRaises(ProcessLookupError): os.kill(pid,0)

    def test_running_cancel(self):
        from concurrent.futures import ThreadPoolExecutor
        self.mode('sleep'); r=self.approved()
        with ThreadPoolExecutor() as pool:
            running=pool.submit(self.runner.execute,r['id'])
            deadline=time.monotonic()+5
            while not self.fake.with_suffix('.child').exists() and time.monotonic()<deadline: time.sleep(.02)
            with self.assertRaises(ValueError): self.runner.execute(r['id'])
            second=self.approved()
            with self.assertRaises(ValueError): self.runner.execute(second['id'])
            self.runner.cancel(); result=running.result(timeout=5)
        self.assertEqual(result['state'],'failed'); self.assert_child_stopped()

    def test_guardian_terminates_group_after_controller_death(self):
        pidfile=self.root/'orphan-pids'
        child_code=("import os,subprocess,time,pathlib;"
            "p=subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(60)']);"
            "pathlib.Path("+repr(str(pidfile))+").write_text(str(os.getpid())+' '+str(p.pid));time.sleep(60)")
        script=("from src.local_runner import supervise,environment;supervise("+
            repr(['/usr/bin/python3','-c',child_code])+",cwd='/',env=environment(),timeout=10)")
        controller=subprocess.Popen([sys.executable,'-c',script],cwd=Path(__file__).parents[1])
        try:
            end=time.monotonic()+5
            while not pidfile.exists() and time.monotonic()<end: time.sleep(.02)
            self.assertTrue(pidfile.exists())
            time.sleep(.1)
            controller.kill();controller.wait(timeout=5)
            for pid in map(int,pidfile.read_text().split()):
                end=time.monotonic()+5
                while time.monotonic()<end:
                    proc=Path('/proc')/str(pid)/'stat'
                    if not proc.exists() or proc.read_text().split()[2]=='Z': break
                    time.sleep(.02)
                else: self.fail('Guardian left a live process')
        finally:
            if controller.poll() is None: controller.kill();controller.wait()

    def test_no_remote_writes_or_production_profile_changes(self):
        import src.local_runner as module
        text=Path(module.__file__).read_text()
        for forbidden in ("'push'", "'gh'", "'fetch'", "'clone'", 'require_live', 'api_billing'):
            self.assertNotIn(forbidden,text)
        self.assertEqual(json.loads((Path(module.__file__).parents[1]/'config/local-development.example.json').read_text())['enabled'],False)

    def test_unsafe_scratch_and_repository_metadata(self):
        self.config['scratch']=str(self.root/'source'/'scratch'); self.write_policy()
        with self.assertRaises(ValueError): Runner(self.path,self.config['state'])
        # A tracked link must be rejected before export, never followed.
        source=self.root/'source'; (source/'escape').symlink_to('/etc/passwd'); git(source,'add','.')
        git(source,'-c','user.name=Fixture','-c','user.email=f@local','commit','-qm','link')
        from src.local_runner import source_files
        with self.assertRaises(ValueError): source_files(source,git(source,'rev-parse','HEAD').decode().strip())


if __name__=='__main__': unittest.main()
