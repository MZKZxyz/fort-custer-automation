"""Bounded daily advisory cycles. No authorization, worker or publication capability."""
import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import tempfile
import threading
import time
from zoneinfo import ZoneInfo

from src.discovery_collection import canonical, decode
from src.issue_discovery import Discovery, Store, validate_config
from src.observation_validation import regular
from src import task_orchestration as observation

PROTOCOL = 'daily-planning-v1'
NOTICE = 'Advisory report only; no authorization authority. No execution performed.'
FIELDS = {'schema', 'enabled', 'timezone', 'local_start', 'max_duration_seconds',
          'output', 'discovery_store', 'discovery', 'orchestration', 'stop_files',
          'retain_reports', 'max_cycles', 'max_storage_bytes', 'max_report_bytes',
          'retry_limit', 'backoff_seconds'}


def require(test, message):
    if not test:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def configuration(path):
    path = regular(path)
    c = decode(path.read_bytes())
    require(isinstance(c, dict) and set(c) == FIELDS and c['schema'] == PROTOCOL,
            'Unsupported daily configuration')
    require(type(c['enabled']) is bool, 'Explicit enabled boolean required')
    require(isinstance(c['timezone'], str), 'Invalid timezone')
    ZoneInfo(c['timezone'])
    require(isinstance(c['local_start'], str) and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', c['local_start']),
            'Explicit local start HH:MM required')
    for key, low, high in [('max_duration_seconds', 1, 3600), ('retain_reports', 1, 366),
                           ('max_cycles', 1, 100000), ('max_storage_bytes', 1024*1024, 1024**3),
                           ('max_report_bytes', 1024, 16*1024*1024)]:
        require(type(c[key]) is int and low <= c[key] <= high, 'Invalid '+key)
    # Deliberately no automatic retries, including GETs. Preserve partial failures.
    require(type(c['retry_limit']) is int and c['retry_limit'] == 0 and
            type(c['backoff_seconds']) is int and c['backoff_seconds'] == 0, 'Retries unsupported; use zero limits')
    require(isinstance(c['stop_files'], list) and c['stop_files'] and all(
        isinstance(p, str) and Path(p).is_absolute() and Path(p).name == 'STOP' for p in c['stop_files']), 'Explicit STOP paths required')
    for key in ('output', 'discovery_store', 'orchestration'):
        require(isinstance(c[key], str) and Path(c[key]).is_absolute(), 'Absolute paths required')
    c['discovery'] = validate_config(c['discovery'])
    o = observation.config(c['orchestration'])
    require(set(c['stop_files']) >= set(o['stop_files']) | set(c['discovery']['stop_files']), 'STOP union required')
    require(Path(c['discovery_store']).absolute() == Path(o['discovery']).absolute(), 'Discovery source mismatch')
    out = Path(c['output'])
    # All scheduler writes must fit in one dedicated, non-overlapping root.
    require(Path(c['discovery_store']).parent == out, 'Discovery store must be dedicated to daily output')
    roots = [Path(__file__).resolve().parents[1], Path(o['execution']).parent]
    require(all(not out.resolve().is_relative_to(p.resolve()) and not p.resolve().is_relative_to(out.resolve())
                for p in roots), 'Output overlaps controller or source storage')
    for p in [path, Path(c['orchestration']), *[Path(o[k]) for k in ('ledger','policy','promotion','execution')],
              *map(Path,c['stop_files'])]:
        require(not p.resolve().is_relative_to(out.resolve()), 'Output overlaps protected source or STOP')
    require(Path(c['discovery_store']).name not in {'cycles.sqlite','cycle.lock'}, 'Reserved output name')
    # Bind the full reviewed orchestration configuration, not just its pathname.
    return c, o, digest(dict(configuration=c, orchestration=o))


def validate_destination(c, o):
    policy = observation.evidence.read_policy(o['policy'])[0]
    out = Path(c['output']).resolve()
    roots = [Path(policy['scratch']), Path(policy['state']),
             *[Path(r['source']) for r in policy['repositories'].values()]]
    require(all(not out.is_relative_to(p.resolve()) and not p.resolve().is_relative_to(out)
                for p in roots), 'Unsafe output root')
    require(str(Path(policy['state'])/'STOP') in c['stop_files'], 'Controller STOP required')


