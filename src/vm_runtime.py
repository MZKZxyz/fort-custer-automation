"""Narrow VM control interface. Never falls back to container or host execution.

An independently deployed provider owns VM creation, signature verification,
host deadline enforcement and guest transport. This repository does not pretend
that a provider declaration is an attested production VM deployment.
"""
import json
import re
import socket
import struct
from pathlib import Path
from trust import canonical, digest, require_live, sha
from readiness import protected_file

OPERATIONS = frozenset(('provision', 'inspect', 'exchange', 'terminate', 'absent', 'inventory'))


class UnixVMProvider:
    synthetic = False
    def __init__(self, path):
        import stat
        self.path = Path(path)
        protected_file(self.path.parent)
        info = self.path.lstat()
        # A root-owned IPC socket may allow the restricted controller group to
        # connect. Group write on the socket grants connect, not code/config edits.
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o007):
            raise ValueError('Privileged VM provider socket required')

    def call(self, operation, payload):
        if operation not in OPERATIONS:
            raise ValueError('Provider operation denied')
        raw = canonical(dict(version=1, operation=operation, payload=payload)).encode()+b'\n'
        if len(raw) > 4*1024*1024:
            raise ValueError('Provider request too large')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(15); client.connect(str(self.path))
            _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != 0:
                raise ValueError('Provider peer identity rejected')
            client.sendall(raw); client.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                part = client.recv(65536)
                if not part:
                    break
                response.extend(part)
                if len(response) > 4*1024*1024:
                    raise ValueError('Provider response limit')
        result = json.loads(response)
        if set(result) != {'version', 'operation', 'result'} or result['version'] != 1 or result['operation'] != operation:
            raise ValueError('Provider response binding rejected')
        return result['result']


def validate_inspection(result, request):
    expected = dict(execution=request['execution'], source=request['source'], scope=digest(request['scope']),
                    image=request['image'], deadline=request['deadline'], isolation='microvm',
                    network='none', host_mounts=[], credentials=[], metadata_access=False,
                    broker_transport='vsock-task-scoped', signed_request=digest(request),
                    watchdog='independent-host', ephemeral=True)
    if result != expected:
        raise ValueError('VM effective configuration mismatch')
    return expected


class VMRuntime:
    def __init__(self, provider, verifier, clock):
        self.provider, self.verifier, self.clock = provider, verifier, clock

    def run(self, request, envelope, exchange, cancelled=lambda: False):
        if not self.provider.synthetic:
            require_live()
        if (set(request) != {'execution', 'task', 'source', 'scope', 'image', 'issued', 'deadline'}
                or not re.fullmatch('[a-f0-9]{32}', request['execution'])
                or type(request['issued']) is not int or type(request['deadline']) is not int
                or not request['issued'] <= self.clock() < request['deadline'] <= request['issued']+2400
                or not re.fullmatch('sha256:[a-f0-9]{64}', request['image'])):
            raise ValueError('VM execution identity or nonrenewable deadline rejected')
        sha(request['source'])
        from independent_qa import safe_path, protected
        if (not isinstance(request['scope'], list) or not request['scope']
                or any(not safe_path(p) or protected(p) for p in request['scope'])
                or sorted(set(request['scope'])) != request['scope']):
            raise ValueError('VM task scope rejected')
        self.verifier.verify(envelope, 'vm-execution', request, self.clock())
        identity = dict(execution=request['execution'])
        try:
            # Durable execution ID is assigned BEFORE provision. Even a lost
            # provision response must terminate by that ID, without blind retries.
            self.provider.call('provision', dict(request=request, envelope=envelope))
            validate_inspection(self.provider.call('inspect', identity), request)
            if cancelled() or self.clock() >= request['deadline']:
                raise ValueError('Cancelled or expired before exchange')
            result = exchange(self.provider, request)
            if cancelled() or self.clock() >= request['deadline']:
                raise ValueError('Cancelled or expired during exchange')
            return result
        finally:
            self.provider.call('terminate', identity)
            absence = self.provider.call('absent', identity)
            if absence != dict(execution=request['execution'], vm_absent=True, disks_absent=True,
                               transport_revoked=True, watchdog_record_retained=True):
                raise RuntimeError('Cleanup unverified: fence execution and retain all reservations')


class SyntheticVMProvider:
    """Lifecycle contract double only; it runs no repository code or guest VM."""
    synthetic = True
    def __init__(self):
        self.requests, self.removed, self.calls = {}, set(), []

    def call(self, operation, payload):
        self.calls.append(operation)
        if operation == 'provision':
            r = payload['request']; execution = r['execution']
            if execution in self.requests or execution in self.removed:
                raise ValueError('Execution identity cannot be reused')
            self.requests[execution] = r
            return dict(execution=execution)
        execution = payload['execution']
        if operation == 'inspect':
            r = self.requests[execution]
            return dict(execution=execution, source=r['source'], scope=digest(r['scope']), image=r['image'],
                        deadline=r['deadline'], isolation='microvm', network='none', host_mounts=[], credentials=[],
                        metadata_access=False, broker_transport='vsock-task-scoped', signed_request=digest(r),
                        watchdog='independent-host', ephemeral=True)
        if operation == 'terminate':
            self.requests.pop(execution, None); self.removed.add(execution); return {}
        if operation == 'absent':
            return dict(execution=execution, vm_absent=execution not in self.requests, disks_absent=True,
                        transport_revoked=True, watchdog_record_retained=True)
        raise ValueError('Unsupported synthetic operation')
