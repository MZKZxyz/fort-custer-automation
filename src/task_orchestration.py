"""Manual operational views and durable derived observations; no dispatch capability."""
import argparse
from collections import Counter
import contextlib
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import time

from src import orchestration_evidence as evidence

PROTOCOL = 'task-orchestration-v1'
COMMANDS = {'init','sync','queue','inspect','status','report','preview'}
FIELDS = {'schema','ledger','policy','discovery','promotion','execution','stop_files','planning'}


def config(path):
    result = evidence.decode(evidence.regular(path).read_bytes())
    evidence.require(isinstance(result,dict) and set(result) == FIELDS and result['schema'] == PROTOCOL,
                     'Unsupported orchestration configuration')
    for key in ('ledger','policy','discovery','promotion','execution'):
        evidence.require(isinstance(result[key],str) and Path(result[key]).is_absolute(), 'Absolute configured paths required')
    paths = [Path(result[k]).resolve() for k in ('ledger','policy','discovery','promotion','execution')]
    evidence.require(len(set(paths)) == len(paths), 'Separate orchestration ledger required')
    stops = result['stop_files']
    evidence.require(isinstance(stops,list) and bool(stops) and all(isinstance(p,str) and Path(p).is_absolute()
                     and Path(p).name == 'STOP' for p in stops), 'Explicit STOP paths required')
    p = result['planning']
    evidence.require(isinstance(p,dict) and set(p) == {'future_capacity','max_active_workers','max_recommendations','tasks'}
                     and type(p['future_capacity']) is int and 1 <= p['future_capacity'] <= 3
                     and type(p['max_active_workers']) is int and p['max_active_workers'] == 1
                     and type(p['max_recommendations']) is int and 1 <= p['max_recommendations'] <= 100
                     and isinstance(p['tasks'],dict) and len(p['tasks']) <= evidence.LIMIT,
                     'Invalid advisory capacity configuration')
    for identity, meta in p['tasks'].items():
        evidence.require(isinstance(identity,str) and isinstance(meta,dict) and
                         set(meta) == {'entry_digest','priority','risk','depends_on'} and evidence.sha(meta['entry_digest'])
                         and type(meta['priority']) is int and -100 <= meta['priority'] <= 100 and
                         meta['risk'] in ('low','medium','high') and isinstance(meta['depends_on'],list) and
                         all(isinstance(d,str) and d != identity for d in meta['depends_on']) and
                         len(set(meta['depends_on'])) == len(meta['depends_on']), 'Invalid planning metadata')
    return result


