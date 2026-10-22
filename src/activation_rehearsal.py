"""Offline control-plane activation contract rehearsal; no production attestation."""
import json
from pathlib import Path
import tempfile
import uuid
from model_broker import ModelBroker, SyntheticProvider
from readiness import audit
from rehearsal import run_rehearsal
from trust import canonical, digest
from vm_runtime import VMRuntime, SyntheticVMProvider


def worker_hook(ledger, execution, spec, issuer, now, evidence_dir=None, cancel_after_response=False):
    # Assert the reservation in the authoritative ledger, not a worker boolean.
    with ledger.tx() as db:
        row = ledger.get(db, execution)
        if row['reserved'] != 300 or row['state'] != 'running':
            raise ValueError('Verified reservation required')
    with tempfile.TemporaryDirectory() as d:
        broker = ModelBroker(Path(d)/'broker.db', SyntheticProvider(), lambda: now, initialize=True)
        principal = 'vsock:synthetic:'+execution
        broker.register(execution, spec['task'], principal, int(row['deadline']))
        provider = SyntheticVMProvider()
        request = dict(execution=execution, task=spec['task'], source=spec['source'], scope=spec['allowed'],
                       image='sha256:'+'a'*64, issued=now, deadline=int(row['deadline']))
        envelope = issuer.grant('vm-execution', request, now)
        cancelled = [False]
        def exchange(provider, request):
            response = broker.request(principal, canonical(dict(execution=execution, task=spec['task'],
                request_id=uuid.uuid4().hex, model='synthetic-codex', operation='investigate',
                input='Investigate maze generation using the frozen task scope', max_output_tokens=128)).encode())
            if cancel_after_response:
                broker.revoke(execution); cancelled[0] = True
            return response
        try:
            result = VMRuntime(provider, issuer.verifier, lambda: now).run(request, envelope, exchange, lambda:cancelled[0])
        except ValueError:
            if not cancelled[0]: raise
            result = dict(cancelled=True, cleanup_verified=not provider.requests)
        broker.revoke(execution)
        with broker.tx() as db:
            events = [r[0] for r in db.execute('SELECT event FROM audit ORDER BY id')]
        if evidence_dir is not None:
            import sqlite3
            name = 'cancelled-broker.db' if cancel_after_response else 'synthetic-broker.db'
            with sqlite3.connect(broker.path) as source, sqlite3.connect(Path(evidence_dir)/name) as target:
                source.backup(target)
        return dict(reservation_cents=row['reserved'], provider='synthetic-contract-double',
                    real_vm=False, lifecycle=provider.calls, broker_audit=events,
                    response_digest=digest(result), credentials_in_worker=False)


def cancellation_rehearsal(evidence_dir=None):
    from planning import initialize
    from secure_ledger import Ledger
    from rehearsal import SyntheticIssuer, fixture
    from ledger_backup import snapshot
    now = 1792670400
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);path=root/'cancelled-ledger.db';initialize(path)
        issuer=SyntheticIssuer();source,base=fixture(root)
        ledger=Ledger(path,issuer.verifier,lambda:now,{'synthetic/server'},synthetic=True)
        spec=dict(task='synthetic/server#3',repo='synthetic/server',branch='task/maze-3',source=base,area='maze',allowed=['calc.py'])
        execution=ledger.dispatch(spec,issuer.grant('dispatch',ledger.request(spec),now))
        ledger.claim(execution,'coding:synthetic')
        proof=worker_hook(ledger,execution,spec,issuer,now,evidence_dir,True)
        ledger.stop(run=execution);ledger.terminated(execution)
        ledger.finalize(execution,issuer.billing(execution,now,0),issuer.verify_billing)
        ledger.finish(execution)
        with ledger.tx() as db:
            row=ledger.get(db,execution)
            events=[r[0] for r in db.execute('SELECT event FROM s53_events ORDER BY id')]
        if row['state']!='failed' or not row['stopped'] or row['final']!=0:
            raise ValueError('Cancellation accounting unresolved')
        if evidence_dir is not None:snapshot(path,Path(evidence_dir)/'cancelled-ledger.db')
        return dict(synthetic=True,state=row['state'],terminated=bool(row['stopped']),final_synthetic_cents=row['final'],
                    events=events,worker=proof)


def rehearse(evidence_dir=None):
    if evidence_dir is not None:
        evidence_dir = Path(evidence_dir)
        evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    readiness = audit()
    if readiness['ready'] or readiness['live_execution']:
        raise ValueError('Offline rehearsal must preserve blocked live readiness')
    result = run_rehearsal(worker_hook=lambda *args: worker_hook(*args, evidence_dir=evidence_dir), evidence_dir=evidence_dir)
    report = dict(kind='offline-control-plane-contract-rehearsal', live_execution=False,
                readiness=readiness, workflow=result, cancellation=cancellation_rehearsal(evidence_dir), real_server_suite='not_run',
                real_vm_attestation=False, offhost_restore_attestation=False)
    if evidence_dir is not None:
        (evidence_dir/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-dir', type=Path, required=True)
    print(json.dumps(rehearse(parser.parse_args().evidence_dir), indent=2))
