"""Isolated manual discovery CLI. Recommendations never confer authorization."""
import argparse
import contextlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from src.discovery_collection import (Collector, PublicGitHub, REPOSITORIES, canonical, decode, timestamp)
from src.discovery_analysis import (DeterministicAnalyzer, WEIGHTS, digest, proposal, validate_proposal)

CONFIG_FIELDS = {'schema', 'repositories', 'stop_files', 'page_size', 'max_pages', 'max_requests',
                 'max_issues', 'max_snapshots', 'max_events', 'max_storage_bytes', 'weights'}
TABLES = {'metadata', 'snapshots', 'proposals', 'events', 'checkpoints'}


def validate_config(config):
    if not isinstance(config, dict) or set(config) != CONFIG_FIELDS or config['schema'] != 'discovery-config-v1':
        raise ValueError('Unsupported discovery configuration')
    repos = config['repositories']
    if (not isinstance(repos, list) or not repos or any(not isinstance(r, str) or r not in REPOSITORIES for r in repos)
        or len(set(repos)) != len(repos)):
        raise ValueError('Unsupported discovery scope')
    stops = config['stop_files']
    if (not isinstance(stops, list) or not stops or any(not isinstance(p, str) or
        not Path(p).is_absolute() or Path(p).name != 'STOP' for p in stops)):
        raise ValueError('Explicit existing controller STOP locations required')
    limits = dict(page_size=(1,100), max_pages=(1,100), max_requests=(1,10000), max_issues=(1,10000),
                  max_snapshots=(1,100000), max_events=(1,300000), max_storage_bytes=(1024,1024**3))
    for key, (low, high) in limits.items():
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError('Invalid discovery bounds')
    if (not isinstance(config['weights'], dict) or set(config['weights']) != set(WEIGHTS) or
        any(type(v) is not int or not -100 <= v <= 100 for v in config['weights'].values())):
        raise ValueError('Invalid reviewed weights')
    return json.loads(canonical(config))


class Store:
    """A new, explicitly initialized database. Never upgrades another system's ledger."""
    def __init__(self, path):
        self.path = Path(path).resolve()

    def initialize(self):
        # Exclusive creation prevents accidental replacement or migration of any state.
        with self.path.open('xb'):
            pass
        with sqlite3.connect(self.path) as db:
            db.executescript('''
            CREATE TABLE metadata (schema TEXT NOT NULL);
            INSERT INTO metadata VALUES ('discovery-store-v1');
            CREATE TABLE snapshots (id TEXT PRIMARY KEY, document TEXT NOT NULL);
            CREATE TABLE proposals (id TEXT PRIMARY KEY, document TEXT NOT NULL);
            CREATE TABLE events (sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, at TEXT NOT NULL);
            CREATE TABLE checkpoints (repository TEXT PRIMARY KEY, at TEXT NOT NULL);
            ''')
            for table in ('snapshots', 'proposals', 'events', 'metadata'):
                for operation in ('UPDATE', 'DELETE'):
                    db.execute(f'CREATE TRIGGER immutable_{table}_{operation} BEFORE {operation} ON {table} '
                               "BEGIN SELECT RAISE(ABORT, 'Immutable discovery evidence'); END")

    @contextlib.contextmanager
    def tx(self, readonly=False):
        with sqlite3.connect(self.path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=10) as db:
            if not readonly:
                db.execute('BEGIN IMMEDIATE')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != TABLES or db.execute('SELECT schema FROM metadata').fetchall() != [('discovery-store-v1',)]:
                raise ValueError('Unsupported discovery database; no migration allowed')
            if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise ValueError('Discovery integrity check failed')
            yield db

    def proposals(self):
        with self.tx(readonly=True) as db:
            result = [validate_proposal(json.loads(row[0])) for row in db.execute('SELECT document FROM proposals')]
        return sorted(result, key=lambda p:(-p['priority'], p['repository'], p['issue_number'], p['id']))

    def inspect(self, identity):
        with self.tx(readonly=True) as db:
            row = db.execute('SELECT document FROM proposals WHERE id=?', (identity,)).fetchone()
            if not row:
                raise ValueError('Unknown proposal')
            p = validate_proposal(json.loads(row[0]))
            evidence = db.execute('SELECT document FROM snapshots WHERE id=?', (p['snapshot'],)).fetchone()
            if not evidence or digest(json.loads(evidence[0])) != p['snapshot']:
                raise ValueError('Corrupt snapshot evidence')
            expected = digest(dict(schema=p['schema'], snapshot=p['snapshot'], analysis=p['analysis_version'], policy=p['policy_digest']))
            if identity != p['id'] or identity != expected:
                raise ValueError('Corrupt proposal identity')
            events = [dict(sequence=r[0], kind=r[1], subject=r[2], at=r[3]) for r in db.execute(
                'SELECT * FROM events WHERE subject IN (?,?) ORDER BY sequence', (identity, p['snapshot']))]
            observations = []
            for sid, document in db.execute('SELECT id, document FROM snapshots ORDER BY id'):
                snapshot = json.loads(document)
                if snapshot['repository'] == p['repository'] and snapshot['number'] == p['issue_number']:
                    if digest(snapshot) != sid:
                        raise ValueError('Corrupt related snapshot')
                    observed = db.execute("SELECT at FROM events WHERE kind='discovered' AND subject=?", (sid,)).fetchone()
                    if not observed:
                        raise ValueError('Missing discovery audit')
                    observations.append(dict(snapshot=sid, at=observed[0], availability=snapshot['availability'],
                                             state=snapshot.get('issue', {}).get('state'),
                                             source_commit=snapshot['source_commit']))
            observations.sort(key=lambda o:(o['at'], o['snapshot']))
            return dict(proposal=p, snapshot=json.loads(evidence[0]), events=events, observations=observations,
                        notice='Untrusted recommendation. No coding, QA, catalog or publication authority.')


