"""Consistent SQLite snapshots encrypted with age to an operator-owned recipient.

Never initializes, overwrites or restores over an authoritative ledger. Restore
always targets a new path for independent inspection before operator cutover.
Private key material is passed by path to age, never read by Python or logged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile


def snapshot(source, target):
    source, target = Path(source), Path(target)
    if source.is_symlink() or not source.is_file() or target.exists():
        raise ValueError('Existing source and unused snapshot path required')
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Source integrity failed')
        with sqlite3.connect(target) as backup:
            db.backup(backup)
    target.chmod(0o600)
    return inspect(target)


def inspect(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Restore integrity failed')
        if db.execute('SELECT version FROM metadata').fetchall() != [(1,)]:
            raise ValueError('Unsupported ledger')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {name: db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
        # logical dump preserves audit/reservation contents independently of page layout.
        logical = hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
    return dict(logical_sha256=logical, rows=counts)


def backup(source, destination, recipient):
    if not recipient.startswith('age1') or len(recipient) > 128:
        raise ValueError('Operator-provisioned age recipient required')
    destination = Path(destination)
    # Exclusive output creation: repeated backup never replaces retained evidence.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output, tempfile.TemporaryDirectory() as d:
            plain = Path(d)/'snapshot.db'
            evidence = snapshot(source, plain)
            subprocess.run(['age', '--encrypt', '--recipient', recipient, str(plain)],
                           stdout=output, stderr=subprocess.PIPE, check=True, timeout=120)
            output.flush(); os.fsync(output.fileno())
        return dict(evidence, encrypted_sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def restore(encrypted, identity, target):
    target = Path(target)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            subprocess.run(['age', '--decrypt', '--identity', str(identity), str(encrypted)],
                           stdout=output, stderr=subprocess.PIPE, check=True, timeout=120)
            output.flush(); os.fsync(output.fileno())
        return inspect(target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='action', required=True)
    b = commands.add_parser('backup'); b.add_argument('source'); b.add_argument('destination'); b.add_argument('--recipient', required=True)
    r = commands.add_parser('restore'); r.add_argument('encrypted'); r.add_argument('target'); r.add_argument('--identity', required=True)
    args = parser.parse_args()
    result = backup(args.source, args.destination, args.recipient) if args.action == 'backup' else restore(args.encrypted, args.identity, args.target)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
