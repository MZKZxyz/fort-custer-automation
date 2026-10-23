"""Read-only subsystem projections. No runner or publisher objects are constructed.

Files and controller-authored SQLite records require operator OS protection.
Hashes bind observations; they are not human signatures.
"""
import contextlib
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from src.catalog_promotion import intake, regular, read_policy
from src.issue_discovery import Store
from src.local_catalog import resolve, REPOSITORIES

LIMIT = 10000
MAX_DOCUMENT = 16 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    require(len(raw) <= MAX_DOCUMENT, 'Evidence document exceeds bound')
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def sha(value, size=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % size, value) is not None


@contextlib.contextmanager
def readonly(path, tables, protocol=None):
    path = regular(path)
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=5)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('BEGIN')
        actual = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require(actual == set(tables), 'Unsupported source schema')
        if protocol:
            require(db.execute('SELECT schema FROM metadata').fetchall() == [(protocol,)],
                    'Unsupported source protocol')
        require(db.execute('PRAGMA quick_check').fetchone() == ('ok',), 'Source integrity failure')
        yield db
    finally:
        db.close()


def bounded(db, sql):
    rows = db.execute(sql).fetchmany(LIMIT+1)
    require(len(rows) <= LIMIT, 'Source row bound exceeded')
    return rows


def catalog(path):
    policy, revision = read_policy(path)
    require(len(policy['catalog']['tasks']) <= LIMIT, 'Catalog bound exceeded')
    return policy, revision, {i:resolve(policy, i)[0] for i in sorted(policy['catalog']['tasks'])}


def discovery(path):
    # Reuse the established deterministic validation, always explicitly offline.
    with readonly(path, {'metadata','snapshots','proposals','events','checkpoints'}, 'discovery-store-v1') as db:
        for table in ('snapshots', 'events'):
            require(db.execute('SELECT count(*) FROM '+table).fetchone()[0] <= LIMIT,
                    'Discovery evidence bound exceeded')
        ids = [r[0] for r in bounded(db, 'SELECT id FROM proposals ORDER BY id')]
    store = Store(path)
    return {i:intake(store, i, network=False) for i in ids}


def promotions(path):
    with readonly(path, {'metadata','events'}, 'catalog-promotion-v1') as db:
        rows = bounded(db, 'SELECT seq,id,kind,at,document FROM events ORDER BY seq')
    grouped = {}
    for seq, identity, kind, at, raw in rows:
        require(finite(at), 'Invalid promotion timestamp')
        grouped.setdefault(identity, []).append(dict(seq=seq, kind=kind, at=at, document=decode(raw)))
    return grouped


def executions(path):
    # The legacy database has no metadata version. Accept only its two known layouts.
    path = regular(path)
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    require(tables in ({'runs'}, {'runs','publications','publication_events'}), 'Unknown execution schema')
    with readonly(path, tables) as db:
        runs = {}
        for identity, raw in bounded(db, 'SELECT id,document FROM runs ORDER BY id'):
            r = decode(raw)
            require(r['id'] == identity and sha(identity,32), 'Execution identity mismatch')
            runs[identity] = r
        pubs = {}
        if 'publications' in tables:
            events = bounded(db, 'SELECT publication,event,at,actor FROM publication_events ORDER BY sequence')
            for identity, run, request, binding, status, result in bounded(db, 'SELECT * FROM publications ORDER BY id'):
                pubs[identity] = dict(id=identity, run=run, request=decode(request), binding=binding,
                    status=status, result=decode(result), history=[dict(event=e, at=t, actor=a)
                        for p,e,t,a in events if p == identity])
            require(all(p in pubs for p,_,_,_ in events), 'Orphan publication events')
    return runs, pubs