class BoundedDiscoveryStore(Store):
    """Same v1 evidence format; cap allocated SQLite pages including journal reserve."""
    def __init__(self, path, page_budget):
        super().__init__(path)
        self.page_budget = page_budget

    @contextlib.contextmanager
    def tx(self, readonly=False):
        with super().tx(readonly=readonly) as db:
            if not readonly:
                page_size = db.execute('PRAGMA page_size').fetchone()[0]
                count = db.execute('PRAGMA page_count').fetchone()[0]
                maximum = self.page_budget // page_size
                require(count <= maximum, 'Discovery physical storage capacity reached')
                db.execute('PRAGMA max_page_count='+str(maximum))
            yield db


def cycle_identity(c, reviewed_digest, epoch):
    local = datetime.fromtimestamp(epoch, ZoneInfo(c['timezone']))
    day = local.date().isoformat()
    return day, digest(dict(protocol=PROTOCOL, local_date=day, configuration_digest=reviewed_digest))


def atomic(path, payload):
    fd, tmp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        require(not path.exists() and not path.is_symlink(), 'Refuse report replacement')
        os.replace(tmp, path)
        syncdir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def syncdir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Cycles:
    def __init__(self, output):
        self.root = Path(output)
        self.path = self.root/'cycles.sqlite'

    def initialize(self):
        self.root.mkdir(mode=0o700, parents=False, exist_ok=True)
        s = self.root.lstat()
        require(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode) and s.st_uid == os.getuid()
                and not s.st_mode & 0o077, 'Private output directory required')
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd); regular(self.path)
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE metadata(schema TEXT NOT NULL);
                INSERT INTO metadata VALUES ('daily-planning-v1');
                CREATE TABLE claims(id TEXT PRIMARY KEY, day TEXT NOT NULL, config TEXT NOT NULL,
                    started REAL NOT NULL, state TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY, cycle TEXT NOT NULL, kind TEXT NOT NULL,
                    document TEXT NOT NULL);
                CREATE TRIGGER claim_no_update BEFORE UPDATE ON claims BEGIN SELECT RAISE(ABORT,'Immutable claim'); END;
                CREATE TRIGGER claim_no_delete BEFORE DELETE ON claims BEGIN SELECT RAISE(ABORT,'Immutable claim'); END;
                CREATE TRIGGER event_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'Immutable event'); END;
                CREATE TRIGGER event_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'Immutable event'); END;''')
        syncdir(self.root)

    @contextlib.contextmanager
    def tx(self, write=False):
        regular(self.path)
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=1)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            if not write:
                db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            require(db.execute('SELECT schema FROM metadata').fetchall() == [(PROTOCOL,)], 'Unknown cycle protocol')
            require({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} ==
                    {'metadata','claims','events'}, 'Unknown cycle schema')
            require(db.execute('PRAGMA quick_check').fetchone() == ('ok',), 'Corrupt cycle ledger')
            yield db
            if write:
                db.commit()
        finally:
            db.close()

    @contextlib.contextmanager
    def lock(self):
        # Never unlink a flock inode: a waiting launcher must lock the same inode.
        regular(self.path)
        fd = os.open(self.root/'cycle.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            regular(self.root/'cycle.lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another daily cycle holds the lock') from None
            yield
        finally:
            os.close(fd)

    def history(self, limit=50):
        require(type(limit) is int and 1 <= limit <= 100, 'History limit 1..100 required')
        with self.tx() as db:
            return [dict(id=i, day=d, configuration_digest=c, started_at=stamp(t), state=self.state(db,i))
                    for i,d,c,t in db.execute('SELECT id,day,config,started FROM claims ORDER BY started DESC,id LIMIT ?', (limit,))]

    def inspect(self, identity=None):
        with self.tx() as db:
            if identity is None:
                row = db.execute('SELECT id FROM claims ORDER BY started DESC,id LIMIT 1').fetchone()
                require(row is not None, 'No cycle claims')
                identity = row[0]
            claim = db.execute('SELECT day,config,started FROM claims WHERE id=?',(identity,)).fetchone()
            require(claim is not None, 'Unknown cycle')
            events = [dict(kind=k,document=json.loads(doc)) for k,doc in db.execute(
                'SELECT kind,document FROM events WHERE cycle=? ORDER BY seq',(identity,))]
            return dict(cycle_id=identity,local_planning_date=claim[0],configuration_digest=claim[1],
                        started_at=stamp(claim[2]),state=self.state(db,identity),events=events,
                        notice=NOTICE,report_files={suffix:(self.root/(identity+suffix)).exists()
                                                   for suffix in ('.json','.txt')})

    @staticmethod
    def state(db, identity):
        row = db.execute("SELECT kind FROM events WHERE cycle=? AND kind IN ('complete','failed','interrupted') ORDER BY seq DESC LIMIT 1", (identity,)).fetchone()
        return row[0] if row else 'incomplete'

    def event(self, identity, kind, document):
        with self.tx(True) as db:
            db.execute('INSERT INTO events(cycle,kind,document) VALUES (?,?,?)', (identity,kind,canonical(document)))

    def claim(self, identity, day, reviewed_digest, epoch, maximum):
        with self.tx(True) as db:
            if db.execute('SELECT 1 FROM claims WHERE id=?', (identity,)).fetchone():
                return False
            require(not db.execute("SELECT 1 FROM claims c WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.cycle=c.id AND e.kind IN ('complete','failed','interrupted'))").fetchone(),
                    'Incomplete claim requires explicit operator recovery')
            last = db.execute('SELECT MAX(day),MAX(started),COUNT(*) FROM claims').fetchone()
            require(last[2] < maximum, 'Cycle history capacity reached; preserve and rotate manually')
            require(last[0] is None or (day >= last[0] and epoch >= last[1]), 'Clock regression; inspect manually')
            db.execute('INSERT INTO claims VALUES (?,?,?,?,?)', (identity,day,reviewed_digest,epoch,'claimed'))
            db.execute('INSERT INTO events(cycle,kind,document) VALUES (?,?,?)', (identity,'claimed',canonical({'at':stamp(epoch)})))
        return True

    def recover(self, identity, reason):
        require(isinstance(reason,str) and 1 <= len(reason) <= 1000, 'Recovery reason required')
        with self.lock(), self.tx(True) as db:
            require(db.execute('SELECT 1 FROM claims WHERE id=?',(identity,)).fetchone() and self.state(db,identity)=='incomplete', 'Only incomplete claims can be recovered')
            db.execute('INSERT INTO events(cycle,kind,document) VALUES (?,?,?)', (identity,'interrupted',canonical(dict(reason=reason, advisory_only=True))))
        return {'state':'interrupted', 'cycle_id':identity}

    def read_report(self, identity):
        with self.tx() as db:
            row = db.execute("SELECT kind,document FROM events WHERE cycle=? AND kind IN ('complete','failed') ORDER BY seq DESC LIMIT 1",(identity,)).fetchone()
            require(row is not None, 'No finalized report; inspect incomplete claim')
            require(not db.execute("SELECT 1 FROM events WHERE cycle=? AND kind='retired'",(identity,)).fetchone(), 'Report retired; digest remains in history')
        receipt = json.loads(row[1])
        for suffix in ('.json','.txt'):
            require(regular(self.root/(identity+suffix)).stat().st_size <= 16*1024*1024, 'Oversized stored report')
        payload = regular(self.root/(identity+'.json')).read_bytes()
        text = regular(self.root/(identity+'.txt')).read_bytes()
        require(hashlib.sha256(payload).hexdigest()==receipt['json_sha256'] and
                hashlib.sha256(text).hexdigest()==receipt['text_sha256'], 'Report integrity failure')
        result = observation.evidence.decode(payload)
        require(result['status']==row[0] and result['cycle_id']==identity, 'Report receipt mismatch')
        return result

    def retain(self, count):
        with self.tx() as db:
            ids = [r[0] for r in db.execute("SELECT cycle FROM events e WHERE kind='complete' AND NOT EXISTS (SELECT 1 FROM events x WHERE x.cycle=e.cycle AND x.kind='retired') ORDER BY seq DESC")]
        for identity in ids[count:]:
            # Retire first: a crash or deletion failure can never advertise missing evidence as current.
            self.event(identity,'retired',{'reason':'bounded successful-report retention'})
            for suffix in ('.json','.txt'):
                p = regular(self.root/(identity+suffix)); p.unlink()
            syncdir(self.root)


def size_guard(c):
    total = 0
    for p in Path(c['output']).iterdir():
        s=p.lstat()
        require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and not s.st_mode & 0o077, 'Unexpected output object')
        total += s.st_size
    require(total + 2*c['max_report_bytes'] + 65536 <= c['max_storage_bytes'], 'Storage capacity reached')


@contextlib.contextmanager
def deadline(guard):
    require(threading.current_thread() is threading.main_thread(), 'Daily controller requires main thread supervision')
    old = {s:signal.getsignal(s) for s in (signal.SIGALRM,signal.SIGTERM,signal.SIGINT)}
    previous = signal.getitimer(signal.ITIMER_REAL)
    require(previous == (0.0,0.0), 'Existing process timer unsupported')
    def tick(*_):
        guard()
    def cancel(*_):
        raise InterruptedError('Cycle interrupted')
    try:
        signal.signal(signal.SIGALRM,tick)
        signal.signal(signal.SIGTERM,cancel); signal.signal(signal.SIGINT,cancel)
        signal.setitimer(signal.ITIMER_REAL,0.1,0.1)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        for s,h in old.items():
            signal.signal(s,h)


def summarize(view, o):
    # Keep hashes and actionable summaries, never copy prompts, patches or logs into reports.
    keys = ('id','repository','issue','state','last_supported_state','priority','risk','blockers',
            'required_action','usage','estimated_cost','qa_validated','evidence','source_ids','resource_limits')
    tasks = [{k:t[k] for k in keys if k in t} for t in view['tasks']]
    return dict(observation_digest=observation.evidence.digest(view),
                tasks=tasks, planning_preview=observation.preview(view,o),
                evidence_summary=observation.report(view),
                tasks_awaiting_promotion_review=[t['id'] for t in tasks if t['state'] in ('proposed','awaiting-promotion-review')],
                tasks_awaiting_coding_approval=[t['id'] for t in tasks if t['state']=='awaiting-coding-approval'],
                qa_failures_and_blocked=[t['id'] for t in tasks if t['state'] in ('blocked','rejected','cancelled','interrupted')],
                publication_reviews=[t['id'] for t in tasks if t['state']=='awaiting-publication-review'],
                recorded_draft_prs=[t['id'] for t in tasks if t['state'] in ('published-draft-recorded','awaiting-human-merge')])


def render(report):
    def escaped(value):
        return json.dumps(value,sort_keys=True,ensure_ascii=True,allow_nan=False)
    lines = [NOTICE, 'Cycle: '+report['cycle_id'], 'Planning date: '+report['local_planning_date'],
             'Status: '+report['status']+' / '+report['stage'],
             'Started: '+report['started_at'], 'Completed: '+report['completed_at'],
             'Configuration SHA-256: '+report['configuration_digest'],
             'GitHub: '+escaped(report['github_collection']),
             'New/revised proposal IDs: '+escaped(report['new_or_revised_proposals']),
             'Proposed order (sequential, separate approvals required): '+escaped(
                 [t['id'] for t in report.get('planning_preview',{}).get('selected',[])]),
             'STOP / infrastructure: '+escaped(report['stop_and_infrastructure']),
             'Usage / budget evidence: '+escaped(report.get('evidence_summary',{}).get('resource_usage','unknown')),
             'Cost: '+report['cost_estimates']]
    for t in report.get('tasks',[]):
        lines.append('Task '+escaped(t['id'])+' ['+t['state']+'] priority='+str(t['priority'])+
                     ': '+escaped(t['required_action'])+'; blockers='+escaped(t['blockers']))
    for key in ('tasks_awaiting_promotion_review','tasks_awaiting_coding_approval','qa_failures_and_blocked',
                'publication_reviews','recorded_draft_prs','errors','next_operator_actions'):
        lines.append(key+': '+escaped(report.get(key,[])))
    return ('\n'.join(lines)+'\n').encode()


def run(c, o, reviewed_digest, *, scheduled=False, transport=None, clock=time.time,
        monotonic=time.monotonic, cancelled=lambda:False):
    started = clock(); began = monotonic()
    day, identity = cycle_identity(c,reviewed_digest,started)
    ledger = Cycles(c['output'])
    if scheduled:
        local = datetime.fromtimestamp(started,ZoneInfo(c['timezone']))
        require(c['enabled'] and local.strftime('%H:%M') >= c['local_start'], 'Schedule disabled or local start not reached')
    with ledger.lock():
        if not ledger.claim(identity,day,reviewed_digest,started,c['max_cycles']):
            with ledger.tx() as db:
                state=ledger.state(db,identity)
            return dict(cycle_id=identity,status=state,duplicate=True,advisory_only=True)
        report = dict(protocol=PROTOCOL,cycle_id=identity,local_planning_date=day,started_at=stamp(started),
                      completed_at=None, configuration_digest=reviewed_digest,notice=NOTICE,
                      advisory_only=True,execution_performed=False,status='failed',
                      github_collection={'status':'not-started'},new_or_revised_proposals=[],
                      stage='preflight', errors=[],next_operator_actions=[],stop_and_infrastructure={},
                      cost_estimates='unknown; subscription usage is not a hard $10/day billing cap')
        def guard(*, work=True):
            require(not cancelled(), 'Cycle cancelled')
            require(not any(Path(p).exists() or Path(p).is_symlink() for p in c['stop_files']), 'STOP active')
            limit = c['max_duration_seconds']
            if work:
                limit -= min(5,limit/5)  # Reserve bounded time for a failed report.
            require(monotonic()-began < limit, 'Cycle duration exceeded')
            wall = clock()
            require(wall >= started, 'Clock moved backwards during cycle')
            require(wall-started <= monotonic()-began+60, 'Clock jumped forwards during cycle')
        try:
            with deadline(guard):
                guard(); size_guard(c)
                validate_destination(c,o)
                report['stage']='discovery'
                used = sum(p.stat().st_size for p in ledger.root.iterdir() if p.name != Path(c['discovery_store']).name)
                page_budget = (c['max_storage_bytes']-used-2*c['max_report_bytes']-131072)//2
                regular(c['discovery_store'])
                store = BoundedDiscoveryStore(c['discovery_store'],page_budget)
                with store.tx(readonly=True) as db:
                    old = {r[0] for r in db.execute('SELECT id FROM proposals')}
                report['github_collection']['status']='collecting'
                ids = Discovery(c['discovery'],store,transport=transport,cancelled=lambda:(guard() or False),
                    clock=lambda:datetime.fromtimestamp(clock(),timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')).discover()
                report['github_collection']={'status':'complete','observed_proposals':len(ids),
                    'repositories':sorted(c['discovery']['repositories']),
                    'request_limit':c['discovery']['max_requests'],'transport':'anonymous GET only'}
                report['new_or_revised_proposals']=sorted(set(ids)-old)
                guard(); size_guard(c)
                # Fresh read-only reconciliation. Never consume an older successful snapshot.
                report['stage']='reconciliation'
                view, _ = observation.reconcile(o,clock())
                report.update(summarize(view,o))
                report['errors'].extend(view['errors'])
                report['stop_and_infrastructure']=dict(stopped=view['stopped'],sources_current=not view['errors'],
                    active_coding_claims=view['active_claims'],max_active_workers=1)
                guard()
                require(not view['errors'], 'Reconciliation has unresolved source evidence')
                report['status']='complete'
                report['stage']='retention'
                ledger.retain(c['retain_reports']-1)
                guard(); size_guard(c)
        except (Exception,KeyboardInterrupt) as error:
            report['status']='failed'
            # Exception messages can contain credentials or untrusted provider data. Record type/stage only.
            report['errors'].append('Cycle failed closed: '+type(error).__name__)
            report['next_operator_actions'].append('Inspect cycle stage, STOP and protected source evidence; no automatic retry. Preserve all records.')
            report['stop_and_infrastructure']['stopped']=any(Path(p).exists() or Path(p).is_symlink() for p in c['stop_files'])
            if report['github_collection']['status']=='collecting':
                report['github_collection']['status']='failed; transaction rolled back; no checkpoint advance'
            if 'planning_preview' in report:
                report['planning_preview']['selected']=[]
        if report['status']=='complete':
            report['stage']='finalized'
        if report['status']=='failed' and 'planning_preview' not in report:
            report['planning_preview']={'advisory_only':True,'selected':[], 'execution_performed':False,
                                        'blockers':['Cycle incomplete or failed']}
        def finalize_guard():
            require(monotonic()-began < c['max_duration_seconds'], 'Cycle duration exceeded during finalization')
            if report['status']=='complete':
                guard(work=False)
        try:
            with deadline(finalize_guard):
                finalize_guard()
                report['completed_at']=stamp(clock())
                payload=(json.dumps(report,sort_keys=True,ensure_ascii=True,allow_nan=False,indent=2)+'\n').encode()
                human=render(report)
                require(max(len(payload),len(human)) <= c['max_report_bytes'], 'Report size exceeded')
                atomic(ledger.root/(identity+'.json'),payload)
                finalize_guard()
                atomic(ledger.root/(identity+'.txt'),human)
                finalize_guard()
                ledger.event(identity,report['status'],dict(json_sha256=hashlib.sha256(payload).hexdigest(),
                            text_sha256=hashlib.sha256(human).hexdigest()))
        except (OSError,ValueError,sqlite3.Error):
            # Partial files never have a success receipt; retained claim needs operator recovery.
            raise ValueError('Report persistence failed; incomplete claim retained; inspect and recover explicitly') from None
        return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('init','run','inspect','history','report','recover'))
    p.add_argument('--config',required=True);p.add_argument('--scheduled',action='store_true')
    p.add_argument('--cycle');p.add_argument('--reason');p.add_argument('--limit',type=int,default=50)
    args=p.parse_args(argv)
    try:
        c,o,reviewed=configuration(args.config); ledger=Cycles(c['output'])
        if args.command=='init':
            validate_destination(c,o)
            ledger.initialize()
            # Explicit first-time only; never replace an existing discovery database.
            with ledger.lock():
                require(not Path(c['discovery_store']).exists(), 'Discovery evidence already exists; do not reset')
                oldmask=os.umask(0o077)
                try:
                    Store(c['discovery_store']).initialize()
                finally:
                    os.umask(oldmask)
            out={'initialized':True,'timer_installed':False,'profile_enabled':c['enabled']}
        elif args.command=='run':
            out=run(c,o,reviewed,scheduled=args.scheduled)
        elif args.command=='recover':
            out=ledger.recover(args.cycle,args.reason)
        elif args.command=='inspect':
            out=ledger.inspect(args.cycle)
        elif args.command=='history':
            out={'cycles':ledger.history(args.limit),'configuration_digest':reviewed}
        else:
            identity=args.cycle or ledger.history(1)[0]['id'];out=ledger.read_report(identity)
        print(json.dumps(out,indent=2,ensure_ascii=True,allow_nan=False))
        if args.command=='run' and out['status']!='complete':
            return 1
        return 0
    except (OSError,ValueError,KeyError,TypeError,IndexError,sqlite3.Error):
        p.exit(1,'Daily planning failed closed; inspect protected configuration, claims, STOP and storage.\n')


if __name__=='__main__':
    raise SystemExit(main())
