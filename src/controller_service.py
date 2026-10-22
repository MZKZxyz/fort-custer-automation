"""Local authenticated administrative service. No dispatch or publishing endpoint.

SO_PEERCRED comes from the kernel; JSON cannot select a caller identity. Root
owns config and code, while a restricted service identity owns the ledger.
Existing ledgers only. Recovery fences active tasks and never frees money.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import time
from trust import canonical
from readiness import protected_file


@contextmanager
def transaction(path):
    if Path(path).is_symlink() or not Path(path).is_file():
        raise ValueError('Existing authoritative ledger required')
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw', uri=True, timeout=10) as db:
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Ledger integrity failure')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT version FROM metadata').fetchall() != [(1,)]:
            raise ValueError('Unsupported planning history')
        db.execute('SELECT stopped FROM s53_control').fetchone()
        yield db


def recover(path, now):
    with transaction(path) as db:
        # On every controller restart, all previously active workers are orphaned
        # until provider inventory + termination have been independently verified.
        for run, in db.execute("SELECT id FROM s53_runs WHERE state IN ('dispatched','running','stopping')").fetchall():
            db.execute("UPDATE s53_runs SET state='reconciliation_required' WHERE id=?", (run,))
            db.execute('INSERT INTO s53_events(at,run,event,payload) VALUES (?,?,?,?)',
                       (now, run, 'startup_fenced', canonical(dict(reservation_retained=True))))


def admin(path, request, uid, allowed, now):
    if uid not in allowed:
        raise ValueError('Operator OS identity not allowed')
    if set(request) != {'operation'} or request['operation'] not in ('status', 'kill'):
        raise ValueError('Administrative operation denied')
    with transaction(path) as db:
        if request['operation'] == 'kill':
            db.execute('UPDATE s53_control SET stopped=1')
            db.execute("UPDATE s53_runs SET state='stopping' WHERE state IN ('dispatched','running','reconciliation_required')")
        db.execute('INSERT INTO s53_events(at,run,event,payload) VALUES (?,NULL,?,?)',
                   (now, 'admin_'+request['operation'], canonical(dict(peer_uid=uid))))
        return dict(stopped=bool(db.execute('SELECT stopped FROM s53_control').fetchone()[0]),
                    unresolved=db.execute('SELECT count(*) FROM s53_runs WHERE stopped=0 OR final IS NULL').fetchone()[0],
                    live_execution=False)


def verify_release(root, manifest):
    entries = json.loads(protected_file(manifest).read_text())
    files = {str(p.relative_to(root)) for folder in ('src', 'config', 'infra')
             for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if set(entries) != files:
        raise ValueError('Incomplete immutable release manifest')
    for name, expected in entries.items():
        p = protected_file(root/name)
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('Immutable release digest mismatch')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['serve', 'status', 'kill'])
    parser.add_argument('--config', type=Path, default=Path('/etc/fort-custer/controller.json'))
    args = parser.parse_args()
    config = json.loads(protected_file(args.config).read_text())
    address = config['socket']
    if args.action != 'serve':
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(10); client.connect(address)
            client.sendall(canonical(dict(operation=args.action)).encode()+b'\n'); client.shutdown(socket.SHUT_WR)
            print(client.recv(8192).decode())
        return
    verify_release(Path(config['release_root']), Path(config['release_manifest']))
    recover(config['ledger'], int(time.time()))
    # systemd owns the runtime directory. A flock prevents competing startup.
    import fcntl
    with open(address+'.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Path(address).unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(address); os.chmod(address, 0o660); server.listen(8)
            while True:
                client, _ = server.accept()
                with client:
                    client.settimeout(5)
                    _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    try:
                        data = bytearray()
                        while b'\n' not in data:
                            part = client.recv(1024)
                            if not part: break
                            data.extend(part)
                            if len(data) > 4096: raise ValueError('Request too large')
                        result = admin(config['ledger'], json.loads(data), uid, config['operator_uids'], int(time.time()))
                    except (ValueError, sqlite3.Error, OSError):
                        result = dict(error='Administrative request rejected')
                    try: client.sendall(canonical(result).encode())
                    except OSError: pass


if __name__ == '__main__':
    main()
