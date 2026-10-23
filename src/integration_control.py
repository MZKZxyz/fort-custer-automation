"""Read-only supervised readiness and the non-configurable v2 migration gate."""
import argparse
import json
import os
from pathlib import Path
import time

from src import orchestration_evidence as e
from src.source_observation import git

PROTOCOL = 'supervised-integration-v2-blocked'
BLOCKERS = (
    'No shared atomic controller/coordinator grant broker has been migrated',
    'No independently verified credential-free external worker and QA isolation',
    'No isolated publisher identity or current GitHub prerequisites verified',
)


def block_live_dispatch():
    # No env var, policy field, receipt supplied by the caller, or CLI override.
    # Old approval hashes remain historical approvals, never v2 broker grants.
    raise ValueError(PROTOCOL + ': ' + '; '.join(BLOCKERS))


def health(policy_path, coordinator_path=None, now=None, *, broker_path=None, broker_config=None):
    """Never initializes a ledger, loads secrets, invokes a worker or authenticates."""
    now = time.time() if now is None else now
    report = dict(schema=PROTOCOL, live_ready=False, live_dispatch=False,
                  live_worker_ceiling=1, scheduling=False, concurrent_live=False,
                  checks={}, blockers=list(BLOCKERS))
    checks = report['checks']
    checks.update(worker_isolation='unverified', publisher_credential_isolation='unverified',
                  github_draft_prerequisites='unverified', independent_qa='unverified',
                  unified_grants='migration-required', coordinator='not-supplied',
                  source_sha='unknown', policy_catalog='unknown', stop='unknown',
                  ledger_integrity='unknown')
    report.update(approved_tasks=None, active_or_ambiguous=None)
    try:
        policy, _, specs = e.catalog(policy_path)
        checks['policy_catalog'] = 'compatible'
        checks['stop'] = 'active' if os.path.lexists(Path(policy['state'])/'STOP') else 'clear'
        checks['source_sha'] = 'valid'
        for spec in specs.values():
            source = policy['repositories'][spec['repo']]['source']
            e.require(git(source, 'rev-parse', 'HEAD').decode().strip() == spec['source'],
                      'Source HEAD changed')
            e.require(not git(source, 'status', '--porcelain', '--untracked-files=all').strip(),
                      'Source checkout conflict')
        runs, _ = e.executions(Path(policy['state'])/'local.sqlite')
        states = []
        for run in runs.values():
            spec = specs.get(run['spec'].get('task_id'))
            if spec is None:
                states.append('historical-unresolved')
            else:
                states.append(e.run_state(run, spec, policy, now)[0])
        checks['ledger_integrity'] = 'verified'
        report['approved_tasks'] = states.count('approved-for-coding')
        report['active_or_ambiguous'] = sum(s in ('running', 'interrupted', 'historical-unresolved',
                                                  'ambiguous-publication', 'blocked') for s in states)
        node = Path(policy['node'])
        import hashlib
        checks['independent_qa'] = ('binary-verified-isolation-unverified' if
            node.is_file() and not node.is_symlink() and os.access(node, os.X_OK) and
            hashlib.sha256(node.read_bytes()).hexdigest() == policy['node_sha256'] else 'blocked')
    except Exception:
        # Do not echo filesystem exceptions, policy content, or subprocess output.
        checks['local_evidence'] = 'unknown-or-contradictory'
        report['blockers'].append('Local source, catalog or ledger verification failed')
    if coordinator_path:
        try:
            from src.concurrency_coordinator import configuration, observations, ACTIVE
            view = observations(configuration(coordinator_path))
            checks['coordinator'] = 'synthetic-only'
            report['synthetic_active_or_ambiguous'] = sum(
                row['state'] in ACTIVE for row in view['tasks'].values())
            if view['stop']: checks['stop'] = 'active'
        except Exception:
            checks['coordinator'] = 'unknown-or-contradictory'
            report['blockers'].append('Coordinator evidence verification failed')
    checks.update(broker_schema='not-supplied', atomic_claim_authority='blocked-not-migrated',
                  legacy_path_migration='blocked-not-migrated', worker_peer_authentication='not-provisioned',
                  filesystem_isolation_evidence='not-verified', qa_isolation='not-verified',
                  publisher_separation='not-verified', live_worker_capacity=0)
    from src.worker_transport import sys as transport_platform
    checks['worker_peer_authentication'] = ('kernel-api-available-endpoint-unverified' if
        transport_platform.platform.startswith('linux') or transport_platform.platform == 'darwin'
        else 'unsupported-platform')
    report['unsupported_resource_controls'] = ['hard_cpu', 'hard_memory', 'hard_disk', 'network_egress']
    if broker_path is not None:
        try:
            from src.grant_broker import Broker
            e.require(broker_config is not None and
                      Path(broker_config['ledger']).absolute() == Path(broker_path).absolute(),
                      'Explicit matching broker configuration required')
            view = Broker(broker_config, lambda:now).inspect()
            report['broker'] = {k:v for k,v in view.items() if k != 'tasks'}
            checks['broker_schema'] = view['schema']
            checks['atomic_claim_authority'] = view['atomic_authority']
            if view['stop']: checks['stop'] = 'active'
        except Exception:
            checks['broker_schema'] = 'unknown-or-contradictory'
            report['blockers'].append('Broker integrity/configuration verification failed')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--coordinator')
    parser.add_argument('--broker-config')
    args = parser.parse_args(argv)
    config = None
    if args.broker_config:
        try:
            config = e.decode(e.regular(args.broker_config).read_bytes())
            e.require(isinstance(config, dict) and isinstance(config.get('ledger'), str),
                      'Invalid broker configuration')
        except Exception: config = {'ledger': '/invalid-broker-configuration'}
    print(json.dumps(health(args.policy, args.coordinator,
                           broker_path=config['ledger'] if config else None,
                           broker_config=config), sort_keys=True, indent=2))
    return 1  # Intentionally blocked until a reviewed implementation replaces v2.


if __name__ == '__main__':
    raise SystemExit(main())
