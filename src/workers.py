"""Official Codex CLI invocation contract; deliberately unavailable in Sprint 5.2."""
import json
import subprocess
import tempfile
from pathlib import Path


class CodexCLI:
    @staticmethod
    def command():
        return ('codex', 'exec', '--json', '--sandbox', 'workspace-write',
                '--config', 'sandbox_workspace_write.network_access=false', '-')

    def run(self, *args, **kwargs):
        raise RuntimeError('Live execution disabled: requires separately approved sandbox, billing and credential broker')


class MockWorker:
    identity = 'coding:mock'

    def checkout(self, source, sha, execution, root):
        """Local fixture only; no network, credentials, shared Git objects or hooks."""
        source = Path(source).resolve()
        if not source.is_dir() or len(sha) != 40 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Local repository and exact SHA required')
        directory = Path(tempfile.mkdtemp(prefix='worker-', dir=root))
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(directory), 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-local', '--no-checkout', '--', str(source), str(directory/'repo')], env=env, check=True, capture_output=True, timeout=30)
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'checkout', '-b', 'task/'+execution, sha], cwd=directory/'repo', env=env, check=True, capture_output=True, timeout=30)
        subprocess.run(['git', 'remote', 'remove', 'origin'], cwd=directory/'repo', env=env, check=True, timeout=30)
        return directory

    def run(self, controller, execution, issue_text=''):
        # Untrusted issue text is inert data; never interpolated into commands or policy.
        if not controller.claim(execution, self.identity):
            return {'execution': execution, 'event': 'duplicate_start_ignored'}
        controller.heartbeat(execution, self.identity)
        return {'execution': execution, 'worker': self.identity, 'event': 'mock_started',
                'untrusted_input_bytes': len(json.dumps(issue_text).encode()), 'network': False}

    def cancel(self, controller):
        controller.recover(kill=True)