def run_state(r, spec, policy, now):
    require(r['spec'] == spec and digest(spec) == r['binding'], 'Execution specification/binding changed')
    state = r['state']; h = r['history']; events = [x['event'] for x in h]
    sequences = {'pending':['prepared'], 'approved':['prepared','approved'],
        'running':['prepared','approved','claimed'],
        'validated':['prepared','approved','claimed','validated'],
        'failed':['prepared','approved','claimed','failed']}
    require(state in sequences and events == sequences[state], 'Unsupported execution history')
    times = [x['at'] for x in h]
    require(all(finite(t) for t in times) and times == sorted(times) and times[-1] <= now,
            'Invalid execution chronology')
    require(finite(r['expires']) and times[0] < r['expires'] <= times[0]+600, 'Invalid execution expiry')
    if len(h) > 1:
        require(h[1].get('binding') == r['binding'] and times[1] < r['expires'], 'Missing coding authorization')
    if len(h) > 2:
        require(times[2] < r['expires'] and finite(r['deadline']) and
                times[2] < r['deadline'] <= times[2]+spec['limits']['timeout_seconds'], 'Invalid execution claim')
    if state in ('pending','approved') and r['expires'] <= now:
        return 'expired', 'Coding authorization expired; inspect with src.local_runner; reconcile the single-use task manually'
    if state == 'pending':
        return 'awaiting-coding-approval', 'Review and approve separately with src.local_runner approve'
    if state == 'approved':
        return 'approved-for-coding', 'Operator may separately invoke src.local_runner execute after policy review'
    if state == 'running':
        if now >= r['deadline']:
            return 'interrupted', 'Durable worker claim exceeded deadline; inspect STOP, process and ledger manually; never retry automatically'
        return 'running', 'Observe existing worker; no new worker may start'
    if state == 'failed':
        require(isinstance(r.get('error'),str), 'Missing controller failure evidence')
        return ('cancelled' if r['error'] == 'cancelled' else 'rejected'), 'Inspect src.local_runner evidence and independent QA; manually reconcile before any new task'
    require(times[-1] < r['deadline'], 'Validation after deadline')
    usage = r.get('usage')
    require(isinstance(usage,dict) and {'input_tokens','cached_input_tokens','output_tokens'} <= usage.keys()
            and all(type(v) is int and v >= 0 for v in usage.values()), 'Missing resource usage evidence')
    qa = r.get('qa'); checks = spec['checks']
    require(isinstance(qa,list) and [q['name'] for q in qa] == ['diff', *[c['name'] for c in checks], 'candidate'],
            'Missing independent QA evidence')
    require(all(type(q['code']) is int and q['code'] == 0 and q['reason'] is None for q in qa), 'Failed independent QA')
    commands = [['/usr/bin/git','diff','--check','HEAD^','HEAD']]+[[policy['node'], *c['argv'][1:]] for c in checks]
    require([q['command'] for q in qa[:-1]] == commands and
            all(isinstance(q.get(k),str) for q in qa[:-1] for k in ('stdout','stderr')), 'QA command mismatch')
    a = qa[-1]
    require(a['input_hash'] == spec['input_hash'] and a['candidate_hash'] == r['candidate_hash'] and
            sha(r['candidate_hash']) and sha(a['candidate_tree'],40) and sha(a['candidate_revision'],40) and
            isinstance(a['patch'],str) and 0 < len(a['patch'].encode()) <= 8*1024*1024 and
            isinstance(r['files'],list) and bool(r['files']) and len(set(r['files'])) == len(r['files']) and
            set(r['files']) <= set(spec['allowed']), 'Candidate QA binding mismatch')
    return 'awaiting-publication-review', 'Controller QA validated; separately prepare/review with src.catalog_publication; publisher must reconstruct the candidate'


