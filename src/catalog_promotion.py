"""Manual, terminal-authorized discovery promotion. Never executes or publishes tasks."""
import argparse
import contextlib
import copy
import fcntl
import hashlib
import functools
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
import uuid

from src.discovery_analysis import digest, validate_proposal, DeterministicAnalyzer, proposal, WEIGHTS
from src.discovery_collection import decode, canonical, issue_snapshot, timestamp, PublicGitHub
from src.issue_discovery import Store
from src.local_catalog import resolve, REPOSITORIES

PROTOCOL = 'catalog-promotion-v1'
TTL = 300
HIGH = re.compile(r'\b(security|auth(?:entication|orization)?|password|credential|database|sql|migration|financial|payment|billing|deploy(?:ment)?)\b', re.I)
PROTECTED = re.compile(r'(approval|policy|publish|controller|promotion|discovery|local_runner|codex_adapter)', re.I)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    """Require a private operator-owned file and protected parent chain; no links."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        s = item.lstat()
        require(not stat.S_ISLNK(s.st_mode), 'Symlink destination rejected')
        if item == path:
            require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_nlink == 1,
                    'Operator-owned regular file required')
            require(not s.st_mode & 0o077, 'Private file permissions required')
        else:
            # /tmp is allowed only as a sticky ancestor, never as the immediate parent.
            require(not s.st_mode & 0o022 or (item != path.parent and s.st_mode & stat.S_ISVTX),
                    'Protected parent directory required')
            require(s.st_uid in (Path('/').stat().st_uid, os.getuid()), 'Untrusted parent owner')
    return path


def read_policy(path):
    path = regular(path)
    raw = path.read_bytes()
    require(len(raw) <= 4*1024*1024, 'Policy too large')
    policy = decode(raw)
    require(isinstance(policy, dict), 'Invalid policy')
    require(policy.get('mode') == 'local_codex_development' and type(policy.get('enabled')) is bool and
            policy.get('trusted_local_tasks_only') is True and
            type(policy.get('timeout_seconds')) is int and 0 < policy['timeout_seconds'] <= 2400,
            'Unsupported controller policy')
    require(isinstance(policy.get('repositories'), dict) and bool(policy['repositories']), 'Missing repositories')
    for repo, spec in policy['repositories'].items():
        require(repo in REPOSITORIES and spec.get('identity') == REPOSITORIES[repo], 'Repository policy mismatch')
    for key in ('state', 'scratch', 'operator_home'):
        require(isinstance(policy.get(key), str) and Path(policy[key]).is_absolute(), 'Invalid controller path')
    require(policy.get('scratch_reviewed_no_secrets') is True, 'Scratch review required')
    scratch, state = Path(policy['scratch']).resolve(), Path(policy['state']).resolve()
    controller = Path(__file__).resolve().parents[1]
    sources = []
    for spec in policy['repositories'].values():
        require(isinstance(spec.get('source'), str) and Path(spec['source']).is_absolute() and
                isinstance(spec.get('sha'), str) and re.fullmatch('[0-9a-f]{40}', spec['sha']) and
                isinstance(spec.get('branch'), str) and bool(spec['branch']), 'Invalid repository source policy')
        sources.append(Path(spec['source']).resolve())
    for root in [controller, *sources]:
        require(not scratch.is_relative_to(root) and not root.is_relative_to(scratch) and
                not state.is_relative_to(root) and not path.is_relative_to(root), 'Controller/source path overlap')
    require(not state.is_relative_to(scratch) and not path.is_relative_to(scratch), 'Worker state overlap')
    catalog = policy.get('catalog')
    require(isinstance(catalog, dict) and set(catalog) == {'schema', 'tasks'} and
            type(catalog['schema']) is int and catalog['schema'] == 1 and isinstance(catalog['tasks'], dict),
            'Unsupported catalog')
    for task in catalog['tasks']:
        resolve(policy, task)
    return policy, hashlib.sha256(raw).hexdigest()


def guard(policy, stops):
    require(isinstance(stops, list) and bool(stops) and all(isinstance(s, str) and
            Path(s).is_absolute() and Path(s).name == 'STOP' for s in stops), 'Explicit STOP paths required')
    require(not any(Path(s).exists() or Path(s).is_symlink() for s in [*stops, str(Path(policy['state'])/'STOP')]),
            'STOP active')


def intake(store, identity, network=False, transport=None):
    require(isinstance(identity, str) and re.fullmatch('[0-9a-f]{64}', identity), 'Invalid proposal ID')
    record = store.inspect(identity)
    p, s = validate_proposal(record['proposal']), record['snapshot']
    require(set(s) == {'repository', 'number', 'availability', 'issue', 'comments', 'source_commit'} and
            s['availability'] == 'present' and s['repository'] == p['repository'] and
            s['number'] == p['issue_number'] and s['source_commit'] == p['source_commit'] and
            digest(s) == p['snapshot'], 'Snapshot provenance mismatch')
    issue = s['issue']
    raw = dict(issue, comments=issue['comment_count'], labels=[{'name':l} for l in issue['labels']])
    require(issue_snapshot(p['repository'], raw, p['issue_number']) == issue and issue['state'] == 'open',
            'Invalid original issue')
    require(isinstance(s['comments'], list) and len(s['comments']) == issue['comment_count'], 'Missing comments')
    ids = set()
    for c in s['comments']:
        require(set(c) == {'id', 'body', 'created_at', 'updated_at', 'html_url'} and type(c['id']) is int and
                c['id'] > 0 and c['id'] not in ids and isinstance(c['body'], str) and len(c['body'].encode()) <= 65536 and
                timestamp(c['created_at']) <= timestamp(c['updated_at']) and
                c['html_url'] == issue['html_url']+'#issuecomment-'+str(c['id']), 'Invalid comment evidence')
        ids.add(c['id'])
    require(p['evidence'] == [p['snapshot']+'#issue']+[p['snapshot']+'#comment-'+str(c['id']) for c in s['comments']],
            'Evidence references changed')
    require(DeterministicAnalyzer().analyze(s) == dict(category=p['category'], signals=p['priority_rationale']['signals']),
            'Analysis provenance mismatch')
    weights = {}
    for key in WEIGHTS:
        signal, weighted = p['priority_rationale']['signals'][key], p['priority_rationale']['weighted'][key]
        require((signal or weighted == 0) and -100 <= weighted <= 100, 'Invalid analysis weights')
        weights[key] = weighted if signal else WEIGHTS[key]
    expected = proposal(s, p['snapshot'], p['discovered_at'], {'weights':weights}, DeterministicAnalyzer())
    expected.update(id=p['id'], policy_digest=p['policy_digest'])
    require(expected == p, 'Modified proposal analysis')
    events = record['events']
    require([e['kind'] for e in events] == ['discovered', 'proposed'] and
            events[0]['subject'] == p['snapshot'] and events[1]['subject'] == identity and
            events[1]['at'] == p['discovered_at'] and events[0]['at'] <= events[1]['at'], 'Missing discovery audit')
    for e in events:
        timestamp(e['at'])
    require(bool(record['observations']) and all(o['availability'] == 'present' and o['state'] == 'open'
            for o in record['observations']), 'Closed or unavailable historical issue observation')
    if network:
        current = issue_snapshot(p['repository'], (transport or PublicGitHub()).get(
            p['repository'], 'issues/'+str(p['issue_number'])), p['issue_number'])
        require(current == issue and current['state'] == 'open', 'Issue changed since discovery')
    return record


def reviewed(policy, task_id, entry, risk, record):
    require(risk in ('low', 'medium', 'high'), 'Explicit risk selection required')
    p, s = record['proposal'], record['snapshot']
    require(isinstance(entry, dict), 'Independent complete task specification required')
    require(entry.get('repository') == p['repository'] and entry.get('source') == p['source_commit'] and
            entry.get('issue') == p['issue_number'] and entry.get('issue_snapshot') == s['issue'],
            'Reviewed provenance/source mismatch; rediscover changed sources')
    instructions = entry.get('instructions')
    require(isinstance(instructions, str) and 1 <= len(instructions.strip()) <= 8192 and
            all(ord(c) >= 32 or c in '\n\t' for c in instructions), 'Invalid reviewed instructions')
    require(isinstance(entry.get('allowed'), list) and all(isinstance(p, str) and not PROTECTED.search(p)
            for p in entry['allowed']), 'Protected controller paths')
    signal = ' '.join([instructions, *entry['allowed'], s['issue']['title'], s['issue']['body'],
                       *s['issue']['labels'], *[c['body'] for c in s['comments']]])
    require(risk != 'high' and p['risk'] != 'high' and not HIGH.search(re.sub(r'[_-]', ' ', signal)),
            'High-risk proposal requires explicit manual escalation outside promotion')
    require(not re.search(r'\b(approve|publish|push|merge|credentials?|secrets?|controller|policy|approval)\b',
                          instructions, re.I), 'Instructions request forbidden authority')
    result = copy.deepcopy(policy)
    require(task_id not in result['catalog']['tasks'], 'Task ID collision')
    result['catalog']['tasks'][task_id] = copy.deepcopy(entry)
    for name in result['catalog']['tasks']:
        resolve(result, name)
    return result


class Ledger:
    """Separate append-only ledger; approvals are domain-specific and never runner grants."""
    def __init__(self, path):
        self.path = Path(path).absolute()

    def initialize(self):
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        regular(self.path)
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE metadata(schema TEXT NOT NULL);
                INSERT INTO metadata VALUES ('catalog-promotion-v1');
                CREATE TABLE events(seq INTEGER PRIMARY KEY, id TEXT NOT NULL, kind TEXT NOT NULL,
                                    at REAL NOT NULL, document TEXT NOT NULL);''')
            for table in ('metadata', 'events'):
                for op in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable promotion ledger'); END")

    @contextlib.contextmanager
    def tx(self):
        regular(self.path)
        with sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('SELECT schema FROM metadata').fetchall() == [(PROTOCOL,)], 'Unknown promotion ledger')
            yield db

    def add(self, db, identity, kind, at, document):
        db.execute('INSERT INTO events(id,kind,at,document) VALUES(?,?,?,?)',
                   (identity, kind, at, canonical(document)))

    def get(self, db, identity, history=False):
        rows = db.execute('SELECT kind,at,document FROM events WHERE id=? ORDER BY seq', (identity,)).fetchall()
        if not history:
            rows = [row for row in rows if row[0] != 'rejected']
        require(bool(rows), 'Unknown promotion')
        return [(k, t, decode(d.encode())) for k,t,d in rows]

    def attempts(self):
        with self.tx() as db:
            return [dict(id=i, state=k, at=t) for i,k,t in db.execute('SELECT id,kind,at FROM events ORDER BY seq')]

    def inspect(self, identity):
        with self.tx() as db:
            return self.get(db, identity, history=True)


def terminal(challenge, document):
    # No answer CLI option, environment authorization, callback, stdin or automatic renewal.
    with open('/dev/tty', 'r') as inp, open('/dev/tty', 'w') as out:
        require(inp.isatty() and out.isatty(), 'Controlling terminal required')
        out.write(json.dumps(document, indent=2, ensure_ascii=True, allow_nan=False)+'\nType '+challenge+'\n')
        out.flush()
        require(inp.readline().rstrip('\r\n') == challenge, 'Promotion authorization refused')


def audited(method):
    @functools.wraps(method)
    def action(self, identity, *args, **kwargs):
        try:
            return method(self, identity, *args, **kwargs)
        except BaseException as error:
            # Rejections append evidence without changing the grant state. A failed
            # filesystem intent is already terminal and cannot be retried.
            subject = 'rejected-'+uuid.uuid4().hex if method.__name__ == 'prepare' else identity
            with self.ledger.tx() as db:
                latest = db.execute('SELECT kind FROM events WHERE id=? ORDER BY seq DESC LIMIT 1', (subject,)).fetchone()
                if not latest or latest[0] not in ('export-failed', 'import-uncertain'):
                    self.ledger.add(db, subject, 'rejected', self.clock(),
                                    dict(operation=method.__name__, subject=identity, error=type(error).__name__))
            raise
    return action


class Promotion:
    def __init__(self, ledger, discovery, policy, stops, clock=time.time):
        self.ledger, self.store, self.path = ledger, discovery, Path(policy).absolute()
        self.stops, self.clock = list(stops), clock
        policy, _ = read_policy(self.path)
        for root in [Path(policy['scratch']).resolve(), *[Path(r['source']).resolve() for r in policy['repositories'].values()]]:
            require(not ledger.path.resolve().is_relative_to(root) and not discovery.path.is_relative_to(root),
                    'Promotion/discovery state must be outside worker sources')
        require(len({ledger.path.resolve(), discovery.path, self.path.resolve()}) == 3,
                'Separate promotion, discovery and policy files required')

    @audited
    def prepare(self, proposal_id, task_id, entry, risk, network=False):
        policy, revision = read_policy(self.path)
        guard(policy, self.stops)
        record = intake(self.store, proposal_id, network)
        result = reviewed(policy, task_id, entry, risk, record)
        identity = uuid.uuid4().hex
        doc = dict(protocol=PROTOCOL, id=identity, proposal=record, proposal_digest=digest(record),
                   task_id=task_id, entry=copy.deepcopy(entry), risk=risk, destination=str(self.path),
                   revision=revision, policy_digest=digest(policy), resulting_policy_digest=digest(result),
                   stop_files=self.stops, issue_check='network' if network else 'offline-historical-only',
                   prepared_at=self.clock())
        doc['binding'] = digest(doc)
        with self.ledger.tx() as db:
            guard(policy, self.stops)
            self.ledger.add(db, identity, 'prepared', self.clock(), doc)
        return doc

    def validate(self, doc):
        bound = dict(doc); binding = bound.pop('binding')
        require(digest(bound) == binding and doc['protocol'] == PROTOCOL and doc['destination'] == str(self.path)
                and doc['stop_files'] == self.stops, 'Promotion binding changed')
        policy, revision = read_policy(self.path)
        guard(policy, self.stops)
        require(revision == doc['revision'] and digest(policy) == doc['policy_digest'], 'Catalog write conflict')
        record = intake(self.store, doc['proposal']['proposal']['id'], doc['issue_check'] == 'network')
        require(digest(record) == doc['proposal_digest'] and record == doc['proposal'], 'Discovery evidence changed')
        result = reviewed(policy, doc['task_id'], doc['entry'], doc['risk'], record)
        require(digest(result) == doc['resulting_policy_digest'], 'Resulting policy changed')
        return policy, result

    @audited
    def approve(self, identity):
        with self.ledger.tx() as db:
            rows = self.ledger.get(db, identity)
            require(rows[0][0] == 'prepared', 'Unknown promotion preparation')
            doc = rows[0][2]
            require(rows[-1][0] == 'prepared', 'Approval already used or attempted')
            self.validate(doc)
            require(0 <= self.clock()-doc['prepared_at'] < TTL, 'Preparation expired; create a new attempt')
            terminal('PROMOTE '+doc['binding'], doc)
            self.validate(doc)
            require(0 <= self.clock()-doc['prepared_at'] < TTL, 'Preparation expired')
            self.ledger.add(db, identity, 'approved', self.clock(), dict(binding=doc['binding'], expires=self.clock()+TTL))
        return self.ledger.inspect(identity)

    @audited
    def apply(self, identity, export):
        """Consume approval and export exclusively; never mutate controller policy."""
        export = Path(export).absolute()
        with self.ledger.tx() as db:
            rows = self.ledger.get(db, identity)
            require(rows[0][0] == 'prepared', 'Unknown promotion preparation')
            doc = rows[0][2]
            require(rows[-1][0] == 'approved', 'Single-use promotion approval required')
            require(rows[-1][2]['binding'] == doc['binding'] and rows[-1][1] <= self.clock() < rows[-1][2]['expires'],
                    'Approval expired or changed')
            policy, result = self.validate(doc)
            bundle = dict(schema='promotion-export-v1', promotion=doc, policy=result,
                          approved_at=rows[-1][1], expires=rows[-1][2]['expires'])
            self.ledger.add(db, identity, 'export-intent', self.clock(), dict(path=str(export), digest=digest(bundle)))
        # Intent commits before filesystem changes. Interrupted/failed export cannot replay approval.
        try:
            require(export != self.path and export != self.ledger.path and export != self.store.path, 'Evidence path collision')
            guard(policy, self.stops)
            atomic_new(export, (canonical(bundle)+'\n').encode())
        except BaseException as error:
            with self.ledger.tx() as db:
                self.ledger.add(db, identity, 'export-failed', self.clock(), dict(error=type(error).__name__))
            raise
        with self.ledger.tx() as db:
            self.ledger.add(db, identity, 'exported', self.clock(), dict(path=str(export), digest=digest(bundle)))
        return bundle


def atomic_new(path, payload):
    """Publish a complete new file without overwriting any existing path."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.promotion-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(payload); out.flush(); os.fsync(out.fileno())
        regular(tmp)
        os.link(tmp, path)  # atomic no-clobber publication
        fsync_dir(path.parent)
    finally:
        os.unlink(tmp)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def audit_import(operation):
    @functools.wraps(operation)
    def action(export, destination, ledger, stops, clock=time.time):
        try:
            return operation(export, destination, ledger, stops, clock)
        except BaseException as error:
            with ledger.tx() as db:
                ledger.add(db, 'import-rejection-'+uuid.uuid4().hex, 'rejected', clock(),
                           dict(operation='import', destination=str(destination), error=type(error).__name__))
            raise
    return action


