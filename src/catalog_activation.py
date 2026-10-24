"""Read-only catalog activation review. Never initializes, approves or dispatches."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sqlite3
import subprocess

from src import orchestration_evidence as e, api_controller as api
from src.live_observation import ObservationBroker
from src.observation_planning import observation_prompt
from src.observation_validation import read_policy
from src.local_catalog import resolve
from src.source_observation import git, source_files, manifest


def separate(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    e.require(not a.is_relative_to(b) and not b.is_relative_to(a), 'Overlapping activation paths')


def destination(path):
    """Check even absent destinations without creating parents or following links."""
    path = Path(path)
    e.require(path.is_absolute() and '..' not in path.parts, 'Absolute normalized paths required')
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            continue
        s = item.lstat()
        e.require(not stat.S_ISLNK(s.st_mode), 'Symlink destination rejected')
        e.require(item == path or stat.S_ISDIR(s.st_mode), 'Destination ancestor must be a directory')
        e.require(s.st_uid in (Path('/').stat().st_uid, os.getuid()), 'Untrusted destination owner')
        e.require(not s.st_mode & 0o022 or
                  (item not in (path, path.parent) and s.st_mode & stat.S_ISVTX),
                  'Protected destination parent required')
    return path


def build(path):
    """Fill only an explicit UNREVIEWED manifest in a separately authored policy."""
    policy = e.decode(e.regular(path).read_bytes())
    tasks = policy['catalog']['tasks']
    e.require(len(tasks) == 1, 'Exactly one new task required')
    task = next(iter(tasks.values()))
    e.require(task['input_hash'] == 'UNREVIEWED', 'Refuse automatic manifest refresh')
    repo = policy['repositories'][task['repo']]
    e.require(git(repo['source'], 'rev-parse', 'HEAD').decode().strip() == task['source'] == repo['sha'],
              'Source HEAD/reviewed revision mismatch')
    task['input_hash'] = manifest(source_files(repo['source'], task['source'], task['allowed']))
    # Full validation is repeated against the saved final policy by preflight.
    resolve(policy, next(iter(tasks)), observation_only=True)
    return policy


def preflight(legacy_path, policy_path, broker_path, api_path):
    """No Runner, SQLite initialization, terminal prompt, key read or transport."""
    legacy_path, policy_path, broker_path, api_path = [e.regular(p) for p in
        (legacy_path, policy_path, broker_path, api_path)]
    legacy = e.decode(legacy_path.read_bytes())
    e.require('catalog' not in legacy and legacy.get('mode') == 'local_codex_development',
              'Expected separate legacy policy without catalog')
    policy, _ = read_policy(policy_path)
    e.require(policy['enabled'] is True and policy.get('cli_version') == '0.163.0' and
              len(policy['catalog']['tasks']) == 1,
              'One explicitly enabled reviewed task required')
    task_id = next(iter(policy['catalog']['tasks']))
    spec, _ = resolve(policy, task_id, observation_only=True)
    repo = policy['repositories'][spec['repo']]
    e.require(git(repo['source'], 'rev-parse', 'HEAD').decode().strip() == spec['source'],
              'Source HEAD/reviewed revision mismatch')
    api.observation_payload(observation_prompt({'spec': spec}))
    broker = ObservationBroker(e.decode(broker_path.read_bytes()))
    e.require(broker.c['enabled'], 'Observation configuration disabled')
    c, prices, budget = api.configuration(api_path)
    e.require(not c['connectivity_enabled'] and prices == api.DEFAULT_PRICING,
              'Unsupported API configuration')
    # Metadata only: never open credential contents or invoke the key helper.
    credential = e.regular(c['credential_file'])
    status = budget.status()
    maximum = api.maximum_charge(prices, api.OBSERVATION_OUTPUT)
    e.require(status['unresolved_requests'] == 0, 'Unresolved API reservation')
    e.require(status['daily_encumbered_nano_usd']+maximum <= status['daily_limit_nano_usd'] and
              status['lifetime_encumbered_nano_usd']+maximum <= status['lifetime_limit_nano_usd'],
              'Insufficient observation budget')
    old_state, old_scratch = Path(legacy['state']), Path(legacy['scratch'])
    e.regular(old_state/'local.sqlite')  # No history is parsed or reinterpreted.
    state, scratch = Path(policy['state']), Path(policy['scratch'])
    roots = [state, scratch, Path(broker.c['scratch'])]
    new_files = [policy_path, broker_path, broker.path]
    old = [legacy_path, old_state, old_scratch, Path(legacy['operator_home']),
           Path(policy['operator_home']), api_path, budget.path, credential,
           Path(__file__).resolve().parents[1],
           *[Path(r['source']) for r in legacy['repositories'].values()],
           *[Path(r['source']) for r in policy['repositories'].values()]]
    for p in [*roots, *new_files]:
        destination(p)
        for q in old:
            separate(p, q)
    for i, p in enumerate([*roots, *new_files]):
        for q in [*roots, *new_files][i+1:]:
            separate(p, q)
    for p in roots:
        e.require(not os.path.lexists(p) or p.is_dir() and not any(p.iterdir()),
                  'New state/scratch must be absent or empty; preserve existing state')
    e.require(not os.path.lexists(broker.path), 'Observation ledger already exists; preserve it')
    stops = {str(old_state/'STOP'), str(state/'STOP')}
    e.require(stops <= set(broker.c['stop_files']), 'Both legacy and catalog STOP paths required')
    for p in broker.c['stop_files']:
        destination(p)
        e.require(not os.path.lexists(p), 'STOP condition present; never remove automatically')
        for root in [scratch, Path(broker.c['scratch'])]:
            separate(p, root)
    # Check pinned prerequisites without running either binary, a worker or QA.
    for name in ('node', 'cli'):
        binary = Path(policy[name])
        e.require(binary.is_absolute() and binary.is_file() and not binary.is_symlink() and
                  os.access(binary, os.X_OK),
                  'Missing pinned '+name)
        e.require(hashlib.sha256(binary.read_bytes()).hexdigest() == policy[name+'_sha256'],
                  'Pinned binary digest mismatch: '+name)
    return dict(ready=True, task_id=task_id, policy_digest=e.digest(policy), spec=spec,
                spec_digest=e.digest(spec), source=spec['source'], allowed=spec['allowed'],
                checks=spec['checks'], maximum_nano_usd=maximum,
                initialized=False, authorized=False, inference=False, publication=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('build').add_argument('--candidate', required=True)
    check = sub.add_parser('preflight')
    for flag in ('legacy-policy', 'policy', 'broker', 'api-config'):
        check.add_argument('--'+flag, required=True)
    args = parser.parse_args()
    try:
        result = (build(args.candidate) if args.command == 'build' else
                  preflight(args.legacy_policy, args.policy, args.broker, args.api_config))
        print(e.canonical(result))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(e.canonical(dict(ready=False, reason=str(exc), initialized=False)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
