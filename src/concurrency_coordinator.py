"""Concurrency readiness v1. No live worker, approval or publication dispatch.

The ledger and this module belong to the trusted controller. Directory separation
is a data-integrity contract, not a security sandbox. Only the fixed in-process
synthetic worker below is executable through this module.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from src import orchestration_evidence as e
from src.local_catalog import resolve
from src.source_observation import manifest, source_files, git

PROTOCOL = 'concurrency-coordinator-v1'
OBSERVATIONS = 'concurrency-observations-v1'
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}
ACTIVE = {'claimed', 'running', 'qa', 'held'}
TOKENS = ('input_tokens', 'cached_input_tokens', 'output_tokens')
FIELDS = {'schema', 'enabled', 'slots', 'live_limit', 'mode', 'ledger', 'scratch',
          'stop_files', 'max_tasks', 'max_artifact_bytes', 'max_storage_bytes'}


def validate(c):
    e.require(isinstance(c, dict) and set(c) == FIELDS and c['schema'] == PROTOCOL,
              'Unknown coordinator configuration')
    e.require(type(c['enabled']) is bool and c['mode'] == 'synthetic-only' and
              type(c['slots']) is int and 1 <= c['slots'] <= 3 and
              type(c['live_limit']) is int and c['live_limit'] == 1,
              'Live concurrency cannot be increased through configuration')
    for key, lower, upper in [('max_tasks', 1, 10000), ('max_artifact_bytes', 1024, 16*1024*1024),
                              ('max_storage_bytes', 1024*1024, 1024**3)]:
        e.require(type(c[key]) is int and lower <= c[key] <= upper, 'Invalid resource ceiling')
    e.require(c['max_artifact_bytes'] < c['max_storage_bytes'], 'Invalid aggregate ceiling')
    for k in ('ledger', 'scratch'):
        e.require(isinstance(c[k], str) and Path(c[k]).is_absolute(), 'Absolute coordinator paths required')
    stops = c['stop_files']
    e.require(isinstance(stops, list) and bool(stops) and len(set(stops)) == len(stops) and
              all(isinstance(p, str) and Path(p).is_absolute() and Path(p).name == 'STOP' for p in stops),
              'Explicit STOP paths required')
    scratch = Path(c['scratch']).resolve()
    protected = [Path(c['ledger']).resolve(), Path(__file__).resolve().parents[1],
                 *[Path(p).resolve() for p in stops]]
    e.require(all(not scratch.is_relative_to(p) and not p.is_relative_to(scratch) for p in protected),
              'Scratch overlaps protected storage')
    return c


def configuration(path):
    return validate(e.decode(e.regular(path).read_bytes()))


def stopped(c):
    return any(os.path.lexists(p) for p in c['stop_files'])


def authorization(policy_path, execution, task, now, c):
    """Fresh read-only verification of an existing controlling-terminal grant."""
    policy_path = e.regular(policy_path)
    policy, _, specs = e.catalog(policy_path)
    state = Path(policy['state']).absolute()
    e.require(str(state/'STOP') in c['stop_files'] and not stopped(c), 'STOP active or omitted')
    protected = [policy_path, state, Path(policy['operator_home']),
                 *[Path(r['source']) for r in policy['repositories'].values()]]
    scratch, ledger = Path(c['scratch']).resolve(), Path(c['ledger']).resolve()
    for p in protected:
        p = p.resolve()
        e.require(not p.is_relative_to(scratch) and not scratch.is_relative_to(p) and
                  not ledger.is_relative_to(p) and not p.is_relative_to(ledger), 'Protected store overlap')
    runs, _ = e.executions(state/'local.sqlite')
    e.require(execution in runs and task in specs, 'Missing independently approved task')
    r, spec = runs[execution], specs[task]
    status, _ = e.run_state(r, spec, policy, now)
    e.require(status == 'approved-for-coding' and policy['enabled'] is True,
              'Current task-bound controller approval required')
    e.require(not any(x['state'] == 'running' for x in runs.values()), 'Existing controller worker hold')
    repo = policy['repositories'][spec['repo']]
    e.require(git(repo['source'], 'rev-parse', 'HEAD').decode().strip() == spec['source'],
              'Stale source revision; no automatic rebase')
    bound = dict(task=task, execution=execution, policy_path=str(policy_path),
                 policy_digest=e.digest(policy), catalog_digest=e.digest(policy['catalog']),
                 spec=spec, authorization_digest=e.digest(r), repository=spec['task']['repository'],
                 source=spec['source'], source_manifest=spec['input_hash'], allowed=spec['allowed'],
                 checks=spec['checks'], expires=r['expires'])
    return bound


class Coordinator:
    def __init__(self, config, clock=time.time):
        self.c = validate(json.loads(json.dumps(config)))
        self.path = Path(self.c['ledger']).absolute()
        self.clock = clock

    def initialize(self):
        e.require(not self.path.exists(), 'Never replace an existing ledger')
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        e.regular(self.path)
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE metadata(schema TEXT, config TEXT);
                CREATE TABLE tasks(id TEXT PRIMARY KEY, execution TEXT UNIQUE NOT NULL, document TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY, task TEXT NOT NULL REFERENCES tasks(id),
                    at REAL NOT NULL, kind TEXT NOT NULL, document TEXT NOT NULL);''')
            db.execute('INSERT INTO metadata VALUES (?,?)', (PROTOCOL, e.digest(self.c)))
            for table in ('metadata', 'tasks', 'events'):
                for op in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable coordinator evidence'); END")
        self._sync_parent()

    def _sync_parent(self):
        fd = os.open(self.path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    @contextlib.contextmanager
    def tx(self, write=False):
        e.regular(self.path)
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            if write:
                pages = max(1, self.c['max_storage_bytes']//db.execute('PRAGMA page_size').fetchone()[0])
                db.execute(f'PRAGMA max_page_count={pages}')
            else: db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            e.require([tuple(r) for r in db.execute('SELECT * FROM metadata')] == [(PROTOCOL, e.digest(self.c))],
                      'Unknown ledger or configuration revision; operator review required')
            e.require({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} ==
                      {'metadata', 'tasks', 'events'}, 'Unknown coordinator schema')
            e.require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Ledger integrity failure')
            yield db
            if write: db.commit()
        finally: db.close()

    def _event(self, db, task, kind, doc):
        now = self.clock()
        last = db.execute('SELECT MAX(at) FROM events').fetchone()[0]
        e.require(e.finite(now) and (last is None or now >= last), 'Coordinator clock regression')
        raw = e.canonical(doc)
        e.require(len(raw.encode()) <= self.c['max_artifact_bytes'], 'Evidence size ceiling')
        db.execute('INSERT INTO events(task,at,kind,document) VALUES (?,?,?,?)', (task, now, kind, raw))

    def _rows(self, db):
        rows = {}
        for r in db.execute('SELECT * FROM tasks ORDER BY id'):
            a = e.decode(r['document'])
            e.require(a['task'] == r['id'] and a['execution'] == r['execution'], 'Task identity mismatch')
            rows[r['id']] = dict(authorization=a, state=None, claim=None, events=[], usage=None)
        for event in db.execute('SELECT * FROM events ORDER BY seq'):
            e.require(event['task'] in rows, 'Orphan event')
            row = rows[event['task']]; kind = event['kind']; d = e.decode(event['document'])
            state = row['state']
            transitions = {'queued': {None}, 'claimed': {'queued'}, 'running': {'claimed'},
                           'qa': {'running'}, 'completed': {'qa'}, 'failed': {'running', 'qa'},
                           'held': {'claimed', 'running', 'qa', 'held'},
                           'cancelled': {'queued'}, 'interrupted': {'held'}}
            e.require(kind in transitions and state in transitions[kind], 'Contradictory coordinator history')
            if kind == 'claimed':
                e.require(d['task'] == event['task'] and d['execution'] == row['authorization']['execution'] and
                          d['authorization'] == e.digest(row['authorization']) and
                          d['slot'] in self.slots and e.sha(d['token'], 32) and
                          d['started'] == event['at'] and e.finite(d['deadline']) and
                          d['started'] < d['deadline'] <= d['started']+row['authorization']['spec']['limits']['timeout_seconds'],
                          'Invalid claim binding')
                row['claim'] = d
            elif kind not in ('queued', 'cancelled'):
                e.require(row['claim'] is not None and d['token'] == row['claim']['token'], 'Fencing mismatch')
            row['state'] = kind
            row['events'].append(dict(seq=event['seq'], at=event['at'], kind=kind, document=d))
            if 'usage' in d: row['usage'] = d['usage']
        active = [r['claim'] for r in rows.values() if r['state'] in ACTIVE]
        e.require(len({a['slot'] for a in active}) == len(active) and
                  len({rows[a['task']]['authorization']['repository'] for a in active}) == len(active),
                  'Conflicting slot/repository ownership')
        e.require(all(r['state'] is not None for r in rows.values()), 'Missing queue event')
        return rows

    @property
    def slots(self):
        return ['slot-'+str(i+1) for i in range(self.c['slots'])]

    def enqueue(self, policy, execution, task):
        e.require(self.c['enabled'] and not stopped(self.c), 'Disabled or STOP active')
        with self.tx(True) as db:
            a = authorization(policy, execution, task, self.clock(), self.c)
            rows = self._rows(db)
            e.require(task not in rows and len(rows) < self.c['max_tasks'], 'Task duplicate or capacity exhausted')
            db.execute('INSERT INTO tasks VALUES (?,?,?)', (task, execution, e.canonical(a)))
            self._event(db, task, 'queued', {'authorization': e.digest(a)})
        return a

    def claim(self, task, slot, worker):
        e.require(self.c['enabled'] and not stopped(self.c), 'Disabled or STOP active')
        e.require(slot in self.slots and isinstance(worker, str) and 0 < len(worker) <= 64, 'Invalid slot/worker')
        with self.tx(True) as db:
            rows = self._rows(db)
            e.require(task in rows and rows[task]['state'] == 'queued', 'Task already claimed or missing')
            a = rows[task]['authorization']
            current = authorization(a['policy_path'], a['execution'], task, self.clock(), self.c)
            e.require(current == a, 'Approval or source changed while queued')
            for r in rows.values():
                if r['state'] in ACTIVE:
                    e.require(r['claim']['slot'] != slot and r['authorization']['repository'] != a['repository'],
                              'Slot/repository occupied; task remains queued')
            now = self.clock()
            d = dict(task=task, execution=a['execution'], authorization=e.digest(a), slot=slot, worker=worker,
                     token=uuid.uuid4().hex, generation=db.execute('SELECT COUNT(*) FROM events').fetchone()[0]+1,
                     started=now, deadline=now+a['spec']['limits']['timeout_seconds'],
                     cancellation=False, stop=False, mode='synthetic-only')
            e.require(not stopped(self.c), 'STOP before claim commit')
            self._event(db, task, 'claimed', d)
        return d

    def _owned(self, db, claim, states):
        rows = self._rows(db)
        e.require(claim.get('task') in rows, 'Unknown claim')
        row = rows[claim['task']]
        e.require(row['claim'] == claim and row['state'] in states, 'Stale fencing token or state')
        return row

    def guard(self, claim):
        with self.tx() as db:
            self._owned(db, claim, {'claimed', 'running', 'qa'})
        e.require(not stopped(self.c) and self.clock() < claim['deadline'], 'STOP/deadline requires cancellation')

    def hold(self, claim, reason, *, cancellation=False, usage=None):
        e.require(isinstance(reason, str) and 0 < len(reason) <= 512, 'Recovery reason required')
        with self.tx(True) as db:
            self._owned(db, claim, ACTIVE)
            self._event(db, claim['task'], 'held', dict(token=claim['token'], reason=reason,
                        cancellation=cancellation, stop=stopped(self.c), termination='unconfirmed', usage=usage))

    def sweep(self):
        """Record STOP/deadline intent. No process death is inferred from elapsed time."""
        with self.tx(True) as db:
            for task, row in self._rows(db).items():
                if row['state'] in {'claimed', 'running', 'qa'} and (stopped(self.c) or self.clock() >= row['claim']['deadline']):
                    self._event(db, task, 'held', dict(token=row['claim']['token'], reason='STOP or deadline',
                                cancellation=True, stop=stopped(self.c), termination='unconfirmed'))

    def cancel(self, task, reason):
        e.require(isinstance(reason, str) and 0 < len(reason) <= 512, 'Cancellation reason required')
        with self.tx(True) as db:
            rows = self._rows(db); e.require(task in rows, 'Unknown task'); row = rows[task]
            if row['state'] == 'queued': self._event(db, task, 'cancelled', dict(reason=reason))
            else:
                self._owned(db, row['claim'], ACTIVE)
                self._event(db, task, 'held', dict(token=row['claim']['token'], reason=reason,
                            cancellation=True, stop=stopped(self.c), termination='unconfirmed'))

    def recover(self, claim, reason, response):
        """Explicit terminal-reviewed recovery; consumes identity forever, never requeues."""
        e.require(isinstance(reason, str) and 0 < len(reason) <= 512 and
                  response == 'RECONCILE '+e.digest(claim), 'Exact operator reconciliation required')
        with self.tx(True) as db:
            self._owned(db, claim, {'held'})
            self._event(db, claim['task'], 'interrupted', dict(token=claim['token'], reason=reason,
                        operator_confirmed_termination=True, replay_permitted=False))

    def inspect(self):
        with self.tx() as db: rows = self._rows(db)
        totals = {k: 0 for k in (*TOKENS, 'execution_seconds', 'qa_seconds', 'artifact_bytes')}
        for row in rows.values():
            if row['usage']:
                for k in totals:
                    if row['usage'].get(k) is not None: totals[k] += row['usage'][k]
            metric_names = [*TOKENS, 'execution_seconds', 'qa_seconds', 'artifact_bytes', 'exit_status', 'peak_memory_bytes', 'cpu_seconds']
            row['unavailable_metrics'] = [k for k in metric_names if not row['usage'] or row['usage'].get(k) is None]
            row['required_action'] = ('Inspect processes, STOP and partial evidence; confirm termination; terminal reconcile'
                                      if row['state'] in ACTIVE else 'No automatic dispatch or retry')
        return dict(schema=OBSERVATIONS, configured_slots=self.slots, live_limit=1, executable_live=False,
                    stop=stopped(self.c), tasks=rows, aggregate=totals,
                    unsupported=['hard_cpu', 'hard_memory', 'hard_disk', 'hard_network', 'subscription_dollar_cap'],
                    metric_availability={'peak_memory_bytes': 'unavailable', 'cpu_seconds': 'unavailable'})

    def run_synthetic(self, claim, worker):
        """Fixed inert adapter only. Never imports or calls LocalCLI/CodexAdapter."""
        e.require(type(worker) is SyntheticWorker, 'Only fixed synthetic workers supported; external sandbox required for live execution')
        from src.local_runner import materialize, snapshot
        self.guard(claim)
        with self.tx(True) as db:
            row = self._owned(db, claim, {'claimed'})
            a = row['authorization']
            e.require(authorization(a['policy_path'], a['execution'], a['task'], self.clock(), self.c) == a,
                      'Authorization changed before synthetic startup')
            self._event(db, claim['task'], 'running', {'token': claim['token']})
        start = time.monotonic()
        metrics = {k: None for k in (*TOKENS, 'execution_seconds', 'qa_seconds', 'artifact_bytes', 'exit_status', 'peak_memory_bytes', 'cpu_seconds')}
        qa_start = None
        try:
            root = Path(self.c['scratch'])
            root.mkdir(mode=0o700, exist_ok=True)
            e.require(not root.is_symlink() and not root.stat().st_mode & 0o077, 'Private scratch required')
            with tempfile.TemporaryDirectory(prefix=claim['token']+'-', dir=root) as work:
                checkout = Path(work)/'checkout'; checkout.mkdir(mode=0o700)
                policy, _, specs = e.catalog(a['policy_path'])
                spec = specs[a['task']]
                source = policy['repositories'][spec['repo']]['source']
                files = source_files(source, spec['source'], spec['allowed'])
                e.require(manifest(files) == a['source_manifest'], 'Source manifest changed')
                materialize(files, checkout)
                self.guard(claim)
                result = worker.run(checkout, a)
                for key in (*TOKENS, 'exit_status'):
                    if type(result.get(key)) is int and (key == 'exit_status' or result[key] >= 0):
                        metrics[key] = result[key]
                self.guard(claim)
                candidate = snapshot(checkout)
                e.require(files.keys() == candidate.keys(), 'Missing or extra artifacts')
                changed = sorted(k for k in files if files[k] != candidate[k])
                e.require(bool(changed) and set(changed) <= set(a['allowed']), 'Outside approved allowlist')
                size = sum(len(v[1]) for v in candidate.values())
                metrics['artifact_bytes'] = size
                e.require(size <= self.c['max_artifact_bytes'], 'Artifact ceiling')
                e.require(result['exit_status'] == 0, 'Synthetic worker failed')
                usage = {k: result[k] for k in TOKENS}
                e.require(all(type(v) is int and v >= 0 for v in usage.values()) and
                          usage['cached_input_tokens'] <= usage['input_tokens'], 'Invalid usage')
                # Controller captures exact bytes, never worker-selected reports/checks.
                artifact = dict(source_manifest=manifest(files), candidate_manifest=manifest(candidate),
                    files={k: [candidate[k][0], candidate[k][1].hex()] for k in changed}, changed=changed,
                    workspace=work, checkout=str(checkout), token=claim['token'])
                with self.tx(True) as db:
                    self._owned(db, claim, {'running'})
                    self._event(db, claim['task'], 'qa', dict(token=claim['token'], artifact=artifact,
                                artifact_digest=e.digest(artifact)))
                qa_start = time.monotonic()
                qa = verify_candidate(a, artifact, policy, lambda: self.guard(claim),
                                      self.c['max_artifact_bytes'], claim['deadline']-self.clock())
                self.guard(claim)
                e.require(authorization(a['policy_path'], a['execution'], a['task'], self.clock(), self.c) == a,
                          'Authorization changed during synthetic work')
                usage.update(execution_seconds=qa_start-start, qa_seconds=time.monotonic()-qa_start,
                             artifact_bytes=size, exit_status=0, peak_memory_bytes=None, cpu_seconds=None)
                with self.tx(True) as db:
                    self._owned(db, claim, {'qa'})
                    e.require(not stopped(self.c) and self.clock() < claim['deadline'], 'STOP/deadline before commit')
                    self._event(db, claim['task'], 'completed', dict(token=claim['token'], qa=qa,
                                qa_digest=e.digest(qa), usage=usage))
        except (Exception, KeyboardInterrupt):
            # Fixed worker has no child processes. QA supervisor kills its process
            # group; any exception/termination uncertainty remains held conservatively.
            with self.tx() as db: row = self._owned(db, claim, ACTIVE)
            metrics['execution_seconds'] = (qa_start if qa_start is not None else time.monotonic())-start
            if qa_start is not None: metrics['qa_seconds'] = time.monotonic()-qa_start
            if row['state'] != 'held': self.hold(claim, 'Synthetic execution or QA incomplete; operator reconciliation required', usage=metrics)
            raise
        return self.inspect()['tasks'][claim['task']]


class SyntheticWorker:
    """No executable arguments, secrets, network, subprocesses or arbitrary callbacks."""
    def run(self, checkout, authorization):
        p = checkout/authorization['allowed'][0]
        p.write_bytes(p.read_bytes()+b'\n// synthetic coordination fixture\n')
        return dict(input_tokens=3, cached_input_tokens=1, output_tokens=4, exit_status=0)


def reconstruct_candidate(a, artifact, policy, maximum):
    """Controller-side reconstruction; never executes candidate code."""
    spec = a['spec']
    files = source_files(policy['repositories'][spec['repo']]['source'], a['source'], a['allowed'])
    e.require(manifest(files) == a['source_manifest'] == artifact['source_manifest'], 'Source manifest mismatch')
    candidate = dict(files)
    e.require(set(artifact['files']) == set(artifact['changed']) and bool(artifact['changed']) and
              set(artifact['changed']) <= set(a['allowed']), 'Unapproved evidence files')
    for name, (mode, data) in artifact['files'].items():
        e.require(type(mode) is int and mode in (0o644, 0o755) and isinstance(data, str) and
                  len(data) <= maximum*2, 'Unsafe candidate evidence')
        candidate[name] = (mode, bytes.fromhex(data))
    e.require(sum(len(v[1]) for v in candidate.values()) <= maximum and
              manifest(candidate) == artifact['candidate_manifest'], 'Candidate manifest mismatch')
    return files, candidate


def verify_candidate(a, artifact, policy, guard, maximum, remaining):
    """Independently run controller-selected checks on the reconstructed candidate."""
    from src.local_runner import Runner
    spec = a['spec']
    files, candidate = reconstruct_candidate(a, artifact, policy, maximum)
    guard()
    # Reuse exact fixed grammar, pinned Node, fresh reconstruction and mutation checks.
    runner = object.__new__(Runner)
    runner.policy = policy
    runner.scratch = Path(policy['scratch'])
    runner.scratch.mkdir(mode=0o700, exist_ok=True)
    report = runner.qa(files, candidate, lambda: _cancelled(guard), remaining, spec=spec)
    e.require(all(q['code'] == 0 and q['reason'] is None for q in report), 'Independent QA failure')
    guard()
    return dict(protocol=PROTOCOL, task=a['task'], execution=a['execution'], token=artifact['token'],
                authorization=e.digest(a), artifact=e.digest(artifact), source_manifest=manifest(files),
                candidate_manifest=manifest(candidate), checks=report, worker_reports_trusted=False)


def _cancelled(guard):
    try: guard(); return False
    except ValueError: return True


def observations(config):
    """Versioned read-only adapter; observations confer no execution authority."""
    c = Coordinator(config)
    view = c.inspect()
    for task, row in view['tasks'].items():
        if row['state'] == 'completed':
            qa_event = next(x['document'] for x in row['events'] if x['kind'] == 'qa')
            final = row['events'][-1]['document']; artifact = qa_event['artifact']; qa = final['qa']
            policy, _, specs = e.catalog(row['authorization']['policy_path'])
            e.require(specs[task] == row['authorization']['spec'] and
                      e.digest(policy) == row['authorization']['policy_digest'], 'Current reviewed policy differs from evidence')
            reconstruct_candidate(row['authorization'], artifact, policy, config['max_artifact_bytes'])
            commands = [['/usr/bin/git', 'diff', '--check', 'HEAD^', 'HEAD']] + [
                [policy['node'], *check['argv'][1:]] for check in row['authorization']['checks']]
            e.require([check['command'] for check in qa['checks'][:-1]] == commands and
                      qa['checks'][-1]['input_hash'] == qa['source_manifest'] and
                      qa['checks'][-1]['candidate_hash'] == qa['candidate_manifest'], 'QA reconstruction receipt mismatch')
            e.require(e.digest(artifact) == qa_event['artifact_digest'] and e.digest(qa) == final['qa_digest'] and
                      qa['artifact'] == e.digest(artifact) and qa['token'] == row['claim']['token'] and
                      qa['task'] == task and qa['execution'] == row['authorization']['execution'] and
                      qa['authorization'] == e.digest(row['authorization']) and
                      qa['source_manifest'] == row['authorization']['source_manifest'] and
                      qa['candidate_manifest'] == artifact['candidate_manifest'] and
                      [x['name'] for x in qa['checks']] == ['diff', *[x['name'] for x in row['authorization']['checks']], 'candidate'] and
                      all(x['code'] == 0 and x['reason'] is None for x in qa['checks']),
                      'Missing or contradictory independent evidence')
    return dict(schema=OBSERVATIONS, read_only=True, authorization_authority=False, **{k:v for k,v in view.items() if k != 'schema'})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['init', 'slots', 'inspect', 'active', 'queued', 'completed', 'failed', 'resources', 'recover'])
    p.add_argument('--config', required=True)
    p.add_argument('--task'); p.add_argument('--reason')
    args = p.parse_args(argv)
    try:
        c = Coordinator(configuration(args.config))
        if args.command == 'init': c.initialize(); result = {'schema': PROTOCOL}
        elif args.command == 'recover':
            from src.local_runner import terminal_challenge
            view = c.inspect(); claim = view['tasks'][args.task]['claim']
            response = terminal_challenge('RECONCILE '+e.digest(claim))
            c.recover(claim, args.reason, response); result = c.inspect()
        else:
            result = observations(c.c)
            if args.command == 'slots': result = result['configured_slots']
            elif args.command == 'resources': result = dict(aggregate=result['aggregate'], tasks={k:v['usage'] for k,v in result['tasks'].items()})
            elif args.command in ('active', 'queued', 'completed', 'failed'):
                states = {'active': ACTIVE, 'queued': {'queued'}, 'completed': {'completed'}, 'failed': {'failed', 'held', 'interrupted', 'cancelled'}}[args.command]
                result = {k:v for k,v in result['tasks'].items() if v['state'] in states}
        print(json.dumps(result, sort_keys=True, indent=2)); return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        p.exit(1, 'Coordinator failed closed; inspect protected configuration, evidence and recovery state.\n')


if __name__ == '__main__': main()