@audit_import
def import_export(export, destination, ledger, stops, clock=time.time):
    """Separate manual controller import. No discovery database access or automatic trust in export."""
    destination = regular(destination)
    bundle = decode(regular(export).read_bytes())
    require(set(bundle) == {'schema', 'promotion', 'policy', 'approved_at', 'expires'} and
            bundle['schema'] == 'promotion-export-v1', 'Unknown export format')
    doc = bundle['promotion']; bound = dict(doc); binding = bound.pop('binding')
    require(doc['protocol'] == PROTOCOL and digest(bound) == binding and
            doc['destination'] == str(destination), 'Export binding mismatch')
    # Lock is shared by every import for this destination, across promotion ledgers.
    lock = destination.with_name(destination.name+'.promotion-lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        regular(lock)
        with os.fdopen(fd, 'r+') as locked:
            fd = None
            fcntl.flock(locked, fcntl.LOCK_EX)
            with ledger.tx() as db:
                rows = ledger.get(db, doc['id'])
                require(rows[0][2] == doc and rows[-1][0] == 'exported' and
                        rows[-1][2]['digest'] == digest(bundle), 'Export not authorized or already consumed')
                require(bundle['approved_at'] <= clock() < bundle['expires'], 'Import approval expired')
                policy, revision = read_policy(destination)
                guard(policy, stops)
                require(stops == doc['stop_files'] and revision == doc['revision'] and
                        digest(policy) == doc['policy_digest'], 'Catalog write conflict')
                result = reviewed(policy, doc['task_id'], doc['entry'], doc['risk'], doc['proposal'])
                require(result == bundle['policy'] and digest(result) == doc['resulting_policy_digest'], 'Export policy changed')
                terminal('IMPORT '+digest(bundle), bundle)
                guard(policy, stops)
                require(clock() < bundle['expires'] and read_policy(destination)[1] == revision, 'Import expired or conflicted')
                ledger.add(db, doc['id'], 'import-intent', clock(), dict(before=revision, after=digest(result)))
            tmp = None
            try:
                handle, tmp = tempfile.mkstemp(prefix='.catalog-', dir=destination.parent)
                with os.fdopen(handle, 'wb') as out:
                    out.write((canonical(result)+'\n').encode()); out.flush(); os.fsync(out.fileno())
                read_policy(tmp)
                guard(policy, stops)
                require(read_policy(destination)[1] == revision, 'Concurrent policy edit')
                os.replace(tmp, destination); tmp = None
                fsync_dir(destination.parent)
            except BaseException as error:
                with ledger.tx() as db:
                    ledger.add(db, doc['id'], 'import-uncertain', clock(), dict(error=type(error).__name__,
                        recovery='Inspect destination digest and intent; never replay. Prepare a new attempt only after reconciliation.'))
                raise
            finally:
                if tmp:
                    os.unlink(tmp)
            with ledger.tx() as db:
                ledger.add(db, doc['id'], 'imported', clock(), dict(task_id=doc['task_id'], policy_digest=digest(result)))
            return dict(task_id=doc['task_id'], policy_digest=digest(result))
    finally:
        if fd is not None:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--policy')
    parser.add_argument('--discovery')
    parser.add_argument('--stop', action='append', default=[])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('attempts')
    p = sub.add_parser('prepare'); p.add_argument('id'); p.add_argument('--task-id', required=True)
    p.add_argument('--reviewed-entry', required=True); p.add_argument('--risk', choices=['low','medium','high'], required=True)
    p.add_argument('--network', action='store_true')
    for name in ('inspect', 'approve'):
        sub.add_parser(name).add_argument('id')
    p = sub.add_parser('apply'); p.add_argument('id'); p.add_argument('--export', required=True)
    p = sub.add_parser('import'); p.add_argument('--export', required=True)
    args = parser.parse_args(); ledger = Ledger(args.ledger)
    if args.command == 'init':
        ledger.initialize(); result = {'schema':PROTOCOL}
    elif args.command == 'attempts':
        result = ledger.attempts()
    elif args.command == 'inspect':
        result = ledger.inspect(args.id)
    elif args.command == 'import':
        require(args.policy is not None, 'Explicit destination required')
        result = import_export(args.export, args.policy, ledger, args.stop)
    else:
        require(args.policy is not None and args.discovery is not None, 'Explicit policy and discovery evidence required')
        promotion = Promotion(ledger, Store(args.discovery), args.policy, args.stop)
        if args.command == 'prepare':
            result = promotion.prepare(args.id, args.task_id, decode(regular(args.reviewed_entry).read_bytes()), args.risk, args.network)
        elif args.command == 'approve': result = promotion.approve(args.id)
        else: result = promotion.apply(args.id, args.export)
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
