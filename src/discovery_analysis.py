"""Offline heuristic analysis; evidence is data and labels are unverified claims."""
import hashlib
import re
from src.discovery_collection import canonical, REPOSITORIES, timestamp

VERSION = 'deterministic-1'
CATEGORIES = ('bug', 'regression-tests', 'performance', 'reliability', 'security',
              'maintainability', 'observability', 'documentation')
# Operator-reviewed scoring policy. Signals describe reports, not verified defects.
WEIGHTS = dict(severity=20, user_impact=10, reproducibility=15, testing=10,
               dependency=5, evidence=10, complexity=-10, regression_risk=-10)
SCHEMA = 'discovery-proposal-v1'
FIELDS = {'schema', 'id', 'repository', 'issue_number', 'snapshot', 'problem', 'proposed_change',
          'evidence', 'candidate_paths', 'suggested_qa', 'risk', 'complexity', 'estimated_cost_usd',
          'priority', 'priority_rationale', 'source_commit', 'discovered_at', 'analysis_version',
          'trust', 'state', 'category', 'facts', 'hypotheses', 'policy_digest'}


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class DeterministicAnalyzer:
    version = VERSION

    def analyze(self, snapshot):
        issue = snapshot['issue']
        labels = set(issue['labels'])
        category = next((c for c in CATEGORIES if c in labels), 'maintainability')
        signals = dict(severity=int(bool(labels & {'critical', 'security'})),
                       user_impact=int('user-impact' in labels),
                       reproducibility=int('reproduced' in labels),
                       testing=int('tests-present' in labels),
                       dependency=int('blocks-other-work' in labels),
                       evidence=int(bool(issue['body'])),
                       complexity=int('large' in labels),
                       regression_risk=int(bool(labels & {'security', 'high-risk'})))
        return dict(category=category, signals=signals)


def proposal(snapshot, snapshot_id, at, config, analyzer):
    result = analyzer.analyze(snapshot)
    if (not isinstance(result, dict) or set(result) != {'category', 'signals'} or
        result['category'] not in CATEGORIES or not isinstance(result['signals'], dict) or
        set(result['signals']) != set(WEIGHTS) or
        any(type(v) is not int or v not in (0, 1) for v in result['signals'].values())):
        raise ValueError('Unsupported analyzer output')
    if analyzer.version != VERSION:
        raise ValueError('Unsupported analysis version')
    # Ranking is controller-owned; adapters cannot forge scoring evidence.
    if result != DeterministicAnalyzer().analyze(snapshot):
        raise ValueError('Unverified analyzer signals')
    signals = result['signals']
    parts = {k: signals[k] * config['weights'][k] for k in WEIGHTS}
    policy_digest = digest(config)
    identity = digest(dict(schema=SCHEMA, snapshot=snapshot_id, analysis=VERSION, policy=policy_digest))
    issue = snapshot['issue']
    p = dict(schema=SCHEMA, id=identity, repository=snapshot['repository'],
             issue_number=snapshot['number'], snapshot=snapshot_id,
             problem='Reported issue: ' + issue['title'],
             proposed_change='Independently reproduce and assess the reported ' + result['category'] +
                             ' concern; define a minimal change only after operator review.',
             evidence=[snapshot_id + '#issue'] + [snapshot_id + '#comment-' + str(c['id']) for c in snapshot['comments']],
             candidate_paths=[], suggested_qa=['Controller owner should select independent reproduction and regression checks.'],
             risk='high' if signals['regression_risk'] else 'unverified',
             complexity='large' if signals['complexity'] else 'unknown', estimated_cost_usd=None,
             priority=sum(parts.values()), priority_rationale=dict(signals=signals, weighted=parts,
                 limitation='Labels and text are reports; no defect, test coverage or dependency is independently verified.'),
             source_commit=snapshot['source_commit'], discovered_at=at, analysis_version=VERSION,
             trust='untrusted-proposal', state='proposed', category=result['category'],
             facts=['An open issue with this identity and content was observed at collection time.'],
             hypotheses=['The reported concern may require a coding change; reproduction and scope remain unverified.'],
             policy_digest=policy_digest)
    validate_proposal(p)
    return p


def validate_proposal(p):
    if (not isinstance(p, dict) or set(p) != FIELDS or p['schema'] != SCHEMA or
        p['trust'] != 'untrusted-proposal' or p['state'] != 'proposed' or
        p['analysis_version'] != VERSION or p['category'] not in CATEGORIES or
        type(p['priority']) is not int or p['estimated_cost_usd'] is not None or
        p['candidate_paths'] != []):
        raise ValueError('Unsupported proposal schema')
    for key in ('id', 'snapshot', 'policy_digest'):
        if not isinstance(p[key], str) or not re.fullmatch(r'[0-9a-f]{64}', p[key]):
            raise ValueError('Invalid proposal digest')
    if (not isinstance(p['repository'], str) or p['repository'] not in REPOSITORIES or
        type(p['issue_number']) is not int or p['issue_number'] <= 0 or
        not isinstance(p['source_commit'], str) or not re.fullmatch(r'[0-9a-f]{40}', p['source_commit']) or
        p['risk'] not in ('high', 'unverified') or p['complexity'] not in ('large', 'unknown')):
        raise ValueError('Invalid proposal provenance or assessment')
    timestamp(p['discovered_at'])
    for key in ('problem', 'proposed_change'):
        if not isinstance(p[key], str) or not 0 < len(p[key].encode()) <= 8192:
            raise ValueError('Invalid proposal text')
    for key in ('evidence', 'suggested_qa', 'facts', 'hypotheses'):
        values = p[key]
        if (not isinstance(values, list) or not values or len(values) > 10001 or
            any(not isinstance(v, str) or not 0 < len(v.encode()) <= 8192 for v in values) or
            len(set(values)) != len(values)):
            raise ValueError('Invalid advisory evidence list')
    if any(not re.fullmatch(p['snapshot'] + r'#(issue|comment-[1-9][0-9]*)', ref) for ref in p['evidence']):
        raise ValueError('Invalid evidence reference')
    rationale = p['priority_rationale']
    if (not isinstance(rationale, dict) or set(rationale) != {'signals', 'weighted', 'limitation'} or
        not isinstance(rationale['limitation'], str)):
        raise ValueError('Invalid priority rationale')
    for key in ('signals', 'weighted'):
        if (not isinstance(rationale[key], dict) or set(rationale[key]) != set(WEIGHTS) or
            any(type(v) is not int for v in rationale[key].values())):
            raise ValueError('Invalid scoring schema')
    if any(v not in (0, 1) for v in rationale['signals'].values()) or sum(rationale['weighted'].values()) != p['priority']:
        raise ValueError('Invalid priority score')
    return p
