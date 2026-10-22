import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trust import digest, require_live, LIVE_BLOCKERS
from secure_ledger import Ledger
from planning import initialize, plan
from orchestrator import ROOT, read_json
from rehearsal import SyntheticIssuer, SyntheticGitHub, FixtureRunner, fixture, candidate, git, run_rehearsal
from independent_qa import IndependentQA, RISKS, export
from publication import Publisher, AppGitHub
from codex_adapter import CodexAdapter, Supervisor, SandboxTests
from metering import parse_events, estimate, verify_authoritative_billing


class Sprint53Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.db=self.root/'state.db'; initialize(self.db)
        self.now=1792670400; self.issuer=SyntheticIssuer()
        self.ledger=Ledger(self.db,self.issuer.verifier,lambda:self.now,{'synthetic/server'},synthetic=True)
        self.source,self.base=fixture(self.root)
        self.spec=dict(task='synthetic/server#3',repo='synthetic/server',branch='task/maze-3',source=self.base,area='maze',allowed=['calc.py'])

    def grant(self,action='dispatch',binding=None,qa=False):
        return self.issuer.grant(action,binding or self.ledger.request(self.spec),self.now,qa=qa)

    def start(self,spec=None):
        spec=spec or self.spec
        e=self.ledger.dispatch(spec,self.grant(binding=self.ledger.request(spec)))
        self.ledger.claim(e,'coding:fixture')
        return e

    def usage(self,e):
        return self.issuer.evidence(e,self.now,tokens=dict(input_tokens=100,output_tokens=20))

    def finalize(self,e):
        self.ledger.record_usage(e,self.usage(e),self.issuer.verify_evidence)
        self.ledger.terminated(e)
        self.ledger.finalize(e,self.issuer.billing(e,self.now,25),self.issuer.verify_billing)

    def ready(self):
        e=self.start(); mirror,commit=candidate(self.root,self.source,self.base,e)
        self.finalize(e); self.ledger.finish(e,commit)
        q=IndependentQA(self.ledger,FixtureRunner(),self.issuer.reviewer)
        report,diff=q.inspect(e,mirror)
        binding=dict(run=e,report=digest(report),risks={r:'approved' for r in RISKS})
        q.accept(e,report,self.grant('qa',binding,qa=True))
        return e,report

    def pubgrant(self,report):
        return self.grant('publish',self.ledger.request(self.spec,'publish',report['candidate'],digest(report)))

    def test_end_to_end(self):
        r=run_rehearsal()
        self.assertTrue(r['synthetic']); self.assertTrue(r['draft'])
        self.assertFalse(r['live_execution']); self.assertIsNone(r['billed_dollars'])
        self.assertEqual(r['events'][-1],'draft_published')

    def test_invalid_approval_is_atomic(self):
        cases=[None,{},'human:operator',self.grant(),self.grant(),self.grant()]
        cases[3]['payload']['subject']='coding:worker'
        cases[4]['payload']['binding']['spec']['source']='a'*40
        cases[5]['signature']='0'*64
        for grant in cases:
            with self.subTest(grant=type(grant)):
                with self.assertRaises((ValueError,TypeError)): self.ledger.dispatch(self.spec,grant)
        with self.ledger.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM s53_runs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM s53_grants').fetchone()[0],0)

    def test_expired_and_wrong_action(self):
        g=self.grant(); self.now+=301
        with self.assertRaises(ValueError): self.ledger.dispatch(self.spec,g)
        with self.assertRaises(ValueError): self.ledger.dispatch(self.spec,self.grant('publish'))

    def test_replayed_grant(self):
        g=self.grant(); e=self.ledger.dispatch(self.spec,g)
        self.finalize(e); self.ledger.finish(e)
        with self.assertRaises(sqlite3.IntegrityError): self.ledger.dispatch(self.spec,g)

    def test_concurrent_same_task_and_different_tasks(self):
        def attempt(i):
            spec=dict(self.spec,task='synthetic/server#'+str(i+3),branch='task/x-'+str(i),area='area'+str(i))
            try: return self.ledger.dispatch(spec,self.grant(binding=self.ledger.request(spec)))
            except ValueError: return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            runs=list(pool.map(attempt,range(4)))
        self.assertEqual(sum(bool(e) for e in runs),1)
        with self.assertRaises(ValueError): self.start()

    def test_duplicate_claim_and_fenced_owner(self):
        e=self.start()
        with self.assertRaises(ValueError): self.ledger.claim(e,'second')
        with self.assertRaises(ValueError): self.ledger.heartbeat(e,'coding:intruder')

    def test_allowlists_and_protected_scope(self):
        for delta in (dict(repo='production/server'),dict(branch='main'),dict(source='main'),dict(allowed=['.github/workflows/approve.yml']),dict(area='../escape'),dict(task='other/repo#3')):
            with self.subTest(delta=delta):
                with self.assertRaises(ValueError): self.ledger.request(dict(self.spec,**delta))

    def test_expiry_restart_keeps_reservation(self):
        e=self.start(); self.now+=61
        restored=Ledger(self.db,self.issuer.verifier,lambda:self.now,{'synthetic/server'},synthetic=True)
        restored.recover()
        with restored.tx() as db:
            r=restored.get(db,e); self.assertEqual(r['state'],'reconciliation_required')
            self.assertIsNone(r['final']); self.assertEqual(r['reserved'],300)
        with self.assertRaises(ValueError): self.start()
        self.finalize(e)
        with self.assertRaises(ValueError): restored.finish(e,'a'*40)
        restored.finish(e)
        self.start()

    def test_restart_in_fresh_process(self):
        e=self.start(); self.now+=61
        script="from pathlib import Path; from secure_ledger import Ledger; from rehearsal import SyntheticIssuer; import sys; l=Ledger(sys.argv[1],SyntheticIssuer().verifier,lambda:1792670461,{'synthetic/server'},synthetic=True); l.recover()"
        subprocess.run([sys.executable,'-c',script,str(self.db)],env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(ROOT/'src')},check=True)
        with self.ledger.tx() as db: self.assertEqual(self.ledger.get(db,e)['state'],'reconciliation_required')

    def test_kill_switch_persistent(self):
        e=self.start(); g=self.grant('kill',{'ledger':'sprint-5.3'})
        self.ledger.stop(g)
        restored=Ledger(self.db,self.issuer.verifier,lambda:self.now,{'synthetic/server'},synthetic=True)
        with self.assertRaises(ValueError): restored.heartbeat(e,'coding:fixture')
        with self.assertRaises(ValueError): self.start()
        self.finalize(e)
        with self.assertRaises(ValueError): restored.finish(e,'a'*40)

    def test_no_automatic_refund_and_three_attempts(self):
        for i in range(3):
            e=self.start(); self.finalize(e); self.ledger.finish(e)
        with self.assertRaises(ValueError): self.start()
        with self.ledger.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM s53_runs').fetchone()[0],3)

    def test_unresolved_metering_and_tampering(self):
        e=self.start()
        with self.assertRaises(ValueError): self.ledger.finish(e,'a'*40)
        usage=self.usage(e); usage['payload']['tokens']['input_tokens']=0
        with self.assertRaises(ValueError): self.ledger.record_usage(e,usage,self.issuer.verify_evidence)
        self.ledger.terminated(e)
        bill=self.issuer.billing(e,self.now,25); bill['cents']=0
        with self.assertRaises(ValueError): self.ledger.finalize(e,bill,self.issuer.verify_billing)
        with self.assertRaises(ValueError): self.ledger.finalize(e,{},verify_authoritative_billing)
        with self.ledger.tx() as db: self.assertIsNone(self.ledger.get(db,e)['final'])

    def test_append_only_approval_audit(self):
        e=self.start()
        for table in ('s53_grants','s53_events'):
            with self.ledger.tx() as db:
                with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM '+table)

    def test_operational_live_always_blocked(self):
        with self.assertRaises(RuntimeError): CodexAdapter().run(None,None,None,None,None,None,None)
        with self.assertRaises(RuntimeError): require_live()
        p=self.root/'operational.db'; initialize(p)
        operational=Ledger(p,self.issuer.verifier,lambda:self.now,{'synthetic/server'})
        with self.assertRaises(RuntimeError): operational.dispatch(self.spec,self.grant())
        self.assertGreaterEqual(len(LIVE_BLOCKERS),3)
        with self.assertRaises(ValueError): Ledger(self.db,self.issuer.verifier,lambda:self.now,{'synthetic/server'},synthetic=False)

    def test_legacy_authorities_are_fenced(self):
        from execution import Controller
        with self.assertRaises(ValueError): Controller(self.db,lambda:self.now).add('x','synthetic/server','main','x')
        with self.assertRaises(ValueError): plan(self.db,read_json(ROOT/'config/settings.json'),[])

    def test_unified_planning_preserves_history(self):
        settings=read_json(ROOT/'config/settings.json')
        task=dict(id=self.spec['task'],repo=self.spec['repo'],area='maze',priority=1,estimated_usd=1,risk='L1',depends_on=[])
        r=self.ledger.plan(settings,[task])
        self.assertEqual(r,self.ledger.plan(settings,[task]))
        e=self.start()
        with self.ledger.tx() as db:
            self.assertEqual(self.ledger.accounting(db)[3],300)
            before=db.execute('SELECT * FROM reservations').fetchall()
        self.finalize(e); self.ledger.finish(e)
        with self.ledger.tx() as db:
            self.assertEqual(self.ledger.accounting(db)[3],25)
            self.assertEqual(before,db.execute('SELECT * FROM reservations').fetchall())
        self.now+=86400
        second=self.ledger.plan(settings,[task])
        self.assertFalse(second['selected'])
        with self.ledger.tx() as db: self.assertEqual(db.execute('SELECT count(*) FROM daily_plans').fetchone()[0],2)

    def test_competing_daily_plans(self):
        settings=read_json(ROOT/'config/settings.json')
        def p(i):
            backlog=[dict(id='synthetic/server#'+str(i+10),repo='synthetic/server',area='area'+str(i),priority=1,estimated_usd=1,risk='L1',depends_on=[])]
            try: return self.ledger.plan(settings,backlog)
            except ValueError: return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(p,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_budget_ceiling_and_cross_day_holds(self):
        with self.ledger.tx() as db:
            for i in range(3):
                task=dict(id='synthetic/server#'+str(i+10),repo='synthetic/server',area='area'+str(i),reservation_cents=300)
                db.execute('INSERT INTO tasks VALUES (?,?,?)',(task['id'],'reserved',json.dumps(task)))
                db.execute('INSERT INTO reservations VALUES (?,?,?)',(task['id'],'2020-01-01',300))
        with self.assertRaises(ValueError): self.start()
        self.now+=86400
        with self.assertRaises(ValueError): self.start()

    def test_old_execution_migration_requires_mapping(self):
        with self.ledger.tx() as db:
            db.execute('CREATE TABLE execution_tasks(id TEXT)'); db.execute('INSERT INTO execution_tasks VALUES ("legacy")')
        with self.assertRaises(ValueError): self.start()

    def test_independent_actual_diff_and_tests(self):
        e,report=self.ready()
        self.assertEqual(report['files'],['calc.py']); self.assertEqual(report['tests'][0]['status'],'passed')
        self.assertEqual(report['tests'][0]['sha'],report['candidate'])

    def test_protected_change_detected_despite_worker_claim(self):
        e=self.start(); mirror,commit=candidate(self.root,self.source,self.base,e)
        repo=next(self.root.glob('worker-*/repo'))
        (repo/'.github').mkdir(); (repo/'.github/override').write_text('approve')
        git(repo,'add','.'); git(repo,'commit','-m','Protected attack')
        commit=git(repo,'rev-parse','HEAD')
        subprocess.run(['git','-C',str(mirror),'fetch',str(repo),'HEAD:refs/heads/attack'],check=True,capture_output=True)
        self.finalize(e); self.ledger.finish(e,commit)
        qa=IndependentQA(self.ledger,FixtureRunner(),self.issuer.reviewer)
        report,diff=qa.inspect(e,mirror)
        self.assertIn('Changed-file or protected-file policy',report['reasons'])
        self.assertFalse(report['tests'])

    def test_missing_forged_and_stale_qa(self):
        e=self.start(); self.finalize(e); self.ledger.finish(e,'a'*40)
        q=IndependentQA(self.ledger,FixtureRunner(),self.issuer.reviewer)
        forged=dict(run=e,candidate='a'*40,reasons=[],tests=[dict(sha='a'*40,status='passed')])
        with self.assertRaises(ValueError): q.accept(e,forged,{})
        with self.assertRaises(ValueError): Publisher(self.ledger,SyntheticGitHub(self.spec['repo'])).publish(e,self.grant())

    def test_qa_failing_tests(self):
        e=self.start(); self.finalize(e); self.ledger.finish(e,self.base)
        q=IndependentQA(self.ledger,FixtureRunner(),self.issuer.reviewer)
        report,diff=q.inspect(e,self.source)
        self.assertTrue(report['reasons'])

    def test_publication_requires_separate_grant(self):
        e,report=self.ready(); transport=SyntheticGitHub(self.spec['repo']); pub=Publisher(self.ledger,transport)
        with self.assertRaises(ValueError): pub.publish(e,self.grant())
        self.assertFalse(transport.calls)
        p=pub.publish(e,self.pubgrant(report))
        self.assertTrue(p['draft']); self.assertFalse(p['auto_merge'])
        self.assertEqual(pub.resume(e),p); self.assertEqual(transport.calls,['push','create'])

    def test_publication_api_failure_and_response_loss_recovery(self):
        e,report=self.ready(); transport=SyntheticGitHub(self.spec['repo'])
        transport.fail='auth'; pub=Publisher(self.ledger,transport)
        with self.assertRaises(ValueError): pub.publish(e,self.pubgrant(report))
        transport.fail='push'
        with self.assertRaises(ValueError): pub.resume(e)
        transport.fail='create'
        with self.assertRaises(ValueError): pub.resume(e)
        transport.fail=None; p=pub.resume(e)
        self.assertTrue(p['draft']); self.assertEqual(len(transport.prs),1)
        self.assertEqual(transport.calls.count('create'),1)

    def test_stale_remote_and_destination(self):
        e,report=self.ready(); transport=SyntheticGitHub('other/server'); pub=Publisher(self.ledger,transport)
        with self.assertRaises(ValueError): pub.publish(e,self.pubgrant(report))
        transport.repository=self.spec['repo']; transport.refs[self.spec['branch']]='b'*40
        with self.assertRaises(ValueError): pub.resume(e)
        self.assertFalse(transport.calls)

    def test_supervisor_timeout_cancel_crash_and_clean_env(self):
        sup=Supervisor()
        for kwargs in (dict(timeout=.08),dict(timeout=2,cancelled=lambda:True)):
            r=sup.run([sys.executable,'-c','import time;time.sleep(10)'],cwd=self.root,**kwargs)
            self.assertIn(r['reason'],('timeout','cancelled')); self.assertNotEqual(r['code'],0)
        r=sup.run([sys.executable,'-c','import sys;sys.exit(7)'],cwd=self.root,timeout=2)
        self.assertEqual(r['code'],7)
        os.environ['PRODUCTION_SECRET_TEST']='must-not-leak'
        try:
            r=sup.run([sys.executable,'-c',"import os; print('PRODUCTION_SECRET_TEST' in os.environ)"],cwd=self.root,timeout=2)
            self.assertEqual(r['stdout'].strip(),b'False')
        finally: del os.environ['PRODUCTION_SECRET_TEST']

    def test_sandbox_contract_no_credentials_network_or_shared_git(self):
        adapter=CodexAdapter(); root=adapter.checkout(self.source,self.base,self.root)
        self.assertFalse((root/'.git').exists()); self.assertEqual((root/'calc.py').read_text(),'def add(a,b): return a-b\n')
        cmd=adapter.sandbox('sandbox@sha256:'+'a'*64,root,'fc-'+'b'*32,adapter.command('pinned-model'))
        for flag in ('--network=none','--runtime=runsc','--read-only','--cap-drop=ALL','--pids-limit=128'):
            self.assertIn(flag,cmd)
        self.assertNotIn('OPENAI_API_KEY',' '.join(cmd))
        with self.assertRaises(ValueError): adapter.sandbox('sandbox:latest',root,'fc-'+'b'*32,('true',))

    def test_provider_telemetry_pricing_and_billing_limits(self):
        lines=[json.dumps(dict(type='thread.started',thread_id='thread')),json.dumps(dict(type='turn.completed',usage=dict(input_tokens=100,cached_input_tokens=10,output_tokens=20)))]
        usage=parse_events(lines,'execution','model','v1'); self.assertFalse(usage['billed'])
        for bad in ([],lines[:1],lines+[lines[-1]]):
            with self.assertRaises(ValueError): parse_events(bad,'execution','model')
        with self.assertRaises(ValueError): estimate(usage,{},self.now)
        price=dict(model='model',version='v1',verified=True,issued=self.now-1,expires=self.now+1,input_per_million='1',cached_per_million='.5',output_per_million='2')
        cost=estimate(usage,price,self.now); self.assertEqual(cost['kind'],'estimated'); self.assertFalse(cost['billed'])
        price['expires']=self.now
        with self.assertRaises(ValueError): estimate(usage,price,self.now)
        with self.assertRaises(ValueError): verify_authoritative_billing({},'execution',self.now)

    def test_merged_planning_history_reuses_original_fingerprint(self):
        p=self.root/'sprint51.db'; initialize(p)
        settings=read_json(ROOT/'config/settings.json')
        now=datetime.fromtimestamp(self.now,timezone.utc)
        original=plan(p,settings,[],now)
        l=Ledger(p,self.issuer.verifier,lambda:self.now,{'synthetic/server'},synthetic=True)
        self.assertEqual(l.plan(settings,[]),original)
        with l.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM daily_plans').fetchone()[0],1)

    def test_cross_midnight_reconciliation_is_charged_today(self):
        e=self.start(); self.now+=86400
        self.finalize(e)
        with self.ledger.tx() as db:
            self.assertEqual(self.ledger.accounting(db)[3],25)

    def test_deadline_cannot_be_extended(self):
        e=self.start()
        for _ in range(40):
            self.now+=59
            self.ledger.heartbeat(e,'coding:fixture')
        self.now+=41
        with self.assertRaises(ValueError): self.ledger.heartbeat(e,'coding:fixture')
        self.ledger.recover(); self.finalize(e)
        with self.assertRaises(ValueError): self.ledger.finish(e,'a'*40)

    def test_failing_candidate_test_evidence_blocks(self):
        e=self.start(); mirror,commit=candidate(self.root,self.source,self.base,e)
        repo=next(self.root.glob('worker-*/repo'))
        (repo/'calc.py').write_text('def add(a,b): return 0\n')
        git(repo,'add','.'); git(repo,'commit','-m','Wrong synthetic repair')
        commit=git(repo,'rev-parse','HEAD')
        subprocess.run(['git','-C',str(mirror),'fetch',str(repo),'HEAD:refs/heads/failing'],check=True,capture_output=True)
        self.finalize(e); self.ledger.finish(e,commit)
        qa=IndependentQA(self.ledger,FixtureRunner(),self.issuer.reviewer)
        report,diff=qa.inspect(e,mirror)
        self.assertEqual(report['tests'][0]['status'],'failed')
        with self.assertRaises(ValueError): qa.accept(e,report,{})

    def test_live_publication_cannot_be_enabled_by_transport(self):
        e,report=self.ready(); t=SyntheticGitHub(self.spec['repo']); t.synthetic=False
        with self.assertRaises(RuntimeError): Publisher(self.ledger,t).publish(e,self.pubgrant(report))
        self.assertFalse(t.calls)

    def test_qa_cannot_use_dispatch_operator_identity(self):
        e=self.start(); mirror,commit=candidate(self.root,self.source,self.base,e)
        self.finalize(e); self.ledger.finish(e,commit)
        q=IndependentQA(self.ledger,FixtureRunner(),self.issuer.reviewer)
        report,diff=q.inspect(e,mirror)
        binding=dict(run=e,report=digest(report),risks={r:'approved' for r in RISKS})
        with self.assertRaises(ValueError): q.accept(e,report,self.grant('qa',binding))
        changed=copy.deepcopy(report); changed['tests'][0]['status']='passed'; changed['diff']='forged'
        with self.assertRaises(ValueError): q.accept(e,changed,self.grant('qa',binding,qa=True))

    def test_ambiguous_create_never_blindly_retries(self):
        e,report=self.ready(); t=SyntheticGitHub(self.spec['repo']); pub=Publisher(self.ledger,t)
        def uncertain(*args):
            t.calls.append('create')
            raise ValueError('Connection lost before response; remote outcome unknown')
        t.create=uncertain
        with self.assertRaises(ValueError): pub.publish(e,self.pubgrant(report))
        with self.assertRaises(ValueError): pub.resume(e)
        self.assertEqual(t.calls.count('create'),1)

    def test_conflicting_observed_evidence_fences_candidate(self):
        e=self.start()
        self.ledger.record_usage(e,self.usage(e),self.issuer.verify_evidence)
        other=self.issuer.evidence(e,self.now,tokens=dict(input_tokens=999,output_tokens=20))
        self.assertFalse(self.ledger.record_usage(e,other,self.issuer.verify_evidence))
        self.ledger.terminated(e)
        self.ledger.finalize(e,self.issuer.billing(e,self.now,25),self.issuer.verify_billing)
        with self.assertRaises(ValueError): self.ledger.finish(e,'a'*40)

    def test_process_group_kills_descendant(self):
        pidfile=self.root/'child.pid'
        script="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); open(sys.argv[1],'w').write(str(p.pid)); time.sleep(30)"
        r=Supervisor().run([sys.executable,'-c',script,str(pidfile)],cwd=self.root,timeout=.25)
        self.assertEqual(r['reason'],'timeout')
        child=int(pidfile.read_text())
        status=Path('/proc')/str(child)/'status'
        if status.exists():
            # A reparented zombie is stopped; it cannot execute or retain a lease.
            self.assertIn('Z',next(line for line in status.read_text().splitlines() if line.startswith('State:')))

    def test_container_termination_must_be_verifiable(self):
        from unittest.mock import patch
        from codex_adapter import ContainerSupervisor
        empty=subprocess.CompletedProcess([],0,stdout=b'',stderr=b'')
        occupied=subprocess.CompletedProcess([],0,stdout=b'container-id',stderr=b'')
        with patch('codex_adapter.Supervisor.run',return_value={'code':0}), patch('codex_adapter.subprocess.run',side_effect=[empty,occupied]):
            with self.assertRaises(RuntimeError):
                ContainerSupervisor().run(('docker','run'),cwd=self.root,name='fc-'+'a'*32)

    def test_same_task_claim_is_serialized(self):
        g=self.grant()
        def dispatch(_):
            try: return self.ledger.dispatch(self.spec,g)
            except (ValueError,sqlite3.IntegrityError): return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(dispatch,range(4)))
        self.assertEqual(sum(e is not None for e in results),1)


if __name__=='__main__': unittest.main()