def publication_state(p, r, now, remote=None):
    q = p['request']
    require(q.get('protocol') == 'catalog-draft-v1' and r['spec'].get('protocol') == 'local-catalog-v1',
            'Unsupported publication protocol; inspect historical publisher separately')
    require(p['id'] == digest(dict(protocol='catalog-draft-v1',run=r['id'])), 'Publication identity mismatch')
    require(p['run'] == r['id'] == q['run'] and digest(q) == p['binding'] and
            q['spec'] == r['spec'] and q['artifact'] == digest(r) and
            q['qa'] == digest(r['qa']) and q['approval'] == digest(r['history']) and
            q['input_hash'] == r['spec']['input_hash'] and q['candidate_hash'] == r['candidate_hash'] and
            q['tree'] == r['qa'][-1]['candidate_tree'] and q['files'] == r['files'] and
            q['base'] == r['spec']['source'] and q['base_branch'] == r['spec']['branch'] and
            q['draft'] is True and q['action'] == 'create-new-branch-and-draft-pr' and sha(q['commit'],40),
            'Publication artifact mismatch')
    repository = REPOSITORIES[r['spec']['repo']]
    require(q.get('repository',repository) == repository, 'Publication repository mismatch')
    require(q['branch'] == 'codex/catalog-'+r['id'] and
            q['title'] == 'Reviewed catalog task: '+r['spec']['task_id'] and
            q['author'] == dict(name='Fort Custer Publisher',email='publisher@fort-custer.local',date='2026-10-22T00:00:00Z') and
            q['message'] == q['title']+'\n\nExecution evidence: '+digest(r)+'\n', 'Publication action changed')
    raw = (f"tree {q['tree']}\nparent {q['base']}\nauthor {q['author']['name']} <{q['author']['email']}> 1792627200 +0000\n"
           f"committer {q['author']['name']} <{q['author']['email']}> 1792627200 +0000\n\n"+q['message']).encode()
    require(hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == q['commit'],
            'Publication commit identity mismatch')
    h = p['history']; events = [x['event'] for x in h if x['event'] != 'remote-preflight']
    sequence = ['prepared','approved','publishing','branch-requested','pr-requested','completed']
    status = p['status']
    if status == 'cancelled':
        require(events[-1:] == ['cancelled'] and events[:-1] in (['prepared'], ['prepared','approved']), 'Invalid cancellation history')
    else:
        require(status in sequence and events == sequence[:sequence.index(status)+1], 'Publication history mismatch')
    times = [x['at'] for x in h]
    require(times and all(finite(t) for t in times) and times == sorted(times) and times[-1] <= now and
            all(x['actor'] == q['operator'] for x in h) and finite(q['expires']) and
            times[0] < q['expires'] <= times[0]+600 and
            all(x['at'] < q['expires'] for x in h if x['event'] not in ('completed','cancelled')), 'Publication chronology mismatch')
    if status == 'cancelled':
        return 'cancelled', 'Inspect publication cancellation; no automatic retry'
    if status in ('publishing','branch-requested','pr-requested'):
        return 'ambiguous-publication', 'Use existing publisher inspect/remote-inspect and manual provider reconciliation; never replay publication'
    if status == 'completed':
        result = p['result']
        require(result.get('commit') == q['commit'] and result.get('tree') == q['tree'] and
                result.get('branch') == q['branch'] and type(result.get('number')) is int and result['number'] > 0 and
                result.get('url') == 'https://github.com/'+repository+'/pull/'+str(result['number']), 'Missing completed publication result')
        if remote is None:
            return 'published-draft-recorded', 'Draft publication recorded locally; current GitHub state unknown; manually verify before merge'
        # The capability is a read-only injected observation callable, never publisher transport.
        observation = remote(repository, q['branch'], result['number'])
        require(observation['repository'] == repository and observation['base'] == q['base'] and
                observation['head'] == q['commit'] and len(observation['prs']) == 1, 'GitHub branch conflict')
        pr = observation['prs'][0]
        require(pr['number'] == result['number'] and pr['html_url'] == result['url'] and
                pr['state'] == 'open' and pr['draft'] is True and not pr.get('merged_at') and not pr.get('auto_merge') and
                pr['head']['sha'] == q['commit'] and pr['head']['ref'] == q['branch'] and
                pr['head']['repo']['full_name'] == repository and pr['base']['sha'] == q['base'] and
                pr['base']['ref'] == q['base_branch'] and pr['base']['repo']['full_name'] == repository and
                pr['title'] == q['title'] and pr['body'] == q['body'] and pr.get('maintainer_can_modify') is False,
                'GitHub PR changed or conflicted')
        return 'awaiting-human-merge', 'Verified draft PR requires human review and manual merge; no merge authority'
    if q['expires'] <= now:
        return 'expired', 'Publication authorization expired; use existing publisher inspection and manual recovery'
    return 'awaiting-publication-review', 'Separately review/authorize publication with the existing publisher CLI'
