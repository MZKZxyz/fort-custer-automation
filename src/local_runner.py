"""Manually approved local development only. Never imported by daily dispatch."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

MODE = 'local_codex_development'
ALLOWED = ['test/analyzer.test.js', 'tools/maze-analyzer/solver.js']
PROMPT = '''Fix only the inherited-property direction lookup in tools/maze-analyzer/solver.js.
Invalid directions including toString, constructor and __proto__ must return null.
Add regression tests in test/analyzer.test.js. Preserve generator semantics.
Run node --test test/analyzer.test.js. Change only these two files.
Do not change API, authentication, MongoDB, deployment, or controller policy.
Do not commit, push, create pull requests, merge, deploy, access services or secrets.
This is a trusted, locally reviewed development experiment.'''
PROBE = """import assert from 'node:assert/strict';
import {compile,initialState,transition} from './tools/maze-analyzer/solver.js';
const maze=compile(['#####','#S E#','#####']);const state=initialState(maze);
for(const name of ['toString','constructor','__proto__','invalid',''])
 assert.equal(transition(maze,state,name),null,name);
assert.notEqual(transition(maze,state,'right'),null);
"""
CHECKS = [('syntax:solver', ['node', '--check', ALLOWED[1]]),
          ('syntax:tests', ['node', '--check', ALLOWED[0]]),
          ('analyzer', ['node', '--test', ALLOWED[0]]),
          ('controller-regression', ['node', '--input-type=module', '--eval', PROBE])]


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()


def environment(home='/nonexistent'):
    # Deliberate allowlist, not a denylist of known API key spellings.
    return dict(PATH='/usr/bin:/bin', HOME=str(home), LANG='C.UTF-8',
                GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')


def git(root, *args):
    return subprocess.check_output(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
        '-c', 'core.fsmonitor=false', '-C', str(root), *args], env=environment(),
        stderr=subprocess.PIPE, timeout=30)


def source_files(source, sha, allowed=None):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Exact SHA required')
    if git(source, 'rev-parse', sha+'^{commit}').decode().strip() != sha:
        raise ValueError('Source identity mismatch')
    files = {}
    for entry in git(source, 'ls-tree', '-rz', sha).split(b'\0'):
        if not entry:
            continue
        meta, raw = entry.split(b'\t'); mode, kind, obj = meta.decode().split()
        name = raw.decode('utf-8')
        parts = name.split('/')
        if (mode not in ('100644', '100755') or kind != 'blob' or
            any(p in ('', '.', '..', '.git', '.codex', '.gitattributes', '.gitmodules') for p in parts) or
            name.startswith('/') or '\\' in name or any(ord(c)<32 for c in name) or
            any(p == '.env' or p.startswith('.env.') and p not in ('.env.example', '.env.sample') for p in parts)):
            raise ValueError('Unsafe repository entry')
        files[name] = (int(mode, 8) & 0o777, git(source, 'cat-file', 'blob', obj))
    if not set(ALLOWED if allowed is None else allowed) <= set(files):
        raise ValueError('Expected allowed files missing')
    return files


def materialize(files, root):
    for name, (mode, data) in files.items():
        p = root/name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data); p.chmod(mode)


def snapshot(root):
    result = {}
    for p in root.rglob('*'):
        if p.is_symlink():
            raise ValueError('Symlinks prohibited')
        if p.is_dir():
            continue
        if not p.is_file() or p.stat().st_nlink != 1 or p.stat().st_size > 16*1024*1024:
            raise ValueError('Unsafe output file')
        result[str(p.relative_to(root))] = (p.stat().st_mode & 0o777, p.read_bytes())
    return result


def manifest(files):
    return digest({k: [v[0], hashlib.sha256(v[1]).hexdigest()] for k,v in files.items()})


def supervise(command, cwd, env, *, stdin='', timeout=2400, cancelled=lambda:False):
    if not 0 < timeout <= 2400:
        raise ValueError('Invalid timeout')
    start = time.monotonic()
    with tempfile.TemporaryFile() as inp, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        inp.write(stdin.encode()); inp.seek(0)
        p = subprocess.Popen(command, cwd=cwd, env=env, stdin=inp, stdout=out,
                             stderr=err, start_new_session=True)
        # A separate guardian survives controller death and enforces the original
        # deadline. EOF on the keepalive pipe means the controller has disappeared.
        reader, writer = os.pipe()
        guard_code = """import os,select,signal,sys