class Discovery:
    def __init__(self, config, store, transport=None, analyzer=None, cancelled=lambda:False,
                 clock=lambda:datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')):
        self.config, self.store = validate_config(config), store
        self.transport = transport if transport is not None else PublicGitHub()
        self.analyzer = analyzer if analyzer is not None else DeterministicAnalyzer()
        self.cancelled, self.clock = cancelled, clock

    def guard(self):
        if self.cancelled() or any(Path(p).exists() for p in self.config['stop_files']):
            raise ValueError('Discovery stopped or cancelled')

    def discover(self):
        self.guard()
        started = timestamp(self.clock())
        # One transaction across the bounded scan: failures never advance checkpoints.
        # Restart re-reads the overlap, rather than trusting unstable page cursors.
        with self.store.tx() as db:
            checkpoints = dict(db.execute('SELECT repository, at FROM checkpoints'))
            existing = [json.loads(r[0]) for r in db.execute('SELECT document FROM snapshots')]
            if len(existing) >= self.config['max_snapshots']:
                raise ValueError('Retention capacity reached; preserve and rotate store manually')
            collector = Collector(self.transport, self.config, self.guard)
            ids = []
            for repo in self.config['repositories']:
                since = checkpoints.get(repo)
                if since and started < timestamp(since):
                    raise ValueError('Clock moved before checkpoint')
                known = {s['number'] for s in existing if s['repository'] == repo}
                snapshots = collector.collect(repo, since, known)
                for snapshot in snapshots:
                    self.guard()
                    sid = digest(snapshot)
                    row = db.execute('SELECT document FROM snapshots WHERE id=?', (sid,)).fetchone()
                    if row and row[0] != canonical(snapshot):
                        raise ValueError('Conflicting snapshot digest')
                    if not row:
                        db.execute('INSERT INTO snapshots VALUES (?,?)', (sid, canonical(snapshot)))
                        db.execute('INSERT INTO events(kind,subject,at) VALUES (?,?,?)', ('discovered', sid, started))
                    if snapshot['availability'] == 'present' and snapshot['issue']['state'] == 'open':
                        p = proposal(snapshot, sid, started, self.config, self.analyzer)
                        old = db.execute('SELECT document FROM proposals WHERE id=?', (p['id'],)).fetchone()
                        if old:
                            previous = json.loads(old[0])
                            p['discovered_at'] = previous['discovered_at']
                            if canonical(p) != old[0]:
                                raise ValueError('Conflicting immutable proposal')
                        else:
                            db.execute('INSERT INTO proposals VALUES (?,?)', (p['id'], canonical(p)))
                            db.execute('INSERT INTO events(kind,subject,at) VALUES (?,?,?)', ('proposed', p['id'], started))
                        ids.append(p['id'])
                db.execute('INSERT INTO checkpoints VALUES (?,?) ON CONFLICT(repository) DO UPDATE SET at=excluded.at', (repo, started))
            self.guard()
            size = sum(db.execute('SELECT COALESCE(SUM(length(CAST(document AS BLOB))),0) FROM '+t).fetchone()[0]
                       for t in ('snapshots', 'proposals'))
            if (db.execute('SELECT count(*) FROM snapshots').fetchone()[0] > self.config['max_snapshots'] or
                db.execute('SELECT count(*) FROM events').fetchone()[0] > self.config['max_events'] or
                size > self.config['max_storage_bytes']):
                raise ValueError('Retention bound exceeded; scan rolled back')
        return sorted(ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, help='Separate discovery SQLite file')
    parser.add_argument('--config', help='Operator-owned discovery configuration')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('init', 'discover', 'proposals'):
        sub.add_parser(command)
    sub.add_parser('inspect').add_argument('id')
    args = parser.parse_args()
    store = Store(args.state)
    if args.command == 'init':
        store.initialize(); result = {'schema':'discovery-store-v1'}
    elif args.command == 'proposals':
        result = store.proposals()
    elif args.command == 'inspect':
        result = store.inspect(args.id)
    else:
        if not args.config:
            parser.error('discover requires --config')
        config = decode(Path(args.config).read_bytes())
        result = {'proposals':Discovery(config, store).discover()}
    # JSON escapes terminal control sequences in untrusted evidence.
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
