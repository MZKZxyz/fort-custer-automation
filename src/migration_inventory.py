"""Read-only legacy inventory for explicit operator reconciliation.

This never creates or migrates a ledger, imports approvals, resolves ambiguity,
or asserts that snapshots from multiple SQLite databases committed atomically.
"""
import argparse
import json
from pathlib import Path
import sqlite3

from src import orchestration_evidence as e

PROTOCOL = 'migration-inventory-v1-blocked'


def inventory(policy_path, coordinator_config=None, broker_config=None):
    policy = e.decode(e.regular(policy_path).read_bytes())
    path = Path(policy['state'])/'local.sqlite'
    runs, pubs = e.executions(path)
    local = []
    for identity, run in runs.items():
        state = run.get('state', 'unknown')
        local.append(dict(execution=identity, state=state, evidence=e.digest(run),
                          disposition='retain-history-fresh-approval-required',
                          termination_review_required=state not in ('pending', 'approved', 'validated'),
                          authorization_converted=False))
    result = dict(schema=PROTOCOL, live_dispatch=False, migration_verified=False,
                  completeness='operator-must-inventory-all-installations-and-older-ledgers',
                  simultaneous_snapshot=False, local=local,
                  publications=[dict(publication=k, state=p['status'], evidence=e.digest(p),
                      review_required=p['status'] != 'completed') for k,p in pubs.items()],
                  coordinator='not-supplied', broker='not-supplied',
                  required_action='STOP all legacy services; preserve backups; independently reconcile every hold; fresh broker approval only')
    if coordinator_config is not None:
        from src.concurrency_coordinator import Coordinator, ACTIVE
        view = Coordinator(coordinator_config).inspect()
        result['coordinator'] = [dict(task=k, state=r['state'], evidence=e.digest(r),
                                     termination_review_required=r['state'] in ACTIVE,
                                     authorization_converted=False) for k,r in view['tasks'].items()]
    if broker_config is not None:
        from src.grant_broker import Broker, ACTIVE
        view = Broker(broker_config).inspect()
        result['broker'] = [dict(execution=k, state=r['state'], evidence=e.digest(r),
                                termination_review_required=r['state'] in ACTIVE,
                                authorization_converted=False) for k,r in view['tasks'].items()]
    result['inventory_digest'] = e.digest(result)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy', required=True)
    p.add_argument('--coordinator')
    p.add_argument('--broker-config')
    args = p.parse_args(argv)
    try:
        def config(path):
            return e.decode(e.regular(path).read_bytes()) if path else None
        report = inventory(args.policy, config(args.coordinator), config(args.broker_config))
        print(json.dumps(report, sort_keys=True, indent=2))
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        p.exit(1, 'Inventory unknown; preserve original ledgers and inspect as the owning operator.\n')
    return 1  # Inventory is never activation approval.


if __name__ == '__main__':
    raise SystemExit(main())
