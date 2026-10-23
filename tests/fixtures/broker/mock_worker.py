"""Inert one-shot socket fixture, launched only by tests with no credentials.

This uses the test user's UID and is deliberately NOT an isolation deployment.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import sys

def validate_environment(env, platform, uid):
    allowed = {'PATH', 'HOME', 'LANG', 'LC_CTYPE'}
    if platform == 'darwin':
        # CoreFoundation may populate this at process startup. The launcher sets
        # it explicitly; accept only the exact non-secret UID/encoding metadata.
        expected = f'0x{uid:X}:0x0:0x0'
        if env.get('__CF_USER_TEXT_ENCODING') != expected:
            raise RuntimeError('Invalid macOS user text encoding metadata')
        allowed.add('__CF_USER_TEXT_ENCODING')
    unexpected = set(env)-allowed
    if unexpected:
        raise RuntimeError('Unexpected inherited environment keys: '+','.join(sorted(unexpected)))


def canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def read(sock, size):
    out = b''
    while len(out) < size:
        chunk = sock.recv(size-len(out))
        if not chunk: raise ValueError('Truncated request')
        out += chunk
    return out


def main():
    listener = int(sys.argv[1])
    # Test launch must close every inherited descriptor except the one listener.
    for fd in range(3, 256):
        if fd == listener: continue
        try: os.fstat(fd)
        except OSError: continue
        raise RuntimeError('Unexpected inherited descriptor')
    validate_environment(os.environ, sys.platform, os.getuid())

    with socket.socket(fileno=listener) as server:
        server.settimeout(3)
        with server.accept()[0] as conn:
            conn.settimeout(3)
            size = struct.unpack('!I', read(conn, 4))[0]
            if not 0 < size <= 1048576: raise ValueError('Oversized request')
            raw = read(conn, size); req = json.loads(raw)
            if 'policy_path' in req or 'checks' in req: raise ValueError('Control plane leak')
            payload = {}
            for name in req['allowed']:
                path = Path(name)
                if path.is_absolute() or '..' in path.parts: raise ValueError('Unsafe fixture path')
                payload[name] = [path.stat().st_mode & 0o777, (path.read_bytes()+b'\n// socket process fixture\n').hex()]
            response = canonical(dict(schema=req['schema'], request=hashlib.sha256(raw).hexdigest(),
                token=req['token'], generation=req['generation'], artifact=payload,
                artifact_digest=hashlib.sha256(canonical(payload)).hexdigest()))
            conn.sendall(struct.pack('!I',len(response))+response)


if __name__ == '__main__':
    main()