fd,pgid,seconds=int(sys.argv[1]),int(sys.argv[2]),float(sys.argv[3])
select.select([fd],[],[],seconds)
try: os.killpg(pgid,signal.SIGKILL)
except ProcessLookupError: pass
"""
        try:
            guardian = subprocess.Popen([sys.executable, '-I', '-c', guard_code,
                str(reader), str(p.pid), str(timeout)], pass_fds=(reader,),
                env=environment(), cwd='/', start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except BaseException:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait(timeout=5); os.close(reader); os.close(writer)
            raise
        os.close(reader)
        reason = None
        try:
            while p.poll() is None:
                if cancelled(): reason = 'cancelled'; break
                if time.monotonic()-start >= timeout: reason = 'timeout'; break
                if os.fstat(out.fileno()).st_size+os.fstat(err.fileno()).st_size > 8*1024*1024:
                    reason = 'output_limit'; break
                time.sleep(.02)
        finally:
            # Kill descendants even if the immediate parent has already exited.
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait(timeout=5)
            os.close(writer)
            guardian.wait(timeout=5)
        if reason is None and time.monotonic()-start >= timeout:
            reason = 'timeout'
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(8*1024*1024), err.read(8*1024*1024)
        if len(stdout)+len(stderr) >= 8*1024*1024: reason = 'output_limit'
        return dict(code=p.returncode, reason=reason, stdout=stdout, stderr=stderr)


class LocalCLI:
    def __init__(self, policy):
        self.policy = policy

    def run(self, workspace, prompt, cancelled, timeout):
        p = self.policy
        binary = Path(p['cli'])
        if not binary.is_absolute() or not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
            raise ValueError('Trusted absolute CLI binary required')
        if hashlib.sha256(binary.read_bytes()).hexdigest() != p['cli_sha256']:
            raise ValueError('CLI binary changed')
        env = environment(p['operator_home'])
        # Network trust settings only; never inherit API credentials or CODEX_HOME overrides.
        for key in ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR'):
            if key in os.environ: env[key] = os.environ[key]
        end = time.monotonic()+timeout
        def call(args, text=''):
            remaining = end-time.monotonic()
            if remaining <= 0: raise ValueError('timeout')
            r = supervise([str(binary), *args], workspace, env, stdin=text,
                          timeout=remaining, cancelled=cancelled)
            if r['code'] or r['reason']: raise ValueError(r['reason'] or 'CLI failed; no fallback')
            return r['stdout'].decode('utf-8', errors='strict').strip(), r['stderr'].decode('utf-8', errors='strict').strip()
        version, _ = call(['--version'])
        if version != 'codex-cli '+p['cli_version'] or p['cli_version'] != '0.163.0':
            raise ValueError('Unsupported CLI version')
        global_help, _ = call(['--help'])
        if '--ask-for-approval' not in global_help:
            raise ValueError('Unsupported approval flag')
        help_text, _ = call(['exec', '--help'])
        for flag in ('--json', '--sandbox', '--ephemeral', '--ignore-user-config', '--ignore-rules', '--skip-git-repo-check'):
            if flag not in help_text: raise ValueError('Unsupported CLI flags')
        login, login_err = call(['login', 'status'])
        if (login+'\n'+login_err).strip() != 'Logged in using ChatGPT':
            raise ValueError('Existing ChatGPT login required; no automatic authentication')
        stdout, stderr = call(['--ask-for-approval', 'never', 'exec', '--json', '--ephemeral',
            '--ignore-user-config', '--ignore-rules', '--skip-git-repo-check', '--sandbox', 'workspace-write',
            '--config', 'sandbox_workspace_write.network_access=false',
            '--config', 'sandbox_workspace_write.exclude_tmpdir_env_var=true',
            '--config', 'sandbox_workspace_write.exclude_slash_tmp=true',
            '--config', 'forced_login_method="chatgpt"',
            '--config', 'model_provider="openai"', '-'], prompt)
        # Never persist raw CLI messages or auth diagnostics.
        if stderr not in ('', 'Reading prompt from stdin...'):
            raise ValueError('Unexpected CLI diagnostics; operator review required')
        events = []
        for line in stdout.splitlines():
            try: event = json.loads(line)
            except ValueError: raise ValueError('Unexpected CLI output') from None
            if not isinstance(event, dict): raise ValueError('Unexpected CLI output')
            if event.get('type', '').startswith('item.'):
                if event.get('item', {}).get('type') not in {'agent_message', 'reasoning', 'command_execution', 'file_change', 'todo_list'}:
                    raise ValueError('Unexpected CLI item')
            events.append(event)
        kinds = [e.get('type') for e in events]
        known = {'thread.started', 'turn.started', 'item.started', 'item.updated', 'item.completed', 'turn.completed'}
        if (not events or kinds[:2] != ['thread.started', 'turn.started'] or any(k not in known for k in kinds) or kinds.count('turn.completed') != 1 or
            kinds[-1] != 'turn.completed' or kinds.count('thread.started') != 1 or kinds.count('turn.started') != 1):
            raise ValueError('Quota, authentication, protocol or usage failure; operator review required')
        usage = events[-1].get('usage')
        if not isinstance(usage, dict) or not {'input_tokens', 'cached_input_tokens', 'output_tokens'} <= set(usage) or any(type(v) is not int or v < 0 for v in usage.values()):
            raise ValueError('Unknown usage telemetry')
        return {k:v for k,v in usage.items() if k in ('input_tokens', 'cached_input_tokens', 'output_tokens')}


class Runner:
    def __init__(self, policy_path, state, clock=time.time):
        self.policy_path, self.state, self.clock = Path(policy_path).resolve(), Path(state).resolve(), clock
        self.policy = json.loads(self.policy_path.read_text())
        p = self.policy
        if (p.get('mode') != MODE or type(p.get('enabled')) is not bool or
            p.get('trusted_local_tasks_only') is not True or
            type(p.get('timeout_seconds')) is not int or not 0 < p['timeout_seconds'] <= 2400):
            raise ValueError('Invalid local policy')
        if any(not Path(p[key]).is_absolute() for key in ('scratch', 'state', 'operator_home')):
            raise ValueError('Absolute operator paths required')
        self.scratch = Path(p['scratch']).resolve()
        sources = [Path(repo['source']) for repo in p['repositories'].values()]
        if not sources or any(not source.is_absolute() for source in sources):
            raise ValueError('Absolute local Git sources required')
        forbidden = [*[source.resolve() for source in sources],
                     Path(__file__).resolve().parents[1], Path.home()/'fort-custer-canary']
        if not self.scratch.is_absolute() or any(self.scratch == x or self.scratch.is_relative_to(x) or x.is_relative_to(self.scratch) for x in forbidden):
            raise ValueError('Scratch must be separate from source, controller and canary')
        if any(self.state.is_relative_to(x) for x in forbidden):
            raise ValueError('State must be outside source, controller and canary')
        if self.state.is_relative_to(self.scratch) or self.policy_path.is_relative_to(self.scratch):
            raise ValueError('Policy and state must be outside worker root')
        if p.get('scratch_reviewed_no_secrets') is not True:
            raise ValueError('Operator must review disposable scratch parent for secrets')
        if self.state != Path(p['state']).resolve():
            raise ValueError('One policy-owned state directory required')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, document TEXT NOT NULL)')

    @contextlib.contextmanager
    def tx(self):
        with sqlite3.connect(self.state/'local.sqlite', timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def read(self, db, run):
        row = db.execute('SELECT document FROM runs WHERE id=?', (run,)).fetchone()
        if row is None: raise ValueError('Unknown task')
        return json.loads(row[0])

    def save(self, db, r):
        db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)', (r['id'], canonical(r)))

    def check(self, r):
        if self.state.joinpath('STOP').exists(): raise ValueError('Persistent kill switch active')
        if r['expires'] <= self.clock(): raise ValueError('Approval expired')
        if digest(r['spec']) != r['binding'] or r['spec']['policy'] != digest(json.loads(self.policy_path.read_text())):
            raise ValueError('Approval binding changed')
        if 'protocol' in r['spec']:
            from src.local_catalog import PROTOCOL, resolve
            if r['spec']['protocol'] != PROTOCOL:
                raise ValueError('Unsupported task protocol')
            spec, files = resolve(self.policy, r['spec']['task_id'])
            if canonical(spec) != canonical(r['spec']):
                raise ValueError('Reviewed task changed')
            return files
        p = self.policy['repositories']['fort-custer-server']
        if (r['spec']['issue'] != 3 or r['spec']['repo'] != 'fort-custer-server' or
            r['spec']['source'] != p['sha'] or r['spec']['branch'] != p['branch'] or
            r['spec']['prompt'] != PROMPT or r['spec']['allowed'] != ALLOWED):
            raise ValueError('Task changed')
        files = source_files(p['source'], p['sha'])
        if manifest(files) != r['spec']['input_hash']: raise ValueError('Source content changed')
        return files

    def prepare(self, issue, repo, candidate):
        if issue != 3 or repo != 'fort-custer-server': raise ValueError('Only reviewed server issue #3 supported')
        if (candidate.get('number') != 3 or candidate.get('state') != 'open' or 'pull_request' in candidate or
            candidate.get('html_url') != 'https://github.com/MZKZxyz/fort-custer-server/issues/3'):
            raise ValueError('Candidate issue identity mismatch')
        p = self.policy['repositories'][repo]
        files = source_files(p['source'], p['sha'])
        spec = dict(mode=MODE, repo=repo, issue=issue, issue_snapshot=candidate, branch=p['branch'],
                    source=p['sha'], prompt=PROMPT, allowed=ALLOWED, checks=CHECKS,
                    policy=digest(self.policy), input_hash=manifest(files))
        r = dict(id=uuid.uuid4().hex, state='pending', spec=spec, binding=digest(spec),
                 expires=self.clock()+600, history=[dict(event='prepared', at=self.clock())])
        with self.tx() as db: self.save(db, r)
        return r

    def task_list(self):
        from src.local_catalog import resolve
        catalog = self.policy.get('catalog')
        if (not isinstance(catalog, dict) or set(catalog) != {'schema', 'tasks'} or
            type(catalog['schema']) is not int or catalog['schema'] != 1 or
            not isinstance(catalog['tasks'], dict)):
            raise ValueError('Unsupported reviewed catalog')
        tasks = catalog['tasks']
        # Listing fails closed on malformed entries, too.
        return [resolve(self.policy, task)[0] for task in sorted(tasks)]

    def task_prepare(self, task_id):
        from src.local_catalog import resolve
        spec, _ = resolve(self.policy, task_id)
        r = dict(id=uuid.uuid4().hex, state='pending', spec=spec, binding=digest(spec),
                 expires=self.clock()+600, history=[dict(event='prepared', at=self.clock())])
        with self.tx() as db:
            self.check(r)
            # A catalog identifier is single-use, including expired or failed tasks.
            # Retain the original record; no implicit restart or reauthorization.
            if any(json.loads(row[0])['spec'].get('task_id') == task_id
                   for row in db.execute('SELECT document FROM runs')):
                raise ValueError('Catalog task already prepared; operator reconciliation required')
            self.save(db, r)
        return r

    def inspect(self, run):
        # Read-only inspection must also work while publication holds its claim.
        with sqlite3.connect(self.state/'local.sqlite', timeout=10) as db:
            return self.read(db, run)

    def approve(self, run, response):
        with self.tx() as db:
            r = self.read(db, run); self.check(r)
            if r['state'] != 'pending' or response != 'APPROVE '+r['binding']:
                raise ValueError('Fresh exact task authorization required')
            r['state'] = 'approved'
            r['history'].append(dict(event='approved', at=self.clock(), binding=r['binding']))
            self.save(db, r)
        return r

    def cancel(self):
        # Sticky across restart, covers pending/approved/running, never auto-reset.
        self.state.joinpath('STOP').touch(mode=0o600)

    def execute(self, run):
        with self.tx() as db:
            r = self.read(db, run); files = self.check(r)
            if not self.policy['enabled']: raise ValueError('Local mode disabled')
            if r['state'] != 'approved': raise ValueError('Task already claimed or unapproved')
            if any(json.loads(row[0])['state'] == 'running' for row in db.execute('SELECT document FROM runs')):
                raise ValueError('One execution maximum; unresolved restart hold')
            timeout = (r['spec']['limits']['timeout_seconds'] if 'protocol' in r['spec']
                       else self.policy['timeout_seconds'])
            r['state'] = 'running'; r['deadline'] = self.clock()+timeout
            r['history'].append(dict(event='claimed', at=self.clock())); self.save(db, r)
        # Durable claim precedes all subprocesses. A crash retains a hold, never retries.
        start = time.monotonic()
        def stopped():
            return self.state.joinpath('STOP').exists() or self.clock() >= r['deadline']
        try:
            with tempfile.TemporaryDirectory(prefix='coding-', dir=self.scratch) as work:
                root = Path(work); materialize(files, root)
                r['usage'] = LocalCLI(self.policy).run(root, r['spec']['prompt'], stopped, timeout)
                if stopped(): raise ValueError('cancelled')
                candidate = snapshot(root)
                changed = sorted(k for k in files.keys() | candidate.keys() if files.get(k) != candidate.get(k))
                r['files'] = changed
                allowed = r['spec']['allowed']
                if (not changed or not set(changed) <= set(allowed) or
                    any(k not in candidate for k in allowed) or
                    ('protocol' not in r['spec'] and set(changed) != set(ALLOWED))):
                    raise ValueError('Unexpected file modification or empty candidate')
                r['candidate_hash'] = manifest(candidate)
                remaining = timeout-(time.monotonic()-start)
                r['qa'] = (self.qa(files, candidate, stopped, remaining, spec=r['spec'])
                           if 'protocol' in r['spec'] else self.qa(files, candidate, stopped, remaining))
                if stopped() or any(c['code'] or c['reason'] for c in r['qa']):
                    raise ValueError('Independent QA failed or cancelled')
                r['state'] = 'validated'
        except (Exception, KeyboardInterrupt) as error:
            r['state'] = 'failed'
            # Only controller-authored errors, never subprocess/auth diagnostics.
            r['error'] = ('timeout' if self.clock() >= r['deadline'] else
                          str(error) if type(error) is ValueError else type(error).__name__)
        r['history'].append(dict(event=r['state'], at=self.clock()))
        with self.tx() as db: self.save(db, r)
        return r

    def qa(self, files, candidate, stopped, remaining, spec=None):
        with tempfile.TemporaryDirectory(prefix='qa-', dir=self.scratch) as work:
            root = Path(work); materialize(files, root)
            git(root, 'init', '-q')
            git(root, 'add', '--all', '--force')
            git(root, '-c', 'user.name=Local QA', '-c', 'user.email=qa@local', 'commit', '-qm', 'Input')
            for name in (spec['allowed'] if spec else ALLOWED):
                mode, data = candidate[name]; (root/name).write_bytes(data); (root/name).chmod(mode)
            if manifest({k:v for k,v in snapshot(root).items() if not k.startswith('.git/')}) != manifest(candidate):
                raise ValueError('QA candidate identity mismatch')
            git(root, 'add', '--all', '--force')
            candidate_tree = git(root, 'write-tree').decode().strip()
            patch = git(root, 'diff', '--cached', '--binary', '--full-index', 'HEAD', '--')
            git(root, '-c', 'user.name=Local QA', '-c', 'user.email=qa@local', 'commit', '-qm', 'Candidate')
            candidate_revision = git(root, 'rev-parse', 'HEAD').decode().strip()
            node = Path(self.policy['node'])
            if (not node.is_absolute() or node.is_symlink() or not node.is_file() or
                not os.access(node, os.X_OK) or
                hashlib.sha256(node.read_bytes()).hexdigest() != self.policy['node_sha256']):
                raise ValueError('Trusted Node binary changed')
            report = []
            end = time.monotonic()+remaining
            checks = ([(c['name'], c['argv'], c['timeout_seconds']) for c in spec['checks']]
                      if spec else [(label, command, 2400) for label, command in CHECKS])
            commands = [('diff', ['/usr/bin/git', 'diff', '--check', 'HEAD^', 'HEAD'], 30), *checks]
            for label, command, check_timeout in commands:
                left = end-time.monotonic()
                if left <= 0: raise ValueError('timeout')
                command = [str(node), *command[1:]] if command[0] == 'node' else command
                out = supervise(command, root, environment(), timeout=min(left, check_timeout), cancelled=stopped)
                report.append(dict(name=label, command=command, code=out['code'], reason=out['reason'],
                    stdout=out['stdout'].decode(errors='replace'), stderr=out['stderr'].decode(errors='replace')))
            # QA must not create even ignored artifacts or mutate its inputs.
            after = {k:v for k,v in snapshot(root).items() if not k.startswith('.git/')}
            if manifest(after) != manifest(candidate): raise ValueError('QA modified candidate')
            artifact = dict(input_hash=manifest(files), candidate_hash=manifest(candidate),
                            candidate_tree=candidate_tree, candidate_revision=candidate_revision, patch=patch.decode('utf-8'))
            report.append(dict(name='candidate', code=0, reason=None, **artifact))
            return report


def terminal_challenge(challenge):
    # macOS terminals do not support a seekable read/write stream.
    with open('/dev/tty', 'r') as terminal_input, open('/dev/tty', 'w') as terminal_output:
        if not terminal_input.isatty() or not terminal_output.isatty():
            raise ValueError('Controlling terminal required')
        terminal_output.write('Review the complete specification. Type '+challenge+'\n')
        terminal_output.flush()
        return terminal_input.readline().rstrip('\r\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True); parser.add_argument('--state', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--issue', type=int, required=True)
    prep.add_argument('--repo', required=True); prep.add_argument('--issue-file', required=True)
    for cmd in ('inspect', 'approve', 'execute', 'publish-prepare', 'publish-inspect', 'publish-approve', 'publish-cancel'):
        sub.add_parser(cmd).add_argument('run')
    sub.add_parser('cancel')
    sub.add_parser('task-list')
    sub.add_parser('task-prepare').add_argument('task_id')
    args = parser.parse_args(); runner = Runner(args.policy, args.state)
    if args.command == 'task-list':
        result = {'tasks': runner.task_list()}
    elif args.command == 'task-prepare':
        result = runner.task_prepare(args.task_id)
    elif args.command == 'prepare':
        result = runner.prepare(args.issue, args.repo, json.loads(Path(args.issue_file).read_text()))
    elif args.command.startswith('publish-'):
        from src.local_publication import Publications
        publisher = Publications(runner)
        if args.command == 'publish-prepare': result = publisher.prepare(args.run)
        elif args.command == 'publish-inspect': result = publisher.inspect(args.run)
        elif args.command == 'publish-cancel': result = publisher.cancel(args.run)
        else:
            r = publisher.inspect(args.run); print(json.dumps(r, indent=2, ensure_ascii=True))
            result = publisher.approve(args.run, terminal_challenge('PUBLISH '+r['binding']))
    elif args.command == 'inspect': result = runner.inspect(args.run)
    elif args.command == 'approve':
        r = runner.inspect(args.run); print(json.dumps(r, indent=2, ensure_ascii=True))
        # No command-line approval token and no noninteractive --yes path.
        result = runner.approve(args.run, terminal_challenge('APPROVE '+r['binding']))
    elif args.command == 'execute': result = runner.execute(args.run)
    else: runner.cancel(); result = {'state': 'stopped'}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 1 if result.get('state') == 'failed' else 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError):
        raise SystemExit('Local runner blocked; inspect policy, task and persistent state. No fallback.')
