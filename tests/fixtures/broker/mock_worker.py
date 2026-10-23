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

listener = int(sys.argv[1])
# Test launch must close every inherited descriptor except the one listener.
for fd in range(3, 256):
    if fd == listener: continue
    try: os.fstat(fd)
    except OSError: continue
    raise RuntimeError('Unexpected inherited descriptor')
if set(os.environ)-{'PATH', 'HOME', 'LANG', 'LC_CTYPE'}:
    raise RuntimeError('Unexpected inherited environment')


def canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def read(sock, size):
    out = b''
    while len(out) < size:
        chunk = sock.recv(size-len(out))
        if not chunk: raise ValueError('Truncated request')
        out += chunk
    return out


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
