"""Offline coding adapter; live admission remains blocked pending experiment evidence."""
import argparse

from src import coding_contract as contract, orchestration_evidence as e
from src import worker_handoff as wire
from src.grant_broker import Broker
from src.source_observation import source_files, manifest

INSTRUCTIONS = ('Add one explanatory comment above compile describing its existing behavior. '
                'Preserve all executable code and behavior.')


def replay_synthetic(broker, claim, response):
    """Consume an existing synthetic claim, validate a proposal, rebuild, then QA.

    This is deliberately not a live authority, an API accounting receipt, or a
    publication artifact. Failed/ambiguous work retains the existing broker hold.
    No raw provider envelope is persisted by this adapter.
    """
    e.require(type(broker) is Broker, 'Synthetic broker required')
    with broker.tx() as db:
        row = broker._owned(db, claim, {'claimed'})
        broker._guard(claim)
        a = row['authorization']
        broker._fresh(a)
        spec = a['spec']
        e.require(spec['allowed'] == [contract.FILE] and
                  spec['task']['instructions'] == INSTRUCTIONS,
                  'Only reviewed compile comment task supported')
        commands = [c['argv'] for c in spec['checks']]
        e.require(['node', '--check', contract.FILE] in commands and
                  ['node', '--test', 'test/analyzer.test.js'] in commands,
                  'Syntax and existing analyzer checks required')
    # Durable single-use intent precedes interpreting any untrusted edit.
    req = broker.start_synthetic(claim)
    policy, _, _ = e.catalog(a['policy_path'])
    files = source_files(policy['repositories'][spec['repo']]['source'],
                         a['source'], a['allowed'])
    candidate = contract.apply(response, files, source_manifest=a['source_manifest'],
                               allowed=a['allowed'])
    e.require(manifest(files) == a['source_manifest'], 'Pinned source mismatch')
    broker.capture_synthetic(claim, wire.response(req, {
        name: candidate[name] for name in a['allowed']}))
    return broker.validate_synthetic(claim)


def readiness():
    return dict(schema='coding-canary-readiness-v1', live_enabled=False,
                model_family='GPT-6.1 Sol', reasoning_effort='low',
                tools=[], publication=False, automatic_retry=False,
                blockers=['exact tested request and reviewed pricing unavailable',
                          'saved successful Sol Low comment response unavailable',
                          'live coding admission and API accounting integration incomplete'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['readiness', 'live'])
    args = parser.parse_args()
    result = readiness()
    if args.command == 'live':
        result.update(status='blocked', retry=False)
    print(e.canonical(result))
    return 1 if args.command == 'live' else 0


if __name__ == '__main__':
    raise SystemExit(main())