class Ledger:
    """Append-only content-addressed snapshots in an exclusively created database."""
    def __init__(self, path):
        self.path = Path(path).absolute()

    def initialize(self):
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        evidence.regular(self.path)
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE metadata(schema TEXT NOT NULL);
                INSERT INTO metadata VALUES ('task-orchestration-v1');
                CREATE TABLE observations(id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE snapshots(seq INTEGER PRIMARY KEY, id TEXT NOT NULL, at REAL NOT NULL, document TEXT NOT NULL);''')
            for table in ('metadata','observations','snapshots'):
                for op in ('UPDATE','DELETE'):
                    db.execute(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable derived evidence'); END")

    @contextlib.contextmanager
    def tx(self, write=False):
        evidence.regular(self.path)
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=10)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            if not write:
                db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            evidence.require(db.execute('SELECT schema FROM metadata').fetchall() == [(PROTOCOL,)], 'Unknown orchestration ledger')
            evidence.require({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} ==
                             {'metadata','observations','snapshots'}, 'Unknown derived ledger schema')
            evidence.require(db.execute('PRAGMA quick_check').fetchone() == ('ok',), 'Derived ledger integrity failure')
            yield db
            if write:
                db.commit()
        finally:
            db.close()

    def save(self, view, observations, at):
        identity = evidence.digest(view)
        with self.tx(write=True) as db:
            last = db.execute('SELECT at,id FROM snapshots ORDER BY seq DESC LIMIT 1').fetchone()
            evidence.require(last is None or at >= last[0], 'Orchestration clock regression')
            for ref, doc in observations.items():
                evidence.require(ref == evidence.digest(doc), 'Observation digest mismatch')
                db.execute('INSERT OR IGNORE INTO observations VALUES (?,?)', (ref,evidence.canonical(doc)))
            if last is None or last[1] != identity:
                db.execute('INSERT INTO snapshots(id,at,document) VALUES (?,?,?)', (identity,at,evidence.canonical(view)))
        return identity

    def latest(self):
        with self.tx() as db:
            row = db.execute('SELECT id,at,document FROM snapshots ORDER BY seq DESC LIMIT 1').fetchone()
            evidence.require(row is not None, 'No reconciliation; invoke sync explicitly')
            view = evidence.decode(row[2])
            evidence.require(evidence.digest(view) == row[0], 'Derived snapshot modified')
            for task in view['tasks']:
                for ref in task['evidence']:
                    observed = db.execute('SELECT document FROM observations WHERE id=?',(ref,)).fetchone()
                    evidence.require(observed is not None and evidence.digest(evidence.decode(observed[0])) == ref,
                                     'Missing immutable evidence reference')
        return dict(snapshot=row[0], observed_at=row[1], historical_only=True, **view)


def task(identity, repository=None, issue=None, state='blocked', action='Inspect source evidence manually'):
    return dict(id=identity, repository=repository, issue=issue, state=state, priority=0, risk='unknown',
                evidence=[], source_ids={}, required_action=action, blockers=[], usage=None, qa_validated=False, estimated_cost='unknown', depends_on=[])


def block(t, reason):
    if t['state'] != 'blocked':t['last_supported_state']=t['state']
    t['blockers'] = sorted(set([*t['blockers'], reason]))
    t['state'] = 'blocked'
    t['required_action'] = 'Inspect referenced subsystem evidence; reconcile manually using its existing CLI; no automatic retry'


def promotion_state(rows, proposals, policy, policy_path, now):
    useful = [r for r in rows if r['kind'] != 'rejected']
    evidence.require(bool(useful) and useful[0]['kind'] == 'prepared', 'Missing promotion preparation')
    d = useful[0]['document']; bound = dict(d); binding = bound.pop('binding')
    evidence.require(evidence.digest(bound) == binding and d['protocol'] == 'catalog-promotion-v1' and
                     d['destination'] == str(Path(policy_path).absolute()) and
                     d['proposal_digest'] == evidence.digest(d['proposal']) and
                     proposals.get(d['proposal']['proposal']['id']) == d['proposal'], 'Promotion provenance mismatch')
    p=d['proposal']['proposal'];s=d['proposal']['snapshot']
    evidence.require(d['risk'] in ('low','medium') and d['entry']['repository'] == p['repository'] and
                     d['entry']['issue'] == p['issue_number'] and d['entry']['source'] == p['source_commit'] and
                     d['entry']['issue_snapshot'] == s['issue'], 'Promotion reviewed provenance mismatch')
    times = [r['at'] for r in rows]
    evidence.require(times == sorted(times) and times[-1] <= now and evidence.finite(d['prepared_at']) and
                     d['prepared_at'] <= useful[0]['at'] < d['prepared_at']+300, 'Promotion chronology mismatch')
    kinds = [r['kind'] for r in useful]
    order = ['prepared','approved','export-intent','exported','import-intent','imported']
    failure = kinds[-1] in ('export-failed','import-uncertain')
    prefix = kinds[:-1] if failure else kinds
    evidence.require(prefix == order[:len(prefix)] and len(prefix) <= len(order), 'Promotion event conflict')
    if failure:
        evidence.require((kinds[-1] == 'export-failed' and prefix[-1] == 'export-intent') or
                         (kinds[-1] == 'import-uncertain' and prefix[-1] == 'import-intent'), 'Invalid promotion failure')
    if len(useful) > 1:
        a = useful[1]
        evidence.require(a['document']['binding'] == binding and
                         d['prepared_at'] <= a['at'] < d['prepared_at']+300 and
                         evidence.finite(a['document']['expires']) and
                         300 <= a['document']['expires']-a['at'] <= 301, 'Promotion approval mismatch')
        evidence.require(all(r['at'] < a['document']['expires'] for r in useful[2:]
                             if r['kind'] not in ('imported','export-failed','import-uncertain')), 'Expired promotion grant was used')
    if len(useful) >= 3:
        intent = useful[2]['document']
        evidence.require(isinstance(intent.get('path'),str) and Path(intent['path']).is_absolute() and
                         evidence.sha(intent.get('digest')), 'Invalid export intent')
        if len(useful) >= 4 and useful[3]['kind'] == 'exported':
            evidence.require(useful[3]['document'] == intent, 'Export receipt contradicts intent')
    if kinds[-1] == 'imported':
        evidence.require(useful[-1]['document'] == dict(task_id=d['task_id'],policy_digest=d['resulting_policy_digest']) and
                         policy['catalog']['tasks'].get(d['task_id']) == d['entry'] and
                         useful[-2]['document']['after'] == d['resulting_policy_digest'] and
                         useful[-2]['document']['before'] == d['revision'], 'Imported catalog evidence mismatch')
        return d, 'reviewed-catalog-task', 'Promotion imported; coding still requires separate terminal approval'
    evidence.require(evidence.digest(policy) == d['policy_digest'], 'Catalog revision conflicts with promotion')
    if failure or kinds[-1] in ('export-intent','import-intent'):
        return d, 'ambiguous-promotion', 'Use src.catalog_promotion inspect; manually reconcile export/destination intents; do not replay'
    expires = d['prepared_at']+300 if len(useful) == 1 else useful[1]['document']['expires']
    if now >= expires:
        return d, 'expired', 'Use src.catalog_promotion inspect and prepare a new reviewed attempt after reconciliation'
    return d, 'awaiting-promotion-review', 'Use src.catalog_promotion inspect, then its separately authorized approve/apply/import commands as appropriate'


def fingerprint(path):
    # Includes live SQLite WAL bytes; no immutable=1 (which would ignore WAL).
    result = []
    for suffix in ('','-wal'):
        p = Path(str(path)+suffix)
        if p.exists():
            evidence.regular(p)
            evidence.require(p.stat().st_size <= 1024**3, 'Evidence source exceeds size bound')
            h=hashlib.sha256()
            with p.open('rb') as source:
                for chunk in iter(lambda:source.read(1024*1024), b''):h.update(chunk)
            result.append((suffix,h.hexdigest()))
        elif not suffix:
            raise ValueError('Missing configured evidence source')
    return result


def reconcile(c, now=None, remote=None):
    now = time.time() if now is None else now
    evidence.require(evidence.finite(now), 'Invalid reconciliation clock')
    tasks, observations, errors = {}, {}, []
    def attach(t, source, identity, document):
        t['source_ids'].setdefault(source,[])
        if identity not in t['source_ids'][source]:t['source_ids'][source].append(identity)
        doc = dict(source=source, identity=identity, document=document)
        ref = evidence.digest(doc); observations[ref] = doc
        if ref not in t['evidence']:
            t['evidence'].append(ref)
    sources = {k:c[k] for k in ('policy','discovery','promotion','execution')}
    before = {}
    for name, path in sources.items():
        try:
            before[name] = fingerprint(path)
        except (OSError,ValueError):
            errors.append(name+': missing or unsafe evidence source')
    policy, specs, proposals, promotions, runs, pubs = None, {}, {}, {}, {}, {}
    for name, adapter in [('policy',lambda:evidence.catalog(c['policy'])),
                          ('discovery',lambda:evidence.discovery(c['discovery'])),
                          ('promotion',lambda:evidence.promotions(c['promotion'])),
                          ('execution',lambda:evidence.executions(c['execution']))]:
        try:
            data = adapter()
            if name == 'policy':
                policy, _, specs = data
                evidence.require(Path(c['execution']).absolute() == Path(policy['state']).absolute()/'local.sqlite',
                                 'Execution source differs from policy')
                protected = [Path(policy['scratch']).resolve(), *[Path(r['source']).resolve() for r in policy['repositories'].values()]]
                evidence.require(not any(Path(c['ledger']).resolve().is_relative_to(p) for p in protected),
                                 'Derived ledger overlaps worker/source storage')
            elif name == 'discovery': proposals = data
            elif name == 'promotion': promotions = data
            else: runs, pubs = data
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
            errors.append(name+': unsupported, incomplete or conflicting source evidence')
    for identity, spec in specs.items():
        t = task(identity, spec['task']['repository'], spec['issue'], 'awaiting-coding-approval',
                 'Separately invoke src.local_runner task-prepare and review its terminal authorization')
        tasks[identity] = t
        attach(t,'catalog',identity,spec)
        t['resource_limits']=dict(timeout_seconds=spec['limits']['timeout_seconds'],
            usage_policy=spec['limits']['usage_policy'],cpu='unsupported',memory='unsupported',hard_subscription_cost_cap='unsupported')
        meta = c['planning']['tasks'].get(identity)
        if meta and meta['entry_digest'] == evidence.digest(spec['task']):
            t.update(priority=meta['priority'],risk=meta['risk'],depends_on=meta['depends_on'])
        else:
            block(t,'Missing or stale operator planning metadata; bind risk/priority/dependencies to exact catalog entry')
    proposal_tasks = {}
    for identity, record in proposals.items():
        p = record['proposal']
        t = task('proposal:'+identity,p['repository'],p['issue_number'],'proposed',
                 'Review with src.issue_discovery inspect; promotion needs an independently supplied reviewed entry')
        t.update(priority=p['priority'],risk=p['risk'])
        tasks[t['id']] = t; proposal_tasks[identity] = t
        attach(t,'discovery',identity,record)
    promoted_proposals = set()
    for identity, rows in promotions.items():
        if all(r['kind'] == 'rejected' for r in rows):
            t = task('promotion:'+identity);tasks[t['id']] = t;block(t,'Rejected promotion attempt requires operator inspection')
            attach(t,'promotion',identity,rows);continue
        d = rows[0]['document']; target = d.get('task_id')
        t = tasks.get(target) if [r for r in rows if r['kind'] != 'rejected'][-1]['kind'] == 'imported' else None
        if t is None:
            t = task('promotion:'+identity, d.get('entry',{}).get('repository'),d.get('entry',{}).get('issue'))
            tasks[t['id']] = t
        attach(t,'promotion',identity,rows)
        try:
            evidence.require(d.get('id') == identity, 'Promotion identity replay')
            d, state, action = promotion_state(rows,proposals,policy,c['policy'],now)
            pid = d['proposal']['proposal']['id']; promoted_proposals.add(pid)
            if t['id'].startswith('promotion:'):
                t.update(priority=d['proposal']['proposal']['priority'],risk=d['risk'])
            attach(t,'discovery',pid,proposals[pid])
            t.update(state=state,required_action=action)
        except (ValueError,KeyError,TypeError,IndexError):
            block(t,'Promotion evidence disagreement or unsupported history')
    for pid in promoted_proposals:
        tasks.pop('proposal:'+pid,None)
    seen = set()
    for identity, r in runs.items():
        spec = r.get('spec',{}); tid = spec.get('task_id')
        t = tasks.get(tid)
        if t is None:
            t = task('execution:'+identity,REPOSITORIES_SAFE.get(spec.get('repo')),spec.get('issue'))
            tasks[t['id']] = t
        attach(t,'execution',identity,r)
        try:
            evidence.require(spec.get('protocol') == 'local-catalog-v1' and tid in specs,
                             'Historical or unsupported execution protocol requires manual inspection')
            evidence.require(tid not in seen,'Multiple executions claim one catalog task');seen.add(tid)
            state, action = evidence.run_state(r,specs[tid],policy,now)
            t.update(state=state,required_action=action)
            if state == 'awaiting-publication-review':t['usage']=r['usage'];t['qa_validated']=True
            related = [p for p in pubs.values() if p['run'] == identity]
            evidence.require(len(related) <= 1, 'Duplicate publications')
            for p in related:
                attach(t,'publication',p['id'],p)
                evidence.require(state == 'awaiting-publication-review','Publication without validated QA')
                def observe(repository, branch, number):
                    observation = remote(repository, branch, number)
                    attach(t,'github',p['id'],observation)
                    return observation
                state, action = evidence.publication_state(p,r,now,observe if remote is not None else None)
                t.update(state=state,required_action=action)
        except (OSError,ValueError,KeyError,TypeError,IndexError):
            block(t,'Execution/QA/publication evidence disagreement; legacy records retained unresolved')
    for identity,p in pubs.items():
        if p['run'] not in runs:
            t=task('publication:'+identity);tasks[t['id']]=t
            attach(t,'publication',identity,p);block(t,'Publication has no authoritative execution')
    stopped = any(Path(p).exists() or Path(p).is_symlink() for p in [*c['stop_files'],
                       *([str(Path(policy['state'])/'STOP')] if policy else [])])
    for name,path in sources.items():
        try:
            if before.get(name) != fingerprint(path):errors.append(name+': evidence changed during reconciliation; sync again manually')
        except (OSError,ValueError):errors.append(name+': evidence unavailable after reconciliation')
    if stopped: errors.append('STOP active; inspect operator STOP locations; no dispatch or automatic reset')
    if not tasks and errors:tasks['sources']=task('sources')
    for t in tasks.values():
        for reason in errors:block(t,reason)
        if t['blockers']:block(t,t['blockers'][0])
        t['evidence'].sort()
    return dict(protocol=PROTOCOL, configuration_digest=evidence.digest(c), advisory_only=True, execution_performed=False,
                errors=sorted(set(errors)), stopped=stopped, active_claims=sum(r.get('state') == 'running' for r in runs.values()),
                tasks=sorted(tasks.values(),key=lambda t:(-t['priority'],t['repository'] or '',str(t['issue']),t['id']))), observations


REPOSITORIES_SAFE = evidence.REPOSITORIES


def queue(view, offset=0, limit=50):
    evidence.require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= 100, 'Invalid pagination')
    rows = [t for t in view['tasks'] if t['state'] != 'running']
    return dict(total=len(rows),offset=offset,limit=limit,next_offset=offset+limit if offset+limit < len(rows) else None,
                items=rows[offset:offset+limit])


def preview(view, c):
    selected, skipped = [], []
    running = [t for t in view['tasks'] if t['state'] in ('running','interrupted')]
    occupied = {t['repository'] for t in running}
    # Complete QA does not prove dependency completion/merge. Dependencies remain blocked
    # until a future approved authoritative completion adapter exists.
    for t in view['tasks']:
        reasons = []
        if t['state'] not in ('reviewed-catalog-task','awaiting-coding-approval','approved-for-coding') or t['blockers']:
            reasons.append('not a reviewed eligible coding task')
        if t['risk'] not in ('low','medium'):reasons.append('high or unknown risk requires operator review')
        if t['depends_on']:reasons.append('dependency completion not verified; manual reconciliation required')
        if t['repository'] in occupied:reasons.append('candidate repository conflict')
        if view.get('active_claims',0):reasons.append('one active worker ceiling occupied')
        if len(selected) >= c['planning']['max_recommendations']:reasons.append('recommendation bound')
        if view['errors'] or view['stopped']:reasons.append('STOP or unresolved source evidence')
        if reasons:
            skipped.append(dict(id=t['id'],reasons=reasons));continue
        selected.append(dict(id=t['id'],repository=t['repository'],priority=t['priority'],risk=t['risk'],
                             authorization='existing coding approval' if t['state']=='approved-for-coding' else 'separate coding approval required',
                             estimated_cost='unknown',execution_authorized_by_preview=False))
        occupied.add(t['repository'])
    return dict(advisory_only=True,future_capacity=c['planning']['future_capacity'],max_active_workers=1,
                active_claims=view.get('active_claims',0), execution_order='sequential-only', selected=selected, skipped=skipped,
                usage_policy='Subscription usage is not a hard API-dollar spending guarantee', execution_performed=False)


def report(view):
    return dict(protocol=PROTOCOL, historical_only=True, states=dict(sorted(Counter(t['state'] for t in view['tasks']).items())),
                tasks=len(view['tasks']), blocked=sum(bool(t['blockers']) for t in view['tasks']),
                qa_validations=sum(t['qa_validated'] for t in view['tasks']),
                resource_usage=dict(records=sum(t['usage'] is not None for t in view['tasks']),
                    **{key:sum(t['usage'].get(key,0) for t in view['tasks'] if t['usage'] is not None)
                       for key in ('input_tokens','cached_input_tokens','output_tokens')}),
                pending_human_decisions=len([t for t in view['tasks'] if t['state'] != 'running']),
                errors=view['errors'], stopped=view['stopped'],execution_performed=False)


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only operational orchestration; all source actions remain separate')
    p.add_argument('command',choices=sorted(COMMANDS));p.add_argument('task_id',nargs='?')
    p.add_argument('--config',required=True);p.add_argument('--limit',type=int,default=50)
    p.add_argument('--offset',type=int,default=0);p.add_argument('--format',choices=('json','text'),default='json')
    args=p.parse_args(argv)
    try:
        c=config(args.config);ledger=Ledger(c['ledger'])
        if args.command=='init':
            policy,_,_=evidence.catalog(c['policy'])
            roots=[Path(policy['scratch']).resolve(),*[Path(r['source']).resolve() for r in policy['repositories'].values()]]
            evidence.require(not any(Path(c['ledger']).resolve().is_relative_to(root) for root in roots), 'Unsafe ledger destination')
            ledger.initialize();out=dict(initialized=True,protocol=PROTOCOL)
        elif args.command in ('sync','preview'):
            now=time.time();view,observations=reconcile(c,now)
            if args.command=='sync':out=dict(snapshot=ledger.save(view,observations,now),**report(view))
            else:out=preview(view,c)
        else:
            view=ledger.latest()
            if args.command=='queue':out=dict(observed_at=view['observed_at'],historical_only=True,**queue(view,args.offset,args.limit))
            elif args.command=='inspect':
                matches=[t for t in view['tasks'] if t['id']==args.task_id]
                evidence.require(len(matches)==1,'Unknown task');out=dict(observed_at=view['observed_at'],historical_only=True,**matches[0])
            else:out=dict(observed_at=view['observed_at'],snapshot=view['snapshot'],**report(view))
        if args.format=='json':print(json.dumps(out,indent=2,ensure_ascii=True))
        else:
            # JSON escaping keeps untrusted text from becoming terminal control sequences.
            for key,value in out.items():print(key+': '+json.dumps(value,sort_keys=True,ensure_ascii=True))
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        p.exit(1,'Orchestration failed closed; inspect configuration and protected source evidence.\n')


def coordinator_observations(config):
    """Optional v1 read-only coordinator evidence; never a dispatch/approval adapter.

    Existing orchestration configuration, snapshots and historical hashes stay v1.
    Operators must explicitly provide the separate reviewed coordinator config.
    """
    from src.concurrency_coordinator import observations
    return observations(config)
