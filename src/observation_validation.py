"""Read-only policy and discovery validation shared by manual and scheduled observers."""
import hashlib
import os
from pathlib import Path
import re
import stat
from src.discovery_analysis import digest, validate_proposal, DeterministicAnalyzer, proposal, WEIGHTS
from src.discovery_collection import decode, issue_snapshot, timestamp, PublicGitHub
from src.local_catalog import resolve, REPOSITORIES

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
        resolve(policy, task, observation_only=True)
    return policy, hashlib.sha256(raw).hexdigest()

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
