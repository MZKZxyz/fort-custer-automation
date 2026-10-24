"""One supervised coding request with separate terminal authorization; no publisher."""
import argparse
import os
import pwd
from pathlib import Path

from src import coding_contract as contract, orchestration_evidence as e
from src import worker_handoff as wire
from src.grant_broker import Broker
from src.source_observation import source_files, manifest

INSTRUCTIONS = contract.INSTRUCTIONS
SOURCE = contract.SOURCE
COMPILE_REGRESSION = """import assert from 'node:assert/strict';
import {compile} from './tools/maze-analyzer/solver.js';
const maze=compile(['#####','#SXE#','# F #','#####']);
assert.equal(maze.width,5);assert.equal(maze.height,4);
assert.equal(maze.start,6);assert.equal(maze.goal,8);
assert.deepEqual(maze.items,[7]);assert.deepEqual(maze.fires,[12]);
assert.equal(maze.bits.get(7),1n);assert.equal(maze.bits.get(12),2n);
for(const rows of [[],['S'],['SSE'],['SE','S'],['S?E']]) assert.throws(()=>compile(rows));
console.log('compile comment regression passed');
"""


def reviewed(a):
    spec = a['spec']
    contract.catalog_task(spec['task'])
    e.require(a['source'] == SOURCE and spec['repo'] == 'fort-custer-server' and
              spec['task']['repository'] == 'MZKZxyz/fort-custer-server' and
              spec['task']['instructions'] == INSTRUCTIONS and a['allowed'] == [contract.FILE],
              'Only pinned compile comment canary supported')
    commands = [c['argv'] for c in spec['checks']]
    e.require(['node', '--check', contract.FILE] in commands and
              ['node', '--test', 'test/analyzer.test.js'] in commands,
              'Syntax and analyzer checks required')


def run(broker, claim, principal, controller):
    from src.coding_broker import CodingBroker
    from src import api_controller as api, coding_api as profile
    from src.local_runner import Runner
    e.require(type(broker) is CodingBroker and type(controller) is api.Controller and
              controller.prices == profile.PRICING and (
                  type(controller.transport) is api.ResponsesTransport or
                  getattr(controller.transport, 'synthetic', False) is True),
              'Trusted coding controller required')
    a = broker.guard(claim, principal, {'authorized'})
    config, prices, budget = api.configuration(broker.api_config)
    e.require(controller.budget.path == budget.path and
              (getattr(controller.transport, 'synthetic', False) is True or
               Path(controller.transport.credential_file) == Path(config['credential_file']).absolute()),
              'Coding controller configuration mismatch')
    request = profile.payload(a['coding_prompt'])
    binding = dict(receiver='synthetic-coding-only' if getattr(controller.transport, 'synthetic', False)
                   else 'live-coding-only', execution=claim['execution'], claim=e.digest(claim),
                   authorization=e.digest(a), principal=principal, source_manifest=a['source_manifest'])
    def guard(): return broker.guard(claim, principal, {'dispatched'})
    broker.admit(claim, principal)  # Single-use intent before budget or inference.
    phase = 'internal'
    def progress(value):
        nonlocal phase
        phase = value
    try:
        raw_edit = controller._request(e.digest(claim)[:32], request, binding, guard,
                                      _coding=True, _phase=progress)
        phase = 'edit_validation'
        guard()
        policy, _, _ = e.catalog(a['reviewed']['policy_path'])
        spec = a['reviewed']['spec']
        files = source_files(policy['repositories'][spec['repo']]['source'], a['reviewed']['source'], spec['allowed'])
        candidate = contract.apply(raw_edit, files, source_manifest=a['source_manifest'], allowed=spec['allowed'])
        phase = 'independent_qa'
        runner = object.__new__(Runner)
        runner.policy, runner.scratch = policy, Path(broker.c['scratch'])
        runner.scratch.mkdir(mode=0o700, exist_ok=True)
        def cancelled():
            try: guard(); return False
            except Exception: return True
        qa = runner.qa(files, candidate, cancelled, claim['deadline']-broker.clock(), spec=spec,
                       on_check=lambda check:broker.evidence(claim, 'qa_check', check),
                       extra_checks=[('compile-regression',
                           ['node', '--input-type=module', '--eval', COMPILE_REGRESSION], 10)])
        e.require(all(q['code'] == 0 and q['reason'] is None for q in qa), 'Independent QA failed')
        phase = 'final_verification'
        guard()
        result = dict(source_manifest=manifest(files), candidate_manifest=manifest(candidate),
                      checks=qa, comment_regression='executable-bytes-identical',
                      publication='separate-authorization-required', retry=False)
        broker.evidence(claim, 'validated', result)
        broker.guard(claim, principal, {'validated'})
        return result
    except BaseException:
        try: broker.record_failure(claim, phase)
        except Exception: pass  # Failure cannot authorize another request or release a hold.
        raise


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
                blockers=['operator installation, exact task approval and separate one-request authorization required'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['readiness', 'init-broker', 'review', 'authorize', 'live', 'audit', 'revoke'])
    parser.add_argument('--broker', type=Path)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--execution')
    parser.add_argument('--task')
    args = parser.parse_args()
    try:
        if args.command == 'readiness': result = readiness()
        else:
            from src.coding_broker import CodingBroker
            from src import api_controller as api
            broker = CodingBroker(e.decode(e.regular(args.broker).read_bytes()))
            principal = pwd.getpwuid(os.getuid()).pw_name
            if args.command == 'init-broker':
                broker.initialize(); result = dict(status='initialized')
            elif args.command in {'review', 'authorize'}:
                fn = broker.review if args.command == 'review' else broker.authorize
                value = fn(args.policy, args.execution, args.task, principal)
                result = dict(status=args.command, binding=e.digest(value))
                if args.command == 'review': result['review'] = value
            elif args.command == 'audit': result = broker.inspect()
            else:
                rows = broker.inspect()['tasks']
                e.require(args.execution in rows, 'Unknown coding canary')
                claim = rows[args.execution]['claim']
                if args.command == 'revoke':
                    broker.revoke(claim); result = dict(status='revoked')
                else:
                    config, prices, budget = api.configuration(broker.api_config)
                    result = run(broker, claim, principal, api.Controller(
                        budget, api.ResponsesTransport(config['credential_file']), prices))
        print(e.canonical(result)); return 0
    except BaseException:
        print(e.canonical(dict(status='blocked-or-unknown', retry=False,
              instruction='inspect coding audit and existing API budget audit; preserve holds; do not retry')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
