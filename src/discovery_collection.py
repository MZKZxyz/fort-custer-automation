"""Bounded public GitHub GET collection. No credential or write interface."""
import json
import re
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORIES = frozenset({'MZKZxyz/fort-custer-server', 'MZKZxyz/fort-custer-client'})
MAX_BYTES = 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decode(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError('Oversized or invalid provider response')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (UnicodeError, RecursionError, ValueError):
        raise ValueError('Malformed provider JSON') from None


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value):
        raise ValueError('Invalid UTC timestamp')
    datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    return value


class RateLimited(ValueError):
    """Stop this invocation; retain checkpoint. Operator retries later."""


class Missing(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicGitHub:
    """Anonymous public reads only; never reads environment tokens or credential files."""
    def __init__(self):
        self._opener = build_opener(NoRedirect)

    def get(self, repository, resource, query=None):
        if repository not in REPOSITORIES:
            raise ValueError('Unsupported repository')
        if not isinstance(resource, str) or not re.fullmatch(
                r'(issues|issues/[1-9][0-9]*|issues/[1-9][0-9]*/comments|commits/main)', resource):
            raise ValueError('Unsupported read resource')
        query = query or {}
        allowed = {'state', 'sort', 'direction', 'per_page', 'page', 'since'} if resource == 'issues' else (
            {'per_page', 'page'} if resource.endswith('/comments') else set())
        if not isinstance(query, dict) or not set(query) <= allowed:
            raise ValueError('Unsupported read parameters')
        for key in ('page', 'per_page'):
            if key in query and (type(query[key]) is not int or not 1 <= query[key] <= 100):
                raise ValueError('Invalid pagination')
        if any(key in query and query[key] != val for key, val in
               [('state', 'open'), ('sort', 'updated'), ('direction', 'asc')]):
            raise ValueError('Unsupported issue selection')
        if 'since' in query:
            timestamp(query['since'])
        url = 'https://api.github.com/repos/' + repository + '/' + resource
        if query:
            url += '?' + urlencode(query)
        request = Request(url, method='GET', headers={
            'Accept': 'application/vnd.github+json', 'User-Agent': 'fort-custer-discovery',
            'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self._opener.open(request, timeout=15) as response:
                raw = response.read(MAX_BYTES + 1)
        except HTTPError as error:
            if error.code in (403, 429):
                raise RateLimited('GitHub rate/access limit; retry later; checkpoint retained') from None
            if error.code in (404, 410):
                raise Missing('Issue unavailable') from None
            raise ValueError('GitHub read failed') from None
        except OSError:
            raise ValueError('GitHub read failed') from None
        return decode(raw)


def positive(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError('Invalid provider identity')
    return value


def text(value, limit):
    if not isinstance(value, str) or len(value.encode('utf-8')) > limit:
        raise ValueError('Invalid or oversized evidence text')
    return value


def issue_snapshot(repository, issue, number=None):
    if not isinstance(issue, dict):
        raise ValueError('Invalid issue schema')
    n = positive(issue.get('number'))
    if number is not None and n != number:
        raise ValueError('Issue identity mismatch')
    base = 'https://api.github.com/repos/' + repository
    if (issue.get('url') != base + '/issues/' + str(n) or
        issue.get('repository_url') != base or
        issue.get('html_url') != 'https://github.com/' + repository + '/issues/' + str(n)):
        raise ValueError('Forged repository or issue identity')
    positive(issue.get('id'))
    if 'pull_request' in issue:
        return None
    if issue.get('state') not in ('open', 'closed'):
        raise ValueError('Invalid issue state')
    labels = issue.get('labels')
    if not isinstance(labels, list) or len(labels) > 100:
        raise ValueError('Invalid labels')
    names = []
    for label in labels:
        if not isinstance(label, dict):
            raise ValueError('Invalid label')
        names.append(text(label.get('name'), 200))
    if len(set(names)) != len(names):
        raise ValueError('Duplicate label evidence')
    count = issue.get('comments')
    if type(count) is not int or not 0 <= count <= 100000:
        raise ValueError('Invalid comment count')
    result = {key: issue[key] for key in ('id', 'number', 'state', 'url', 'html_url', 'repository_url')}
    result.update(title=text(issue.get('title'), 4096), body=text('' if issue.get('body') is None else issue['body'], 65536),
                  created_at=timestamp(issue.get('created_at')), updated_at=timestamp(issue.get('updated_at')),
                  labels=sorted(names), comment_count=count)
    if result['created_at'] > result['updated_at']:
        raise ValueError('Invalid issue chronology')
    return result


class Collector:
    def __init__(self, transport, config, guard):
        self.transport, self.config, self.guard = transport, config, guard
        self.requests = 0

    def read(self, repo, resource, query=None):
        self.guard()
        if repo not in self.config['repositories']:
            raise ValueError('Repository outside operator scope')
        self.requests += 1
        if self.requests > self.config['max_requests']:
            raise ValueError('Discovery request limit reached')
        value = self.transport.get(repo, resource, query)
        if len(canonical(value).encode()) > MAX_BYTES:
            raise ValueError('Oversized provider response')
        self.guard()
        return value

    def pages(self, repo, resource, query=None):
        result = []
        for page in range(1, self.config['max_pages'] + 1):
            rows = self.read(repo, resource, dict(query or {}, per_page=self.config['page_size'], page=page))
            if not isinstance(rows, list) or len(rows) > self.config['page_size']:
                raise ValueError('Invalid provider page')
            result.extend(rows)
            if len(rows) < self.config['page_size']:
                return result
        raise ValueError('Pagination bound reached; incomplete scan discarded')

    def collect(self, repo, since, known):
        commit = self.read(repo, 'commits/main')
        if (not isinstance(commit, dict) or not isinstance(commit.get('sha'), str) or
            not re.fullmatch(r'[0-9a-f]{40}', commit['sha']) or
            commit.get('html_url') != 'https://github.com/' + repo + '/commit/' + commit['sha']):
            raise ValueError('Invalid source commit identity')
        query = dict(state='open', sort='updated', direction='asc')
        if since:
            query['since'] = timestamp(since)
        listed, numbers = {}, set(known)
        for row in self.pages(repo, 'issues', query):
            snapshot = issue_snapshot(repo, row)
            if snapshot is None:
                continue
            n = snapshot['number']
            if n in listed:
                raise ValueError('Duplicate or conflicting issue evidence')
            listed[n] = snapshot
            numbers.add(n)
        if len(numbers) > self.config['max_issues']:
            raise ValueError('Issue bound reached')
        evidence = []
        for number in sorted(numbers):
            try:
                detail = issue_snapshot(repo, self.read(repo, 'issues/' + str(number)), number)
            except Missing:
                evidence.append(dict(repository=repo, number=number, availability='unavailable', source_commit=commit['sha']))
                continue
            if detail is None:
                continue
            comments = []
            ids = set()
            if detail['comment_count']:
                for comment in self.pages(repo, 'issues/' + str(number) + '/comments'):
                    if not isinstance(comment, dict):
                        raise ValueError('Invalid comment')
                    identity = positive(comment.get('id'))
                    if (identity in ids or comment.get('issue_url') != detail['url'] or
                        comment.get('html_url') != detail['html_url'] + '#issuecomment-' + str(identity)):
                        raise ValueError('Duplicate or forged comment evidence')
                    ids.add(identity)
                    if timestamp(comment.get('created_at')) > timestamp(comment.get('updated_at')):
                        raise ValueError('Invalid comment chronology')
                    comments.append(dict(id=identity, body=text(comment.get('body'), 65536),
                                         created_at=timestamp(comment.get('created_at')),
                                         updated_at=timestamp(comment.get('updated_at')),
                                         html_url=comment['html_url']))
            # Re-read to reject a moving issue/comment count during collection.
            final = issue_snapshot(repo, self.read(repo, 'issues/' + str(number)), number)
            if final != detail or len(comments) != detail['comment_count']:
                raise ValueError('Issue changed during collection; retry later')
            evidence.append(dict(repository=repo, number=number, availability='present',
                                 issue=detail, comments=sorted(comments, key=lambda c:c['id']),
                                 source_commit=commit['sha']))
        return evidence
