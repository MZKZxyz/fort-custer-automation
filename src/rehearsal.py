"""Completely offline rehearsal. Synthetic identity/billing keys are ephemeral.

FixtureRunner may execute ONLY our generated, trusted fixture; it is not an OS
sandbox for untrusted server code. Operational ledgers reject synthetic QA.
"""
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import uuid
from trust import Verifier, canonical, digest
from planning import initialize
from secure_ledger import Ledger
from workers import MockWorker
from independent_qa import IndependentQA, RISKS
from publication import Publisher
from metering import parse_events


class SyntheticIssuer:
    def __init__(self):
        self.key=secrets.token_bytes(32)
        self.verifier=Verifier(self.key,'synthetic-human-service','sprint-5.3',{'operator:fixture'})
        self.qa_key=secrets.token_bytes(32)
        self.reviewer=Verifier(self.qa_key,'synthetic-qa-service','independent-review',{'reviewer:fixture'})

    def grant(self,action,binding,now,qa=False):
        payload=dict(issuer='synthetic-qa-service' if qa else 'synthetic-human-service',
                     audience='independent-review' if qa else 'sprint-5.3',
                     subject='reviewer:fixture' if qa else 'operator:fixture',action=action,
                     binding=binding,issued=int(now),expires=int(now)+300,nonce=uuid.uuid4().hex)
        return dict(payload=payload,signature=hmac.new(self.qa_key if qa else self.key,canonical(payload).encode(),hashlib.sha256).hexdigest())

    def evidence(self,run,now,**values):
        payload=dict(execution=run,at=now,synthetic=True,**values)
        return dict(payload=payload,signature=hmac.new(self.key,canonical(payload).encode(),hashlib.sha256).hexdigest())

    def verify_evidence(self,envelope,run,now):
        p=envelope['payload']
        if (not hmac.compare_digest(envelope['signature'],hmac.new(self.key,canonical(p).encode(),hashlib.sha256).hexdigest())
                or p['execution']!=run or p['synthetic'] is not True or not now-60<=p['at']<=now):
            raise ValueError('Forged/missing/stale synthetic evidence')

    def billing(self,run,now,cents):
        proof=self.evidence(run,now,cents=cents)
        return dict(cents=cents,synthetic=True,proof=proof)

    def verify_billing(self,e,run,now):
        self.verify_evidence(e['proof'],run,now)
        if e['proof']['payload'].get('cents')!=e['cents'] or e['synthetic'] is not True:
            raise ValueError('Modified billing')


class FixtureRunner:
    synthetic=True
    checks=(('unit', (sys.executable,'-m','unittest','discover','-s','test','-v')),)
    def run(self,root,command):
        from codex_adapter import Supervisor
        r=Supervisor().run(command,cwd=root,timeout=5)
        return dict(status='passed' if r['code']==0 and not r['reason'] else 'failed',
                    command=list(command),output=hashlib.sha256(r['stdout']+r['stderr']).hexdigest())


class SyntheticGitHub:
    synthetic=True
    def __init__(self,repository):
        self.repository=repository; self.refs={}; self.prs=[]; self.calls=[]; self.fail=None
    def repository_id(self):
        if self.fail=='auth': raise ValueError('Synthetic GitHub 401')
        return self.repository
    def head(self,branch): return self.refs.get(branch)
    def drafts(self,branch): return [p for p in self.prs if p['head']['ref']==branch]
    def push(self,branch,candidate):
        self.calls.append('push'); self.refs[branch]=candidate
        if self.fail=='push': raise ValueError('Synthetic lost push response')
    def create(self,branch,title,body):
        self.calls.append('create')
        p=dict(html_url='mock://draft/1',state='open',draft=True,merged=False,auto_merge=None,
               head=dict(ref=branch,sha=self.refs[branch],repo=dict(full_name=self.repository)),
               base=dict(ref='main',repo=dict(full_name=self.repository)),body=body)
        self.prs.append(p)
        if self.fail=='create': raise ValueError('Synthetic lost PR response')
        return p


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),'-c','user.name=Fixture',
                                   '-c','user.email=fixture@example.invalid','-c','core.hooksPath=/dev/null',*args],stderr=subprocess.DEVNULL).decode().strip()


