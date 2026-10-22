"""Real offline containers around the existing trusted synthetic ledger gates."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from infrastructure import ContainerRuntime, ContainerQA, docker, source_files, source_modes, artifact_digest, tree_digest
from independent_qa import IndependentQA, RISKS
from metering import parse_events, verify_authoritative_billing
from orchestrator import ROOT, read_json
from planning import initialize
from publication import Publisher
from rehearsal import SyntheticIssuer, SyntheticGitHub, fixture, git
from secure_ledger import Ledger
from trust import canonical, digest, require_live


def image(role):
    value=json.loads(docker('image','inspect','fc54-'+role+':rehearsal').stdout)[0]['Id']
    return value


def expect_blocked(action):
    try:
        action()
    except (ValueError,RuntimeError):
        return True
    raise RuntimeError('Failure scenario did not fail closed')


def rehearse():
    runtime=ContainerRuntime()
    images={role:image(role) for role in ('controller','coding','qa')}
    # Actual fixed probes run separately under both identities, before any task.
    probes={role:runtime.run(role,images[role],{'policy':'probe'},timeout=180)
            for role in ('coding','qa')}
    controller_smoke=runtime.run('controller',images['controller'],{},timeout=180)
    with tempfile.TemporaryDirectory(prefix='sprint54-') as root:
        db=Path(root)/'state.db'; initialize(db)
        now=1792670400
        issuer=SyntheticIssuer(); source,base=fixture(root)
        ledger=Ledger(db,issuer.verifier,lambda:now,{'synthetic/server'},synthetic=True)
        spec=dict(task='synthetic/server#3',repo='synthetic/server',branch='task/maze-3',source=base,area='maze',allowed=['calc.py'])
        issue=dict(id=spec['task'],repo=spec['repo'],area='maze',priority=90,estimated_usd=3,risk='L1',depends_on=[])
        plan=ledger.plan(read_json(ROOT/'config/settings.json'),[issue])
        failures={'invalid_authorization':expect_blocked(lambda:ledger.dispatch(spec,{})),
                  'live_execution':expect_blocked(require_live)}
        execution=ledger.dispatch(spec,issuer.grant('dispatch',ledger.request(spec),now))
        ledger.claim(execution,'coding:isolated')
        # Export only tracked exact source; no .git/config/hooks reach container.
        from independent_qa import export
        coding=Path(root)/'coding-export'; coding.mkdir(); export(source,base,coding)
        files=source_files(coding)
        fixed=runtime.run('coding',images['coding'],dict(files=files,modes=source_modes(coding),artifact=artifact_digest(files,source_modes(coding)),policy='fixture'),timeout=180)
        if fixed.get('artifact') != artifact_digest(fixed['files'],fixed['modes']) or fixed['modes'] != source_modes(coding):
            raise ValueError('Candidate transport digest mismatch')
        # Fixed synthetic ingestion: real worker artifacts need an audited broker.
        changed=sorted(p for p in set(files)|set(fixed['files']) if files.get(p)!=fixed['files'].get(p))
        if changed != ['calc.py']:
            raise ValueError('Synthetic changed-file allowlist')
        shutil.rmtree(coding)
        if coding.exists(): raise RuntimeError('Coding workspace cleanup failed')
        repo=Path(root)/'ingested'
        subprocess.run(['git','clone','--no-local',str(source),str(repo)],check=True,capture_output=True)
        (repo/'calc.py').write_text(fixed['files']['calc.py'])
        git(repo,'add','.');git(repo,'commit','-m','Isolated synthetic repair')
        commit=git(repo,'rev-parse','HEAD')
        mirror=Path(root)/'mirror'
        subprocess.run(['git','clone','--bare','--no-local',str(repo),str(mirror)],check=True,capture_output=True)
        shutil.rmtree(repo)
        usage=parse_events([canonical(dict(type='thread.started',thread_id='synthetic-thread')),
            canonical(dict(type='turn.completed',usage=dict(input_tokens=100,cached_input_tokens=0,output_tokens=20)))],execution,'synthetic-model')
        ledger.record_usage(execution,issuer.evidence(execution,now,usage=usage),issuer.verify_evidence)
        ledger.terminated(execution)
        failures['missing_billing']=expect_blocked(lambda:ledger.finalize(execution,{},verify_authoritative_billing))
        failures['unreconciled_candidate']=expect_blocked(lambda:ledger.finish(execution,commit))
        ledger.finalize(execution,issuer.billing(execution,now,25),issuer.verify_billing)
        ledger.finish(execution,commit)
        qa=IndependentQA(ledger,ContainerQA(images['qa']),issuer.reviewer)
        report,diff=qa.inspect(execution,mirror)
        failures['qa_rejection']=expect_blocked(lambda:qa.accept(execution,report,{}))
        review=issuer.grant('qa',dict(run=execution,report=digest(report),risks={r:'approved' for r in RISKS}),now,qa=True)
        approved=qa.accept(execution,report,review)
        transport=SyntheticGitHub(spec['repo'])
        publisher=Publisher(ledger,transport)
        failures['invalid_publication']=expect_blocked(lambda:publisher.publish(execution,{}))
        grant=issuer.grant('publish',ledger.request(spec,'publish',commit,approved['digest']),now)
        pr=publisher.publish(execution,grant)
        if publisher.resume(execution)!=pr or transport.calls!=['push','create']:
            raise RuntimeError('Duplicate publication')
        # Actual container cancellation proves removal of its entire cgroup.
        cancellation_started=[None]
        def cancelled():
            if cancellation_started[0] is None: cancellation_started[0]=time.monotonic()
            return time.monotonic()-cancellation_started[0] >= 3
        failures['cancellation']=expect_blocked(lambda:runtime.run('coding',images['coding'],{'policy':'cancellation-probe'},cancelled=cancelled))
        failures['crash']=expect_blocked(lambda:runtime.run('coding',images['coding'],dict(files={'../escape':'x'},modes={'../escape':0o644},artifact='invalid',policy='fixture')))
        ledger.stop(issuer.grant('kill',{'ledger':'sprint-5.3'},now))
        failures['kill_switch']=expect_blocked(lambda:ledger.dispatch(spec,issuer.grant('dispatch',ledger.request(spec),now)))
        with ledger.tx() as con:
            audit=[dict(id=row[0],at=row[1],run=row[2],event=row[3],payload=json.loads(row[4]))
                   for row in con.execute('SELECT id,at,run,event,payload FROM s53_events ORDER BY id')]
            events=[record['event'] for record in audit]
            holds=con.execute('SELECT count(*) FROM reservations').fetchone()[0]
        if docker('ps','-aq','--filter','label=fc.sprint=5.4').stdout.strip():
            raise RuntimeError('Leaked rehearsal container')
        return dict(synthetic=True,live_execution=False,images=images,probes=probes,
            controller_smoke=controller_smoke['live_execution'] is False,
            selected=len(plan['selected']),candidate=commit,artifact_sha=report['artifact_sha'],
            tests=report['tests'],failures=failures,events=events,audit_history=audit,draft=pr['draft'],
            planning_holds_preserved=holds,billed_dollars=None,synthetic_final_cents=25,
            isolation='gVisor containers; not a hardened VM boundary')
