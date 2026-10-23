"""Offline counterexample/OS probe for official Codex 0.163.0 exec-server.

Not a worker, grant consumer, authentication relay or activation mechanism.
Only fixed operations against temporary synthetic files are exposed by main().
Never point this diagnostic at a logged-in CODEX_HOME or real source tree.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time

from src.codex_worker import CLI_VERSION

MAXIMUM = 1024 * 1024


class _Executor:
    """Private bounded JSONL adapter; no network registration or inference."""
    def __init__(self, binary, root):
        self.binary, self.root = str(Path(binary).resolve(strict=True)), Path(root).resolve()
        self.env = dict(PATH='/usr/bin:/bin', HOME=str(self.root),
                        CODEX_HOME=str(self.root/'codex-home'), TMPDIR=str(self.root), LANG='C')
        self.process = None
        self.buffer = b''
        self.counter = 0

    def __enter__(self):
        version = subprocess.run([self.binary, '--version'], env=self.env, cwd=self.root,
                                 capture_output=True, timeout=5, check=True)
        if version.stdout.strip() != ('codex-cli '+CLI_VERSION).encode():
            raise ValueError('Unreviewed Codex version; do not auto-upgrade')
        self.stderr = tempfile.TemporaryFile()
        self.process = subprocess.Popen([self.binary, 'exec-server', '--listen', 'stdio://'],
            cwd=self.root, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr, start_new_session=True, close_fds=True, bufsize=0)
        try:
            result = self.rpc('initialize', dict(clientName='fort-custer-offline-probe'))
            if result.get('result', {}).get('environmentInfo', {}).get('executorVersion') != CLI_VERSION:
                raise ValueError('Executor protocol version mismatch')
            self.process.stdin.write(b'{"method":"initialized","params":{}}\n')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.process is not None:
            # Probe-owned process group only. This is not VM termination proof.
            try: os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            self.process.wait(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()
            self.stderr.close()

    def rpc(self, method, params):
        self.counter += 1
        ident = self.counter
        raw = json.dumps(dict(id=ident, method=method, params=params)).encode()+b'\n'
        if len(raw) > MAXIMUM: raise ValueError('Request ceiling')
        self.process.stdin.write(raw)
        end = time.monotonic()+10
        total = 0
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                while b'\n' in self.buffer:
                    line, self.buffer = self.buffer.split(b'\n', 1)
                    message = json.loads(line)
                    if message.get('id') == ident: return message
                    if message.get('method') not in {'process/output', 'process/exited', 'process/closed'}:
                        raise ValueError('Unknown executor notification')
                left = end-time.monotonic()
                if left <= 0 or not selector.select(left): raise TimeoutError('Executor deadline')
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk: raise ValueError('Executor disconnected')
                total += len(chunk)
                if total > MAXIMUM or self.stderr.tell() > MAXIMUM:
                    raise ValueError('Executor output ceiling')
                self.buffer += chunk


def _context(workspace, protected, allowed):
    def entry(path, access):
        return dict(path=dict(type='path', path=path.as_uri()), access=access)
    # Root-readable baseline plus explicit protected denials. Only one file is
    # writable; the workspace as a whole is never a writable root.
    entries = [dict(path=dict(type='special', value=dict(kind='root')), access='read'),
               entry(allowed, 'write'), entry(protected, 'deny')]
    return dict(permissions=dict(type='managed', file_system=dict(type='restricted', entries=entries),
                                 network='restricted'), cwd=workspace.as_uri(),
                workspaceRoots=[workspace.as_uri()], windowsSandboxLevel='disabled')


def _local_counterexample(root, allowed, auth, marker):
    """Independent same-UID process evidence; never invokes a sandbox helper."""
    env = dict(PATH='/usr/bin:/bin', HOME=str(root), CODEX_HOME=str(root/'codex-home'), LANG='C')
    def cat(path):
        return subprocess.run(['/bin/cat', str(path)], cwd=root, env=env,
                              capture_output=True, timeout=5, check=False)
    control = cat(allowed)
    positive = control.returncode == 0 and control.stdout == b'baseline' and not control.stderr
    result = cat(auth) if positive else None
    readable = (result.returncode == 0 and result.stdout == marker and not result.stderr
                if result is not None else None)
    return dict(positive_read=positive, auth_readable=readable)


def _process_cat(server, ident, path, workspace):
    """Collect bounded output through terminal status, not just the first chunk.

    process/start success does not prove the executable started. Runtime/helper
    failures can arrive later through process/read. Missing terminal evidence is
    unavailable, never a credential denial.
    """
    started = server.rpc('process/start', dict(processId=ident,
        argv=['/bin/cat', str(path)], cwd=workspace.as_uri(), env={'PATH': '/usr/bin:/bin'},
        tty=False, pipeStdin=False, arg0=None, sandbox=None))
    if 'error' in started:
        return dict(complete=False, stdout=b'', denied=False)
    after = None
    data = b''
    # Each RPC already has a 10-second wall bound; no indefinite polling/replay.
    for _ in range(5):
        output = server.rpc('process/read', dict(processId=ident, afterSeq=after,
                                                maxBytes=4096, waitMs=1000))
        if 'error' in output:
            return dict(complete=False, stdout=b'', denied=False)
        result = output['result']
        for chunk in result['chunks']:
            after = chunk['seq']
            raw = base64.b64decode(chunk['chunk'], validate=True)
            if chunk['stream'] == 'stdout': data += raw
            if len(data) > 4096: raise ValueError('Process probe output ceiling')
        if result.get('exited') is True:
            return dict(complete=result.get('exitCode') == 0 and result.get('failure') is None
                        and result.get('sandboxDenied') is False,
                        stdout=data, denied=result.get('sandboxDenied') is True
                        and result.get('failure') is None)
    return dict(complete=False, stdout=b'', denied=False)


def _process_counterexample(server, workspace, allowed, auth, marker):
    control = _process_cat(server, 'synthetic-control', allowed, workspace)
    positive = control['complete'] and control['stdout'] == b'baseline'
    if not positive:
        return dict(positive_read=False, state='unavailable', auth_readable=None)
    result = _process_cat(server, 'synthetic-cat', auth, workspace)
    if result['complete']:
        readable = result['stdout'] == marker
        return dict(positive_read=True, state='observed-readable' if readable else 'unexpected-output',
                    auth_readable=readable)
    if result['denied']:
        return dict(positive_read=True, state='observed-denial', auth_readable=False)
    return dict(positive_read=True, state='unavailable', auth_readable=None)


def probe(binary):
    """Create and destroy our own nonsecret fixtures. Return booleans, no data."""
    with tempfile.TemporaryDirectory(prefix='fc-611-') as tmp:
        root = Path(tmp).resolve()
        home, protected, workspace = root/'codex-home', root/'protected', root/'workspace'
        for folder in (home, protected, workspace): folder.mkdir(mode=0o700)
        # This is deliberately NOT a valid auth.json and cannot authenticate.
        marker = b'FORT_CUSTER_SYNTHETIC_NOT_A_CREDENTIAL'
        auth = home/'auth.json'; auth.write_bytes(marker); auth.chmod(0o600)
        sentinels = [protected/name for name in ('credentials', 'policy', 'approvals', 'publisher')]
        for path in sentinels: path.write_bytes(marker); path.chmod(0o600)
        allowed, forbidden = workspace/'allowed.txt', workspace/'unapproved.txt'
        for path in (allowed, forbidden): path.write_text('baseline')
        # Explicit denials for synthetic auth and controller storage.
        context = _context(workspace, protected, allowed)
        context['permissions']['file_system']['entries'].append(
            dict(path=dict(type='path', path=home.as_uri()), access='deny'))
        local = _local_counterexample(root, allowed, auth, marker)
        with _Executor(binary, root) as server:
            def read(path, sandbox):
                return server.rpc('fs/readFile', dict(path=path.as_uri(), sandbox=sandbox))
            process = _process_counterexample(server, workspace, allowed, auth, marker)
            direct = read(auth, None)
            readable = base64.b64decode(direct['result']['dataBase64'], validate=True) == marker
            denials = [bool(read(path, context).get('error')) for path in [auth, *sentinels]]
            # A positive sandbox control prevents helper startup failure from
            # masquerading as a successful denial test.
            positive = read(allowed, context)
            setup_failure = ('app-server-socket-directory-unavailable' if
                'app-server socket directory must be a user-owned directory with mode 0700' in
                positive.get('error', {}).get('message', '') else 'positive-control-failed')
            setup_detail = positive.get('error', {}).get('message', '').replace(str(root), '<fixture>')[:1024]
            positive = ('result' in positive and base64.b64decode(
                positive['result']['dataBase64'], validate=True) == b'baseline')
            def write(path):
                return server.rpc('fs/writeFile', dict(path=path.as_uri(),
                    dataBase64=base64.b64encode(b'changed').decode(), sandbox=context))
            writable = 'result' in write(allowed) and allowed.read_bytes() == b'changed'
            denied_write = bool(write(forbidden).get('error')) and forbidden.read_bytes() == b'baseline'
            unknown = server.rpc('fort-custer/unsupported', {})
            # Omitting sandbox is an executor capability, not an enforcement
            # boundary. A receiver MUST never trust caller-selected policies.
            omitted = read(protected/'policy', None)
            bypass = base64.b64decode(omitted['result']['dataBase64'], validate=True) == marker
        controls = positive and writable
        verified = controls and all(denials) and denied_write
        return dict(schema='codex-boundary-probe-v1', cli_version=CLI_VERSION,
            synthetic_only=True, inference=False, live_ready=False,
            same_uid_auth_readable=readable,
            same_uid_subprocess_positive_read=local['positive_read'],
            same_uid_subprocess_auth_readable=local['auth_readable'],
            executor_process_positive_read=process['positive_read'],
            executor_process_state=process['state'],
            same_uid_process_auth_readable=process['auth_readable'],
            explicit_sandbox_positive_read=positive,
            platform_sandbox_state='verified' if verified else 'failed-denial' if controls else 'unavailable',
            sandbox_setup_failure=None if controls else setup_failure,
            sandbox_setup_detail=None if controls else setup_detail,
            explicit_sandbox_denials=denials if controls else None,
            approved_write=writable,
            unapproved_write_denied=denied_write if controls else None,
            unknown_rpc_rejected='error' in unknown,
            omitted_sandbox_reads_controller_sentinel=bypass,
            transport='actual-official-exec-server-stdio',
            enforcement='platform-sandbox' if verified else 'unverified-denial-failed' if controls else 'unverified-positive-control-failed',
            limitations=['not-model-tool-routing-proof', 'not-cross-user-or-VM-proof',
                         'not-network-resource-or-descendant-termination-proof'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(probe(args.codex), sort_keys=True, indent=2))
    return 1  # Counterexample/readiness evidence never authorizes execution.


if __name__ == '__main__':
    raise SystemExit(main())
