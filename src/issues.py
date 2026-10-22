"""Read-only GitHub backlog adapter. Issue text is data, never instructions."""
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_page(url, token=None):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'fort-custer-planner',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    with build_opener(NoRedirect).open(Request(url, headers=headers, method='GET'), timeout=30) as response:
        return json.load(response)


def parse_issue(repo, issue):
    """Require structured metadata; invalid issues go to human review."""
    metadata = json.loads(issue.get('body') or '')
    if not isinstance(metadata, dict) or set(metadata) != {'area', 'priority', 'estimated_usd', 'depends_on'}:
        raise ValueError('Issue body must contain exactly area, priority, estimated_usd, depends_on')
    area, priority, estimate, deps = (metadata[k] for k in ('area', 'priority', 'estimated_usd', 'depends_on'))
    if not isinstance(area, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,120}', area):
        raise ValueError('Invalid area')
    if any(part in ('', '.', '..') for part in area.split('/')):
        raise ValueError('Invalid area')
    if type(priority) is not int or not 0 <= priority <= 100:
        raise ValueError('Invalid priority')
    if type(estimate) not in (int, float) or not math.isfinite(estimate) or estimate <= 0:
        raise ValueError('Invalid estimate')
    if not isinstance(deps, list) or any(not isinstance(d, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+#[1-9][0-9]*', d) for d in deps):
        raise ValueError('Invalid dependencies')
    return dict(metadata, id=f"{repo}#{issue['number']}", repo=repo, risk='L3',
                title=''.join(c for c in str(issue.get('title', '')) if c.isprintable())[:240])


def ingest(settings, token=None, fetch=fetch_page, policy=None):
    if not token:
        raise ValueError('GitHub read credential required')
    if policy is None:
        from orchestrator import ROOT, read_json
        policy = read_json(ROOT / 'config/policy.json')
    tasks, seen = [], set()
    label = settings['planning']['github']['eligible_label']
    for repo in settings['repositories']:
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
            raise ValueError('Invalid configured repository')
        # Deliberately read ALL open issues, including those awaiting approval.
        for page in range(1, 1001):
            query = urlencode({'state': 'open', 'per_page': 100, 'page': page})
            try:
                issues = fetch(f'https://api.github.com/repos/{repo}/issues?{query}', token)
            except Exception:
                # Never include response bodies, headers or credentials in diagnostics.
                raise OSError('GitHub read failed; verify Issues read permission and API availability') from None
            if not isinstance(issues, list) or len(issues) > 100:
                raise ValueError('Invalid GitHub response')
            for issue in issues:
                if not isinstance(issue, dict):
                    raise ValueError('Invalid GitHub issue')
                if 'pull_request' in issue:
                    continue
                number = issue.get('number')
                if type(number) is not int or number <= 0 or issue.get('state') != 'open':
                    raise ValueError('Invalid open issue identity')
                identity = f'{repo}#{number}'
                if identity in seen:
                    raise ValueError('Duplicate issue in paginated response')
                seen.add(identity)
                labels = issue.get('labels')
                if not isinstance(labels, list) or any(not isinstance(x, dict) or not isinstance(x.get('name'), str) for x in labels):
                    raise ValueError('Invalid issue labels')
                labels = {x['name'] for x in labels}
                reasons = []
                try:
                    task = parse_issue(repo, issue)
                except (ValueError, TypeError, KeyError):
                    task = dict(id=identity, repo=repo, title=str(issue.get('title', ''))[:240],
                                risk=policy['default_risk'])
                    reasons.append('invalid or missing structured metadata')
                risks = labels & set(policy['risk_levels'])
                task['risk'] = next(iter(risks)) if len(risks) == 1 else policy['default_risk']
                if label not in labels:
                    reasons.append('missing eligibility label')
                if task['risk'] not in ('L0', 'L1', 'L2'):
                    reasons.append('high or unverified risk requires approval')
                text = (str(issue.get('title', '')) + ' ' + str(issue.get('body', ''))).lower()
                if any(term.lower() in text for term in policy['sensitive_terms']):
                    reasons.append('sensitive policy term requires approval')
                    task['risk'] = 'L3'
                area = task.get('area', '')
                if any(area.startswith(path) or path.rstrip('/') in area for path in policy['always_human_review_paths']):
                    reasons.append('protected policy area requires approval')
                if labels & {'automation:approval-required', 'automation:blocked'}:
                    reasons.append('explicit approval or blocked label')
                task['review_reasons'] = reasons
                tasks.append(task)
            if len(issues) < 100:
                break
        else:
            raise ValueError('GitHub pagination limit exceeded')
    closed = set()
    for dependency in sorted({d for task in tasks for d in task.get('depends_on', [])}):
        repo, number = dependency.rsplit('#', 1)
        if repo not in settings['repositories']:
            continue
        try:
            issue = fetch(f'https://api.github.com/repos/{repo}/issues/{number}', token)
        except Exception:
            raise OSError('Dependency read failed; no plan created') from None
        if not isinstance(issue, dict) or issue.get('number') != int(number) or issue.get('state') not in ('open', 'closed') or 'pull_request' in issue:
            raise ValueError('Dependency state cannot be verified')
        if issue['state'] == 'closed':
            closed.add(dependency)
    for task in tasks:
        task['verified_closed_dependencies'] = sorted(set(task.get('depends_on', [])) & closed)
    return tasks
