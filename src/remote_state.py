"""CAS storage for the planning ledger only; never writes backlog issues."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener
from issues import NoRedirect

BRANCH = 'automation-planning-state'
FILE = 'planning.db'


def api(method, path, token, data=None):
    request = Request('https://api.github.com/' + path,
                      data=json.dumps(data).encode() if data is not None else None,
                      headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                               'Content-Type': 'application/json', 'User-Agent': 'fort-custer-state',
                               'X-GitHub-Api-Version': '2022-11-28'}, method=method)
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        return json.load(response)


def restore(db, repo, token, initialize=False, base_sha=None, request=api):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo) or not token:
        raise ValueError('State credential and repository required')
    if Path(db).exists():
        raise ValueError('Refusing to replace local state')
    prefix = f'repos/{repo}'
    # A missing branch may be bootstrapped only by explicit manual input.
    try:
        request('GET', f'{prefix}/git/ref/heads/{BRANCH}', token)
    except HTTPError as error:
        if error.code != 404 or not initialize or not base_sha:
            raise ValueError('Persistent state branch unavailable') from None
        request('POST', f'{prefix}/git/refs', token,
                {'ref': f'refs/heads/{BRANCH}', 'sha': base_sha})
    try:
        result = request('GET', f'{prefix}/contents/{FILE}?ref={BRANCH}', token)
    except HTTPError as error:
        if error.code != 404 or not initialize:
            raise ValueError('Persistent ledger unavailable') from None
        from planning import initialize as create
        create(db)
        return None
    if initialize:
        raise ValueError('Cannot initialize existing remote ledger')
    if result.get('encoding') != 'base64' or not re.fullmatch(r'[0-9a-f]{40}', result.get('sha', '')):
        raise ValueError('Invalid remote state response')
    content = base64.b64decode(result['content'].replace('\n', ''), validate=True)
    if not content.startswith(b'SQLite format 3\x00'):
        raise ValueError('Invalid ledger format')
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    Path(db).write_bytes(content)
    return result['sha']


def save(db, repo, token, sha, request=api):
    payload = {'message': 'Persist advisory planning ledger', 'branch': BRANCH,
               'content': base64.b64encode(Path(db).read_bytes()).decode()}
    if sha:
        payload['sha'] = sha
    # GitHub rejects a stale contents SHA (409). No retries or overwrite fallback.
    request('PUT', f'repos/{repo}/contents/{FILE}', token, payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['restore', 'save'])
    parser.add_argument('--db', required=True)
    parser.add_argument('--sha-file', required=True)
    parser.add_argument('--initialize', action='store_true')
    args = parser.parse_args()
    repo, token = os.environ['GITHUB_REPOSITORY'], os.environ['STATE_TOKEN']
    if args.operation == 'restore':
        sha = restore(args.db, repo, token, args.initialize, os.environ.get('GITHUB_SHA'))
        Path(args.sha_file).write_text(sha or '')
    else:
        save(args.db, repo, token, Path(args.sha_file).read_text() or None)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Persistent state operation failed closed; verify state and Contents permissions.') from None