def fixture(root):
    source=Path(root)/'fixture'; source.mkdir()
    git(source,'init'); (source/'test').mkdir()
    (source/'calc.py').write_text('def add(a,b): return a-b\n')
    (source/'test/test_calc.py').write_text('import unittest\nfrom calc import add\nclass Tests(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n')
    git(source,'add','.'); git(source,'commit','-m','Synthetic failing task')
    base=git(source,'rev-parse','HEAD')
    return source,base


def candidate(root,source,base,run):
    checkout=MockWorker().checkout(source,base,run,root)/'repo'
    (checkout/'calc.py').write_text('def add(a,b): return a+b\n')
    git(checkout,'add','.'); git(checkout,'commit','-m','Synthetic repair')
    commit=git(checkout,'rev-parse','HEAD')
    mirror=Path(root)/('mirror-'+run)
    subprocess.run(['git','clone','--bare','--no-local',str(checkout),str(mirror)],check=True,capture_output=True)
    return mirror,commit


def run_rehearsal():
    from orchestrator import read_json, ROOT
    with tempfile.TemporaryDirectory(prefix='sprint53-') as root:
        db=Path(root)/'state.db'; initialize(db)
        now=1792670400
        issuer=SyntheticIssuer(); source,base=fixture(root)
        ledger=Ledger(db,issuer.verifier,lambda:now,{'synthetic/server'},synthetic=True)
        spec=dict(task='synthetic/server#3',repo='synthetic/server',branch='task/maze-3',source=base,area='maze',allowed=['calc.py'])
        backlog=[dict(id=spec['task'],repo=spec['repo'],area='maze',priority=90,estimated_usd=3,risk='L1',depends_on=[])]
        plan=ledger.plan(read_json(ROOT/'config/settings.json'),backlog)
        request=ledger.request(spec)
        execution=ledger.dispatch(spec,issuer.grant('dispatch',request,now))
        ledger.claim(execution,'coding:synthetic')
        mirror,commit=candidate(root,source,base,execution)
        usage=parse_events([canonical(dict(type='thread.started',thread_id='synthetic-thread')),
                            canonical(dict(type='turn.completed',usage=dict(input_tokens=100,cached_input_tokens=0,output_tokens=20)))],execution,'synthetic-model','synthetic-v1')
        ledger.record_usage(execution,issuer.evidence(execution,now,usage=usage),issuer.verify_evidence)
        ledger.terminated(execution)
        ledger.finalize(execution,issuer.billing(execution,now,25),issuer.verify_billing)
        ledger.finish(execution,commit)
        qa=IndependentQA(ledger,FixtureRunner(),issuer.reviewer)
        report,diff=qa.inspect(execution,mirror)
        review=issuer.grant('qa',dict(run=execution,report=digest(report),risks={r:'approved' for r in RISKS}),now,qa=True)
        approved=qa.accept(execution,report,review)
        transport=SyntheticGitHub(spec['repo'])
        grant=issuer.grant('publish',ledger.request(spec,'publish',commit,approved['digest']),now)
        pr=Publisher(ledger,transport).publish(execution,grant)
        with ledger.tx() as con:
            events=[r[0] for r in con.execute('SELECT event FROM s53_events ORDER BY id')]
            holds=con.execute('SELECT count(*) FROM reservations').fetchone()[0]
        return dict(synthetic=True,live_execution=False,selected=len(plan['selected']),
                    events=events,qa_tests=report['tests'],draft=pr['draft'],
                    original_planning_holds_preserved=holds,
                    billed_dollars=None,synthetic_final_cents=25)


if __name__=='__main__':
    print(json.dumps(run_rehearsal(),indent=2))
