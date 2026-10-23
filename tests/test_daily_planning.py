"""Offline cycles with real subsystem SQLite evidence and anonymous fake GETs."""
import ast
import copy
from datetime import datetime
import importlib
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import test_task_orchestration as fixtures
from test_issue_discovery import FakeReads, SERVER, CLIENT
from src import daily_planning as d
from src.discovery_collection import RateLimited, PublicGitHub


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OrchestrationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root=self.f.root
        self.out=self.root/'daily'; self.out.mkdir(mode=0o700)
        self.ledger=d.Cycles(self.out);self.ledger.initialize()
        self.discovery=self.out/'discovery.sqlite'
        self.discovery.write_bytes(self.f.f.store.path.read_bytes());self.discovery.chmod(0o600)
        self.o=copy.deepcopy(self.f.c);self.o['discovery']=str(self.discovery)
        self.op=self.root/'daily-observer.json';self.op.write_text(json.dumps(self.o));self.op.chmod(0o600)
        disc=json.loads((Path(__file__).parents[1]/'config/discovery.example.json').read_text())
        stops=sorted(set(self.f.f.stops+[str(Path(self.f.policy['state'])/'STOP')]))
        disc['stop_files']=stops
        self.c=dict(schema=d.PROTOCOL,enabled=False,timezone='America/Los_Angeles',local_start='09:00',
            max_duration_seconds=60,output=str(self.out),discovery_store=str(self.discovery),discovery=disc,
            orchestration=str(self.op),stop_files=stops,retain_reports=2,max_cycles=100,
            max_storage_bytes=16*1024*1024,max_report_bytes=1024*1024,retry_limit=0,backoff_seconds=0)
        self.cp=self.root/'daily.json';self.write_config()
        self.now=datetime.fromisoformat('2026-10-22T20:00:00+00:00').timestamp()
        self.mono=0;self.fake=FakeReads()
        self.fake.issues[SERVER].update(copy.deepcopy(self.f.f.fake.issues[SERVER]))

    def write_config(self):
        self.cp.write_text(json.dumps(self.c));self.cp.chmod(0o600)
        self.c,self.o,self.digest=d.configuration(self.cp)

    def run_cycle(self,**kw):
        return d.run(self.c,self.o,self.digest,transport=self.fake,clock=lambda:self.now,
                     monotonic=lambda:self.mono,**kw)

    def test_complete_real_reconciliation_and_report_integrity(self):
        result=self.run_cycle()
        self.assertEqual(result['status'],'complete',result)
        self.assertEqual(self.ledger.read_report(result['cycle_id']),result)
        self.assertTrue(result['advisory_only']);self.assertFalse(result['execution_performed'])
        self.assertTrue(result['new_or_revised_proposals'])
        self.assertTrue(result['tasks_awaiting_coding_approval'])
        self.assertTrue(result['tasks_awaiting_promotion_review'])
        self.assertEqual(result['planning_preview']['max_active_workers'],1)
        for p in self.out.iterdir():self.assertFalse(p.stat().st_mode & 0o077)
        (self.out/(result['cycle_id']+'.txt')).write_text('tampered')
        with self.assertRaises(ValueError):self.ledger.read_report(result['cycle_id'])

    def test_duplicate_no_network_or_conflicting_report(self):
        first=self.run_cycle(); calls=len(self.fake.calls)
        second=self.run_cycle()
        self.assertEqual(first['cycle_id'],second['cycle_id']);self.assertTrue(second['duplicate'])
        self.assertEqual(len(self.fake.calls),calls);self.assertEqual(len(self.ledger.history()),1)

    def test_identity_config_and_local_date(self):
        a=d.cycle_identity(self.c,self.digest,self.now)
        self.assertEqual(a,d.cycle_identity(self.c,self.digest,self.now+1))
        self.assertNotEqual(a,d.cycle_identity(self.c,'b'*64,self.now))
        self.assertNotEqual(a,d.cycle_identity(self.c,self.digest,self.now+86400))
        midnight=datetime.fromisoformat('2026-10-23T01:00:00+00:00').timestamp()
        self.assertEqual(d.cycle_identity(self.c,self.digest,midnight)[0],'2026-10-22')

    def test_dst_fold_one_cycle_and_gap_catchup(self):
        self.c.update(enabled=True,local_start='01:00')
        self.now=datetime.fromisoformat('2026-11-01T08:30:00+00:00').timestamp()
        first=self.run_cycle(scheduled=True)
        self.now+=3600
        self.assertTrue(self.run_cycle(scheduled=True)['duplicate'])
        self.assertEqual(first['local_planning_date'],'2026-11-01')
        self.c['local_start']='02:30'
        before=datetime.fromisoformat('2027-03-14T09:59:00+00:00').timestamp()
        self.now=before
        with self.assertRaises(ValueError):self.run_cycle(scheduled=True)
        self.now=before+60
        self.assertEqual(self.run_cycle(scheduled=True)['local_planning_date'],'2027-03-14')

    def test_disabled_schedule_manual_allowed(self):
        with self.assertRaises(ValueError):self.run_cycle(scheduled=True)
        self.assertEqual(self.ledger.history(),[])
        self.assertEqual(self.run_cycle()['status'],'complete')

    def test_no_backfill_missed_days_and_clock_regression(self):
        self.run_cycle(); self.now+=4*86400
        self.assertEqual(self.run_cycle()['status'],'complete')
        self.assertEqual(len(self.ledger.history()),2)
        self.now-=86400
        with self.assertRaises(ValueError):self.run_cycle()

    def test_restart_hold_requires_reason_and_never_retries_claim(self):
        day,identity=d.cycle_identity(self.c,self.digest,self.now)
        self.ledger.claim(identity,day,self.digest,self.now,100)
        self.assertEqual(self.run_cycle()['status'],'incomplete')
        self.now+=86400
        with self.assertRaises(ValueError):self.run_cycle()
        self.assertEqual(self.fake.calls,[])
        with self.assertRaises(ValueError):self.ledger.recover(identity,'')
        self.assertEqual(self.ledger.recover(identity,'Operator verified no active process')['state'],'interrupted')
        self.assertEqual(self.run_cycle()['status'],'complete')
        self.now-=86400
        self.assertEqual(self.run_cycle()['status'],'interrupted')

    def test_concurrent_lock_and_claim(self):
        with self.ledger.lock():
            with self.assertRaises(ValueError):self.run_cycle()
        day,identity=d.cycle_identity(self.c,self.digest,self.now)
        self.assertTrue(self.ledger.claim(identity,day,self.digest,self.now,100))
        self.assertFalse(self.ledger.claim(identity,day,self.digest,self.now,100))
        with self.ledger.lock():
            with self.assertRaises(ValueError):self.ledger.recover(identity,'active process')

    def test_network_rate_limit_and_timeout_durable_no_retry(self):
        for error in (RateLimited('untrusted secret'),TimeoutError('untrusted secret')):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.fake,'get',side_effect=error) as get:
                    result=self.run_cycle(); self.assertEqual(get.call_count,1)
                self.assertEqual(result['status'],'failed')
                self.assertIn('rolled back',result['github_collection']['status'])
                self.assertNotIn('untrusted secret',json.dumps(result))
                self.assertEqual(self.ledger.read_report(result['cycle_id']),result)
                self.now+=86400

    def test_partial_collection_rollback(self):
        before=self.discovery.read_bytes()
        original=self.fake.get
        def fail(repo,resource,query=None):
            if repo==CLIENT:raise TimeoutError()
            return original(repo,resource,query)
        with patch.object(self.fake,'get',side_effect=fail):result=self.run_cycle()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.discovery.read_bytes(),before)

    def test_missing_source_is_durable_and_blocks_preview(self):
        Path(self.o['promotion']).unlink()
        result=self.run_cycle()
        self.assertEqual(result['status'],'failed');self.assertFalse(result['planning_preview']['selected'])
        self.assertTrue(any('promotion' in error for error in result['errors']))
        self.assertEqual(self.ledger.read_report(result['cycle_id']),result)
        self.assertEqual(d.configuration(self.cp)[2],self.digest)

    def test_corrupt_policy_durable_before_any_reads(self):
        Path(self.o['policy']).write_text('broken')
        self.write_config()
        self.assertEqual(self.run_cycle()['status'],'failed');self.assertFalse(self.fake.calls)

    def test_source_changes_do_not_reuse_previous_success(self):
        self.assertEqual(self.run_cycle()['status'],'complete')
        self.now+=86400;Path(self.o['execution']).write_bytes(b'corrupt')
        result=self.run_cycle()
        self.assertEqual(result['status'],'failed');self.assertFalse(result['planning_preview']['selected'])

    def test_stop_initial_mid_scan_and_broken_link(self):
        stop=Path(self.c['stop_files'][0]);stop.parent.mkdir(parents=True,exist_ok=True)
        stop.symlink_to(stop.parent/'missing')
        result=self.run_cycle();self.assertEqual(result['status'],'failed');self.assertFalse(self.fake.calls)
        stop.unlink();self.now+=86400
        self.fake.interrupt=lambda *_:stop.touch()
        result=self.run_cycle();self.assertEqual(result['status'],'failed')
        self.assertEqual(len(self.fake.calls),1);self.assertTrue(result['stop_and_infrastructure']['stopped'])

    def test_clock_changes_during_collection_fail_closed(self):
        start=self.now
        self.fake.interrupt=lambda *_:setattr(self,'now',start-1)
        self.assertEqual(self.run_cycle()['status'],'failed')
        self.now=start+86400
        self.fake.interrupt=lambda *_:setattr(self,'now',start+86400+120)
        self.assertEqual(self.run_cycle()['status'],'failed')

    def test_unknown_ledger_version_never_migrates(self):
        with self.ledger.tx(True) as db:
            db.execute("UPDATE metadata SET schema='future-v9'")
        with self.assertRaises(ValueError):self.run_cycle()

    def test_duration_and_cancel(self):
        self.fake.interrupt=lambda *_:setattr(self,'mono',56)
        result=self.run_cycle();self.assertEqual(result['status'],'failed');self.assertEqual(len(self.fake.calls),1)
        self.now+=86400;self.mono=0
        self.assertEqual(self.run_cycle(cancelled=lambda:True)['status'],'failed')

    def test_periodic_supervisor_interrupts_blocking_adapter(self):
        def stop():raise TimeoutError('bounded')
        with self.assertRaises(TimeoutError):
            with d.deadline(stop):signal.pause()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))

    def test_request_bounds(self):
        self.c['discovery']['max_requests']=1
        result=self.run_cycle();self.assertEqual(result['status'],'failed');self.assertEqual(len(self.fake.calls),1)

    def test_storage_and_history_capacity(self):
        self.c['max_storage_bytes']=1024*1024
        result=self.run_cycle();self.assertEqual(result['status'],'failed');self.assertFalse(self.fake.calls)
        self.c['max_cycles']=1;self.now+=86400
        with self.assertRaises(ValueError):self.run_cycle()

    def test_success_retention_and_tombstones(self):
        first=self.run_cycle();self.now+=86400;self.run_cycle();self.now+=86400;self.run_cycle()
        self.assertEqual(len(list(self.out.glob('*.json'))),2)
        self.assertEqual(len(self.ledger.history()),3)
        with self.assertRaises(ValueError):self.ledger.read_report(first['cycle_id'])

    def test_retention_failure_visible_not_success(self):
        self.c['retain_reports']=1;self.run_cycle();self.now+=86400
        with patch.object(Path,'unlink',side_effect=OSError('disk')):
            result=self.run_cycle()
        self.assertEqual(result['status'],'failed');self.assertFalse(result['planning_preview']['selected'])

    def test_stop_during_final_report_write_leaves_no_success_receipt(self):
        original=d.atomic
        stop=Path(self.c['stop_files'][0])
        def activate(path,payload):
            original(path,payload)
            stop.touch()
        with patch.object(d,'atomic',side_effect=activate):
            with self.assertRaises(ValueError):self.run_cycle()
        self.assertEqual(self.ledger.history()[0]['state'],'incomplete')

    def test_report_disk_full_preserves_incomplete_claim(self):
        with patch.object(d,'atomic',side_effect=OSError('disk full')):
            with self.assertRaises(ValueError):self.run_cycle()
        self.assertEqual(self.ledger.history()[0]['state'],'incomplete')
        self.assertTrue(self.run_cycle()['duplicate'])

    def test_interrupted_second_report_write(self):
        original=d.atomic
        def fail(path,payload):
            if path.suffix=='.txt':raise OSError('disk full')
            original(path,payload)
        with patch.object(d,'atomic',side_effect=fail):
            with self.assertRaises(ValueError):self.run_cycle()
        self.assertEqual(len(list(self.out.glob('*.json'))),1)
        self.assertEqual(self.ledger.history()[0]['state'],'incomplete')
        with self.assertRaises(ValueError):self.ledger.read_report(self.ledger.history()[0]['id'])

    def test_report_bound_fails_without_success_receipt(self):
        self.c['max_report_bytes']=1024
        with self.assertRaises(ValueError):self.run_cycle()
        self.assertEqual(self.ledger.history()[0]['state'],'incomplete')

    def test_stop_cannot_be_output_and_scope_cannot_expand(self):
        for key,value in [('stop_files',[str(self.out/'STOP')]),('retry_limit',1),('enabled','true')]:
            original=self.c[key];self.c[key]=value
            self.cp.write_text(json.dumps(self.c))
            with self.assertRaises(ValueError):d.configuration(self.cp)
            self.c[key]=original
        self.c['discovery']['repositories']=['evil/repo'];self.cp.write_text(json.dumps(self.c))
        with self.assertRaises(ValueError):d.configuration(self.cp)

    def test_config_digest_binds_orchestration_content(self):
        self.o['planning']['max_recommendations']=2;self.op.write_text(json.dumps(self.o))
        self.assertNotEqual(self.digest,d.configuration(self.cp)[2])

    def test_source_evidence_unchanged(self):
        paths=[Path(self.o[k]) for k in ('policy','promotion','execution','ledger')]
        before={p:p.read_bytes() for p in paths}
        self.run_cycle()
        self.assertEqual(before,{p:p.read_bytes() for p in paths})

    def test_cli_history_report_and_failure_exit(self):
        result=self.run_cycle()
        for command in ('inspect','history','report'):
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(d.main([command,'--config',str(self.cp)]),0)
            self.assertTrue(json.loads(out.getvalue()))
        self.now+=86400
        with patch.object(d,'run',return_value={'status':'failed'}),redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(['run','--config',str(self.cp)]),1)

    def test_explicit_initialization_only_and_inert_template(self):
        self.c['output']=str(self.root/'new-daily')
        self.c['discovery_store']=str(self.root/'new-daily'/'discovery.sqlite')
        self.o['discovery']=self.c['discovery_store'];self.op.write_text(json.dumps(self.o))
        self.write_config()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(['init','--config',str(self.cp)]),0)
        self.assertEqual(d.Cycles(self.c['output']).history(),[])
        self.assertTrue(Path(self.c['discovery_store']).is_file())
        import plistlib
        project=Path(__file__).parents[1]
        template=plistlib.loads((project/'ops/com.fort-custer.daily-planning.plist.example').read_bytes())
        self.assertTrue(template['Disabled']);self.assertFalse(template['RunAtLoad']);self.assertFalse(template['KeepAlive'])
        self.assertNotIn('schedule:',(project/'.github/workflows/daily-planner.yml').read_text())
        self.assertFalse(json.loads((project/'config/daily-planning.example.json').read_text())['enabled'])

    def test_inspect_recovery_reason_is_visible(self):
        day,identity=d.cycle_identity(self.c,self.digest,self.now)
        self.ledger.claim(identity,day,self.digest,self.now,100)
        self.ledger.recover(identity,'Verified process exited')
        result=self.ledger.inspect(identity)
        self.assertEqual(result['state'],'interrupted')
        self.assertEqual(result['events'][-1]['document']['reason'],'Verified process exited')

    def test_physical_sqlite_page_cap_rolls_back(self):
        before=self.discovery.read_bytes()
        with self.assertRaises(sqlite3.Error):
            with d.BoundedDiscoveryStore(self.discovery,self.discovery.stat().st_size+4096).tx() as db:
                db.execute("INSERT INTO snapshots VALUES ('bounded',?)",('x'*1024*1024,))
        self.assertEqual(self.discovery.read_bytes(),before)

    def test_report_observes_real_qa_and_recorded_draft(self):
        self.f.published()
        result=self.run_cycle()
        self.assertEqual(result['status'],'complete',result)
        self.assertTrue(result['recorded_draft_prs'])
        self.assertGreater(result['evidence_summary']['resource_usage']['output_tokens'],0)
        row=next(t for t in result['tasks'] if t['id']=='constant')
        self.assertEqual(row['state'],'published-draft-recorded')
        self.assertTrue(row['qa_validated'])
        self.assertIn('current GitHub state unknown',row['required_action'])

    def test_reconciled_qa_failure_never_recommends(self):
        r=self.f.validated();r['qa'][0]['code']=1;self.f.save_run(r)
        result=self.run_cycle()
        self.assertIn('constant',result['qa_failures_and_blocked'])
        self.assertNotIn('constant',[t['id'] for t in result['planning_preview']['selected']])

    def test_no_privileged_module_imports_in_fresh_interpreter(self):
        code="""import sys
sys.path.insert(0,'tests')
import src.daily_planning as d
from test_issue_discovery import FakeReads, SERVER
c,o,h=d.configuration(CONFIG_PATH)
fake=FakeReads()
fake.issues[SERVER].update(ISSUES)
result=d.run(c,o,h,transport=fake,clock=lambda:EPOCH)
assert result['status']=='complete',result
for name in ('src.local_runner','src.catalog_promotion','src.catalog_publication','src.local_publisher','src.codex_adapter'):
 assert name not in sys.modules,name
""".replace('CONFIG_PATH',repr(str(self.cp))).replace('ISSUES',repr(self.f.f.fake.issues[SERVER])).replace('EPOCH',repr(self.now))
        subprocess.run([sys.executable,'-c',code],check=True)

    def test_no_action_network_or_credentials_capability(self):
        # Existing action APIs must remain unused even when they are available in this test process.
        with patch('src.local_runner.LocalCLI.run',side_effect=AssertionError('Codex')), \
             patch('src.catalog_promotion.Promotion.apply',side_effect=AssertionError('promotion')), \
             patch('src.catalog_publication.Publications.execute',side_effect=AssertionError('publish')), \
             patch.dict(os.environ,{'GITHUB_TOKEN':'PUBLISHER_SENTINEL'}):
            self.assertEqual(self.run_cycle()['status'],'complete')
        self.assertTrue(all(repo in {SERVER,CLIENT} for repo,_,_ in self.fake.calls))
        # Public transport constructs GET only and does not attach inherited publisher credentials.
        transport=PublicGitHub()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,n):self.limit=n;return b'[]'
        with patch.object(transport._opener,'open',return_value=Response()) as opened:
            transport.get(SERVER,'issues')
        request=opened.call_args.args[0]
        self.assertEqual(request.method,'GET');self.assertNotIn('Authorization',request.headers)
        self.assertEqual(opened.call_args.kwargs['timeout'],15)


if __name__=='__main__':unittest.main()
