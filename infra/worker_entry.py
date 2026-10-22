"""Credential-free container protocol. Never accepts commands from issue text."""
import hashlib
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

LIMIT = 4 * 1024 * 1024
POLICIES = {
    'fixture': [('unit', [sys.executable, '-I', '-c',
        "import sys,unittest;sys.path.insert(0,'/workspace');r=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover('/workspace/test'));sys.exit(not r.wasSuccessful())"])],
    'MZKZxyz/fort-custer-server': [
        ('dependencies', ['npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund']),
        ('unit', ['node', '--test']),
        ('analyzer', ['node', '--test', 'test/analyzer.test.js']),
        ('smoke', ['node', 'tools/maze-analyzer/cli.js', '--seed', 'sprint4-0'])],
    'MZKZxyz/fort-custer-client': [
        ('dependencies', ['npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund']),
        ('unit', ['npm', 'test', '--', '--watchAll=false', '--runInBand']),
        ('build', ['npm', 'run', 'build'])],
}

def tree_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def main():
    # Candidate tests share this UID; prevent them reading/modifying the
    # trusted runner's memory or /proc/PID/fd to forge its evidence stream.
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(4,0,0,0,0) != 0 or libc.prctl(3,0,0,0,0) != 0:
        raise RuntimeError('Nondumpable QA supervisor required')
    raw = sys.stdin.buffer.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Input limit')
    request = json.loads(raw)
    role = os.environ['FC_ROLE']
    if request.get('policy') == 'cancellation-probe':
        import time
        subprocess.Popen([sys.executable,'-c','import time;time.sleep(3600)'],start_new_session=True)
        time.sleep(3600)
        raise RuntimeError('Cancellation probe was not stopped')
    if request.get('policy') == 'probe':
        import runpy
        probe = runpy.run_path('/opt/probe.py')['probe']
        print(json.dumps({'checks':probe()})); return
    files = request['files']
    modes = request['modes']
    if set(modes) != set(files) or any(type(m) is not int or m not in (0o644,0o755) for m in modes.values()):
        raise ValueError('Complete source modes required')
    for name, text in files.items():
        if (not name or name.startswith('/') or '\\' in name
                or any(p in ('', '.', '..', '.git') for p in name.split('/'))
                or not isinstance(text, str)):
            raise ValueError('Unsafe source path')
        p = Path('/workspace') / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode())
        p.chmod(modes[name])
    if tree_digest(dict(files=files,modes=modes)) != request['artifact']:
        raise ValueError('Source artifact mismatch')
    if role == 'coding':
        if request['policy'] != 'fixture' or files.get('calc.py') != 'def add(a,b): return a-b\n':
            raise ValueError('Only synthetic coding is available')
        files['calc.py'] = 'def add(a,b): return a+b\n'
        result = dict(files=files,modes=modes, artifact=tree_digest(dict(files=files,modes=modes)), synthetic=True)
    elif role == 'qa':
        checks = list(POLICIES[request['policy']])
        if request['policy'] == 'MZKZxyz/fort-custer-server':
            checks += [('syntax:'+p, ['node', '--check', '--', p]) for p in sorted(files) if p.endswith('.js')]
        if request['policy'] == 'MZKZxyz/fort-custer-client':
            package = json.loads(files.get('package.json', '{}'))
            if 'test:e2e' in package.get('scripts', {}):
                checks.append(('browser', ['npm', 'run', 'test:e2e']))
        tests = []
        for name, argv in checks:
            try:
                # Container tmpfs + file size limit bound all command output.
                with open('/tmp/stdout', 'w+b') as out, open('/tmp/stderr', 'w+b') as err:
                    proc = subprocess.run(argv, cwd='/workspace', stdin=subprocess.DEVNULL,
                        stdout=out, stderr=err, timeout=180,
                        env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp',
                             'CI':'true','NODE_ENV':'test','npm_config_cache':'/opt/npm-cache',
                             'MONGOD_BINARY':'/opt/mongodb/mongod','MONGOMS_RUNTIME_DOWNLOAD':'false','PLAYWRIGHT_BROWSERS_PATH':'/opt/browsers'})
                    out.seek(0); err.seek(0)
                    stdout, stderr = out.read(8*1024*1024), err.read(8*1024*1024)
                tests.append(dict(name=name, command=argv, exit_code=proc.returncode,
                    stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                    stderr_sha256=hashlib.sha256(stderr).hexdigest(),
                    output=hashlib.sha256(stdout+stderr).hexdigest(),
                    status='passed' if proc.returncode == 0 else 'failed'))
            except (OSError, subprocess.TimeoutExpired):
                tests.append(dict(name=name, command=argv, exit_code=None, status='failed', error='required command unavailable or timed out'))
            if tests[-1]['status'] != 'passed':
                break
        result = dict(tests=tests, artifact=tree_digest(dict(files=files,modes=modes)), source=request['source'],
                      candidate=request['candidate'], policy=request['policy'])
    else:
        raise ValueError('Unknown role')
    print(json.dumps(result, sort_keys=True))

if __name__ == '__main__':
    main()
