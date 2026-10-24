"""Offline policy versioning for the second comment-only observation canary."""
import argparse
import copy
from pathlib import Path

from src import orchestration_evidence as e, api_controller as api
from src.observation_validation import read_policy
from src.local_catalog import resolve
from src.live_observation import ObservationBroker
from src.concurrency_coordinator import stopped
from src.observation_planning import observation_prompt
from src.source_observation import git

ORIGINAL = 'solver-comment-review'
SECOND = 'solver-comment-verification-2'


def candidate(path):
    policy, _ = read_policy(path)
    e.require(ORIGINAL in policy['catalog']['tasks'] and SECOND not in policy['catalog']['tasks'],
              'Original task required and second identifier must be new')
    result = copy.deepcopy(policy)
    result['catalog']['tasks'][SECOND] = copy.deepcopy(policy['catalog']['tasks'][ORIGINAL])
    # No manifest rebuilding, source refresh, path, limit or instruction changes.
    spec, _ = resolve(result, SECOND, observation_only=True)
    api.observation_payload(observation_prompt({'spec': spec}))
    return result


def preflight(original, version, broker_path, api_path):
    original, version = e.regular(original), e.regular(version)
    e.require(original != version, 'Separate versioned policy file required')
    expected = candidate(original)
    policy, _ = read_policy(version)
    e.require(policy == expected, 'Version must only add an identical second task')
    e.require(policy['enabled'] is True, 'Catalog disabled')
    spec, _ = resolve(policy, SECOND, observation_only=True)
    repo = policy['repositories'][spec['repo']]
    e.require(git(repo['source'], 'rev-parse', 'HEAD').decode().strip() == spec['source'],
              'Stale source revision; no automatic refresh')
    runs, _ = e.executions(Path(policy['state'])/'local.sqlite')
    e.require(any(r['spec'].get('task_id') == ORIGINAL for r in runs.values()),
              'Original task consumption not found')
    e.require(not any(r['spec'].get('task_id') == SECOND for r in runs.values()),
              'Second catalog identifier already consumed')
    e.require(not any(r['state'] == 'running' for r in runs.values()), 'Existing worker hold')
    broker = ObservationBroker(e.decode(e.regular(broker_path).read_bytes()))
    # inspect opens the EXISTING store read-only and enforces its original config digest.
    audit = broker.inspect()
    e.require(audit['enabled'] and not stopped(broker.c), 'Observation disabled or STOP')
    e.require(str(Path(policy['state'])/'STOP') in broker.c['stop_files'],
              'Catalog STOP omitted; existing broker configuration cannot be changed')
    e.require(not any(r['claim']['task'] == SECOND for r in audit['tasks'].values()),
              'Second observation identifier already consumed')
    e.require(len(audit['tasks']) < broker.c['max_tasks'], 'Observation ledger ceiling')
    c, prices, budget = api.configuration(api_path)
    e.require(not c['connectivity_enabled'] and prices == api.DEFAULT_PRICING,
              'Unsupported API configuration')
    status = budget.status()
    maximum = api.maximum_charge(prices, api.OBSERVATION_OUTPUT)
    e.require(status['unresolved_requests'] == 0, 'Unresolved API reservation')
    e.require(status['daily_encumbered_nano_usd']+maximum <= status['daily_limit_nano_usd'] and
              status['lifetime_encumbered_nano_usd']+maximum <= status['lifetime_limit_nano_usd'],
              'Insufficient existing budget')
    return dict(ready_for_manual_preparation=True, task_id=SECOND, policy_digest=e.digest(policy),
                broker_config_digest=broker.config_digest, authorized=False, initialized=False,
                inference=False, maximum_nano_usd=maximum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('candidate'); build.add_argument('--original', required=True)
    check = sub.add_parser('preflight')
    for name in ('original', 'policy', 'broker', 'api-config'):
        check.add_argument('--'+name, required=True)
    args = parser.parse_args()
    try:
        result = (candidate(args.original) if args.command == 'candidate' else
                  preflight(args.original, args.policy, args.broker, args.api_config))
        print(e.canonical(result)); return 0
    except Exception as exc:
        print(e.canonical(dict(ready=False, reason=str(exc), authorized=False, initialized=False)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
