"""Offline synthetic fixtures. No live adapter, credentials or operational ledger."""
import copy
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import contextlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_local_catalog as catalog_fixtures
from src import concurrency_coordinator as c
from src.local_runner import Runner, LocalCLI, git
from src.local_catalog import REPOSITORIES


def race_claim(config, task, slot, now):
    try: return c.Coordinator(config, lambda:now).claim(task, slot, 'process')['token']
    except ValueError: return None


class Fixture:
    def __init__(self, count=3):
        self.fixtures = []
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name); self.root.chmod(0o700)
        self.config = dict(schema=c.PROTOCOL, enabled=True, slots=3, live_limit=1, mode='synthetic-only',
            ledger=str(self.root/'coordinator.sqlite'), scratch=str(self.root/'scratch'), stop_files=[],
            max_tasks=100, max_artifact_bytes=1024*1024, max_storage_bytes=16*1024*1024)
        self.approvals = []; self.policies = []
        # Three disjoint fake repository identities ONLY in offline fixture scope.
        # Existing controller validation/prepare/approve is exercised unchanged.
        self.repo_patch = patch.dict(REPOSITORIES, {f'fixture-{i}': f'offline/repository-{i}' for i in range(count)})
        self.repo_patch.start()
        for i in range(count):
            f = catalog_fixtures.CatalogTests(); f.setUp(); self.fixtures.append(f)
            f.root.chmod(0o700)
            name = f'fixture-{i}'; identity = REPOSITORIES[name]
            p = f.config['repositories'].pop('fort-custer-server')
            p['identity'] = identity
            f.config['repositories'][name] = p
            git(p['source'], 'remote', 'set-url', 'origin', 'https://github.com/'+identity+'.git')
            entry = copy.deepcopy(f.entry()); task = f'task-{i}'
            entry.update(repo=name, repository=identity,
                issue_snapshot=dict(entry['issue_snapshot'], html_url=f'https://github.com/{identity}/issues/3'))
            f.config['catalog']['tasks'] = {task:entry}
            f.reload(); f.path.chmod(0o600)
            # The inherited controller fixture creates SQLite using the host's
            # defaults; coordinator evidence must be private regardless of umask.
            (Path(f.config['state'])/'local.sqlite').chmod(0o600)
            self.config['stop_files'].append(str(Path(f.config['state'])/'STOP'))
            self.approvals.append(f.approved(task)); self.policies.append(f.path)
        self.now = max(f.now for f in self.fixtures)
        self.coordinator = c.Coordinator(self.config, lambda:self.now)
        self.coordinator.initialize()

    def close(self):
        for f in self.fixtures: f.doCleanups()
        self.repo_patch.stop(); self.tmp.cleanup()

    def queue(self, i=0):
        r = self.approvals[i]
        return self.coordinator.enqueue(self.policies[i], r['id'], f'task-{i}')

    def claim(self, i=0, slot=None):
        self.queue(i)
        return self.coordinator.claim(f'task-{i}', slot or f'slot-{i+1}', f'worker-{i}')


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.addCleanup(self.f.close)
        self.co = self.f.coordinator

    def test_fixture_private_evidence_under_permissive_umask(self):
        previous = os.umask(0)
        try:
            fixture = Fixture(count=1)
            self.addCleanup(fixture.close)
            controller = fixture.fixtures[0]
            protected = [fixture.coordinator.path, controller.path,
                         Path(controller.config['state'])/'local.sqlite']
            for path in protected:
                with self.subTest(path=path.name):
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self.assertEqual(c.e.regular(path), path.absolute())
            for path in (fixture.root, controller.root,
                         Path(controller.config['state']), Path(controller.config['scratch'])):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            # Exercise the production permission validator during authorization too.
            self.assertEqual(fixture.claim()['task'], 'task-0')
        finally:
            os.umask(previous)

    def test_three_workers_and_verified_independent_evidence(self):
        claims = [self.f.claim(i) for i in range(3)]
        self.assertEqual(len({x['token'] for x in claims}),3)
        self.assertEqual(len({x['generation'] for x in claims}),3)
        self.assertEqual(len({x['slot'] for x in claims}),3)
        self.assertEqual(len(self.co.inspect()['tasks']),3)
        # Barrier demonstrates all three independently owned workspaces coexist.
        barrier = threading.Barrier(3); original = c.SyntheticWorker.run
        def work(worker, root, authorization):
            self.assertFalse((root/'.git').exists())
            barrier.wait(timeout=10)
            return original(worker, root, authorization)
        with patch.object(c.SyntheticWorker, 'run', work), patch.object(LocalCLI, 'run', side_effect=AssertionError('LIVE')):
            with ThreadPoolExecutor(3) as pool:
                results = list(pool.map(lambda claim:self.co.run_synthetic(claim,c.SyntheticWorker()),claims))
        self.assertEqual([x['state'] for x in results],['completed']*3)
        view = c.observations(self.f.config)
        self.assertFalse(view['authorization_authority'])
        self.assertFalse(view['executable_live']); self.assertEqual(view['live_limit'],1)
        paths = []
        for row in view['tasks'].values():
            event = next(x['document'] for x in row['events'] if x['kind']=='qa')
            paths.append(event['artifact']['checkout'])
            qa = row['events'][-1]['document']['qa']
            self.assertEqual(qa['token'],row['claim']['token'])
            self.assertFalse(qa['worker_reports_trusted'])
            self.assertEqual(qa['checks'][-1]['candidate_hash'],event['artifact']['candidate_manifest'])
        self.assertEqual(len(set(paths)),3)
        self.assertEqual(view['aggregate']['input_tokens'],9)
        self.assertEqual(view['aggregate']['cached_input_tokens'],3)
        self.assertEqual(view['aggregate']['output_tokens'],12)
        self.assertIn('hard_memory',view['unsupported'])

    def test_same_repository_queued_until_completion(self):
        f = self.f.fixtures[0]
        entry = copy.deepcopy(f.config['catalog']['tasks']['task-0'])
        f.config['catalog']['tasks']['second'] = entry
        # Policy revision must precede ALL grants/queue records.
        f.reload(); f.path.chmod(0o600)
        r = f.runner.inspect(self.f.approvals[0]['id'])
        # The old authorization is deliberately stale: use a fresh independent fixture task.
        second = f.approved('second')
        third = copy.deepcopy(entry); f.config['catalog']['tasks']['third'] = third
        f.reload(); f.path.chmod(0o600)
        # Recreate approvals with exact final policy through original controller, in temporary ledger.
        with f.runner.tx() as db: db.execute('DELETE FROM runs')
        first = f.approved('second'); other = f.approved('third')
        self.co.enqueue(f.path, first['id'],'second'); self.co.enqueue(f.path, other['id'],'third')
        claim = self.co.claim('second','slot-1','one')
        with self.assertRaises(ValueError): self.co.claim('third','slot-2','two')
        self.assertEqual(self.co.inspect()['tasks']['third']['state'],'queued')
        self.co.run_synthetic(claim,c.SyntheticWorker())
        self.assertEqual(self.co.claim('third','slot-2','two')['slot'],'slot-2')

    def test_same_task_race_threads(self):
        self.f.queue()
        def attempt(_):
            try:return self.co.claim('task-0','slot-1','worker')
            except ValueError:return None
        with ThreadPoolExecutor(8) as pool: results=list(pool.map(attempt,range(8)))
        self.assertEqual(sum(x is not None for x in results),1)

    def test_multiple_process_coordinators_same_slot(self):
        self.f.queue(0); self.f.queue(1)
        ctx = multiprocessing.get_context('fork')
        with ProcessPoolExecutor(2,mp_context=ctx) as pool:
            futures=[pool.submit(race_claim,self.f.config,f'task-{i}','slot-1',self.f.now) for i in range(2)]
            self.assertEqual(sum(x.result() is not None for x in futures),1)

    def test_duplicate_execution_and_task(self):
        self.f.queue()
        with self.assertRaises(ValueError): self.f.queue()
        with self.assertRaises(ValueError): self.co.enqueue(self.f.policies[0],self.f.approvals[0]['id'],'task-1')

    def test_unapproved_expired_and_advisory_rejected(self):
        f=self.f.fixtures[0]; r=self.f.approvals[0]
        with f.runner.tx() as db:
            saved=f.runner.read(db,r['id']); saved['state']='pending'; saved['history']=saved['history'][:1]; f.runner.save(db,saved)
        with self.assertRaises(ValueError): self.f.queue()
        with self.assertRaises(ValueError): self.co.enqueue(f.path,'advisory-plan','task-0')
        with f.runner.tx() as db: f.runner.save(db,r)
        self.f.now=r['expires']
        with self.assertRaises(ValueError): self.f.queue()

    def test_current_policy_digest_and_task_binding(self):
        self.f.queue()
        f=self.f.fixtures[0]
        f.config['catalog']['tasks']['task-0']['instructions']='changed'
        f.reload(); f.path.chmod(0o600)
        with self.assertRaises(ValueError): self.co.claim('task-0','slot-1','worker')

    def test_source_head_revision_conflict(self):
        self.f.queue(); f=self.f.fixtures[0]; source=f.config['repositories']['fixture-0']['source']
        git(source,'-c','user.name=Fixture','-c','user.email=f@local','commit','--allow-empty','-qm','moved')
        with self.assertRaises(ValueError): self.co.claim('task-0','slot-1','worker')

    def test_startup_rechecks_controller_authorization(self):
        claim=self.f.claim(); f=self.f.fixtures[0]
        with f.runner.tx() as db:
            r=f.runner.read(db,claim['execution']); r['state']='running'; f.runner.save(db,r)
        with self.assertRaises(ValueError): self.co.run_synthetic(claim,c.SyntheticWorker())
        self.assertEqual(self.co.inspect()['tasks']['task-0']['state'],'claimed')

    def test_restart_no_automatic_reassign_and_expiry_hold(self):
        claim=self.f.claim(); self.f.now=claim['deadline']+1
        other=c.Coordinator(self.f.config,lambda:self.f.now)
        with self.assertRaises(ValueError): other.claim('task-0','slot-2','other')
        other.sweep()
        self.assertEqual(other.inspect()['tasks']['task-0']['state'],'held')
        with self.assertRaises(ValueError): other.run_synthetic(claim,c.SyntheticWorker())
        self.assertEqual(other.inspect()['tasks']['task-0']['claim'],claim)

    def test_recovery_consumes_identity_fencing_replay(self):
        claim=self.f.claim(); self.co.hold(claim,'coordinator restart')
        with self.assertRaises(ValueError): self.co.recover(claim,'verified termination','yes')
        self.co.recover(claim,'Operator checked all processes and partial evidence','RECONCILE '+c.e.digest(claim))
        self.assertEqual(self.co.inspect()['tasks']['task-0']['state'],'interrupted')
        with self.assertRaises(ValueError): self.co.claim('task-0','slot-2','retry')
        with self.assertRaises(ValueError): self.co.run_synthetic(claim,c.SyntheticWorker())
        forged=dict(claim,token='a'*32)
        with self.assertRaises(ValueError): self.co.hold(forged,'replay')

    def test_stop_broken_link_prevents_claims_and_requests_cancel(self):
        claim=self.f.claim(); stop=Path(self.f.config['stop_files'][0]); stop.symlink_to(stop.parent/'missing')
        with self.assertRaises(ValueError): self.f.queue(1)
        with self.assertRaises(ValueError): self.co.run_synthetic(claim,c.SyntheticWorker())
        self.co.sweep(); row=self.co.inspect()['tasks']['task-0']
        self.assertEqual(row['state'],'held')
        self.assertTrue(row['events'][-1]['document']['cancellation'])
        self.assertEqual(row['events'][-1]['document']['termination'],'unconfirmed')

    def test_stop_during_worker_and_termination_uncertainty(self):
        claim=self.f.claim()
        def worker(*_): Path(self.f.config['stop_files'][0]).touch(); return {'exit_status':0}
        with patch.object(c.SyntheticWorker,'run',side_effect=worker):
            with self.assertRaises(ValueError): self.co.run_synthetic(claim,c.SyntheticWorker())
        self.assertEqual(self.co.inspect()['tasks']['task-0']['state'],'held')

    def test_cancel_queued_and_active(self):
        self.f.queue(0); claim=self.f.claim(1)
        self.co.cancel('task-0','operator cancellation'); self.co.cancel('task-1','operator cancellation')
        rows=self.co.inspect()['tasks']
        self.assertEqual(rows['task-0']['state'],'cancelled'); self.assertEqual(rows['task-1']['state'],'held')
        with self.assertRaises(ValueError): self.co.run_synthetic(claim,c.SyntheticWorker())

    def test_worker_crash_partial_write_outside_allowlist_and_deadline(self):
        for i in range(3):
            claim=self.f.claim(i)
            def worker(root,a):
                if i==0:
                    (root/a['allowed'][0]).write_text('partial')
                    raise RuntimeError('worker crash')
                if i==1:
                    (root/'outside.js').write_text('outside')
                    return dict(input_tokens=1,cached_input_tokens=0,output_tokens=1,exit_status=0)
                self.f.now=claim['deadline']+1
                return dict(input_tokens=1,cached_input_tokens=0,output_tokens=1,exit_status=0)
            with patch.object(c.SyntheticWorker,'run',side_effect=worker):
                with self.assertRaises((RuntimeError,ValueError)):self.co.run_synthetic(claim,c.SyntheticWorker())
            self.assertEqual(self.co.inspect()['tasks'][f'task-{i}']['state'],'held')

    def test_incomplete_qa_holds_and_artifacts_remain(self):
        claim=self.f.claim()
        with patch.object(Runner,'qa',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): self.co.run_synthetic(claim,c.SyntheticWorker())
        row=self.co.inspect()['tasks']['task-0']
        self.assertEqual(row['state'],'held'); self.assertTrue(any(x['kind']=='qa' for x in row['events']))

    def test_independent_qa_rejects_worker_test_report_and_bad_code(self):
        claim=self.f.claim()
        def worker(root,a):
            (root/a['allowed'][0]).write_text('invalid ! JavaScript')
            return dict(input_tokens=1,cached_input_tokens=0,output_tokens=1,exit_status=0,tests='passed')
        with patch.object(c.SyntheticWorker,'run',side_effect=worker):
            with self.assertRaises(ValueError): self.co.run_synthetic(claim,c.SyntheticWorker())
        self.assertEqual(self.co.inspect()['tasks']['task-0']['state'],'held')

    def test_immutable_artifacts_and_no_missing_reconstruction(self):
        claim=self.f.claim(); self.co.run_synthetic(claim,c.SyntheticWorker())
        with self.co.tx(True) as db:
            for statement in ('DELETE FROM events','UPDATE tasks SET document="{}"','DELETE FROM metadata'):
                with self.assertRaises(sqlite3.IntegrityError): db.execute(statement)
        row=self.co.inspect()['tasks']['task-0']; artifact=copy.deepcopy(next(x['document']['artifact'] for x in row['events'] if x['kind']=='qa'))
        artifact['candidate_manifest']='a'*64
        policy=self.f.fixtures[0].config
        with self.assertRaises(ValueError): c.verify_candidate(row['authorization'],artifact,policy,lambda:None,1024*1024,5)
        artifact['files']['outside.js']=[0o644,'00']
        with self.assertRaises(ValueError): c.verify_candidate(row['authorization'],artifact,policy,lambda:None,1024*1024,5)

    def test_disabled_and_unsafe_configuration(self):
        for key,value in [('slots',4),('live_limit',2),('mode','codex'),('enabled','true'),('max_tasks',True)]:
            with self.subTest(key=key),self.assertRaises(ValueError):c.Coordinator(dict(self.f.config,**{key:value}))
        disabled=c.Coordinator(dict(self.f.config,enabled=False))
        with self.assertRaises(ValueError): disabled.enqueue(self.f.policies[0],self.f.approvals[0]['id'],'task-0')
        with self.assertRaises(ValueError): disabled.inspect() # config digest change cannot bypass review

    def test_live_adapter_and_arbitrary_worker_rejected(self):
        claim=self.f.claim()
        class FakeLive:
            def run(self,*_): raise AssertionError('must not launch')
        for adapter in (FakeLive(),LocalCLI(self.f.fixtures[0].config)):
            with self.assertRaises(ValueError): self.co.run_synthetic(claim,adapter)
        class Subclass(c.SyntheticWorker): pass
        with self.assertRaises(ValueError):self.co.run_synthetic(claim,Subclass())

    def test_read_only_adapter_preserves_all_source_bytes(self):
        paths=[self.co.path,*self.f.policies,*[Path(f.config['state'])/'local.sqlite' for f in self.f.fixtures]]
        before={p:p.read_bytes() for p in paths}
        c.observations(self.f.config)
        self.assertEqual(before,{p:p.read_bytes() for p in paths})

    def test_unknown_schema_and_clock_regression(self):
        self.f.queue(); self.f.now-=60
        with self.assertRaises(ValueError): self.co.claim('task-0','slot-1','worker')
        with self.assertRaises(ValueError): c.Coordinator(dict(self.f.config,schema='future-v9'))

    def test_resource_ceiling_and_unavailable_metrics(self):
        claim=self.f.claim()
        def worker(root,a):
            (root/a['allowed'][0]).write_bytes(b'x'*self.f.config['max_artifact_bytes'])
            return dict(input_tokens=1,cached_input_tokens=0,output_tokens=1,exit_status=0)
        with patch.object(c.SyntheticWorker,'run',side_effect=worker):
            with self.assertRaises(ValueError):self.co.run_synthetic(claim,c.SyntheticWorker())
        self.assertIn('cpu_seconds',self.co.inspect()['tasks']['task-0']['unavailable_metrics'])

    def test_inspection_cli_is_read_only(self):
        path=self.f.root/'config.json'; path.write_text(json.dumps(self.f.config)); path.chmod(0o600)
        for command in ('slots','inspect','active','queued','completed','failed','resources'):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(c.main([command,'--config',str(path)]),0)
            self.assertIsNotNone(json.loads(output.getvalue()))

    def test_same_task_race_across_processes(self):
        self.f.queue()
        with ProcessPoolExecutor(2,mp_context=multiprocessing.get_context('fork')) as pool:
            jobs=[pool.submit(race_claim,self.f.config,'task-0',slot,self.f.now) for slot in ('slot-1','slot-2')]
            self.assertEqual(sum(job.result() is not None for job in jobs),1)

    def test_qa_termination_failure_retains_recovery_hold(self):
        claim=self.f.claim()
        with patch('src.local_runner.supervise',side_effect=TimeoutError('termination unconfirmed')):
            with self.assertRaises(TimeoutError):self.co.run_synthetic(claim,c.SyntheticWorker())
        row=self.co.inspect()['tasks']['task-0']
        self.assertEqual(row['state'],'held')
        self.assertEqual(row['events'][-1]['document']['termination'],'unconfirmed')
        self.assertEqual(row['usage']['exit_status'],0)
        self.assertIsNone(row['usage']['cpu_seconds'])

    def test_stop_during_qa_prevents_completion(self):
        claim=self.f.claim(); original=Runner.qa
        def qa(runner,*args,**kwargs):
            report=original(runner,*args,**kwargs)
            Path(self.f.config['stop_files'][0]).touch()
            return report
        with patch.object(Runner,'qa',qa):
            with self.assertRaises(ValueError):self.co.run_synthetic(claim,c.SyntheticWorker())
        self.assertEqual(self.co.inspect()['tasks']['task-0']['state'],'held')

    def test_failed_final_persistence_keeps_claim_and_candidate(self):
        claim=self.f.claim(); original=self.co._event
        def event(db,task,kind,doc):
            if kind=='completed':raise sqlite3.OperationalError('disk full')
            return original(db,task,kind,doc)
        with patch.object(self.co,'_event',side_effect=event):
            with self.assertRaises(sqlite3.OperationalError):self.co.run_synthetic(claim,c.SyntheticWorker())
        row=self.co.inspect()['tasks']['task-0']
        self.assertEqual(row['state'],'held')
        self.assertTrue(any(x['kind']=='qa' for x in row['events']))
        with self.assertRaises(ValueError):self.co.claim('task-0','slot-2','retry')

    def test_completed_source_evidence_and_legacy_protocol_unchanged(self):
        paths=[*self.f.policies,*[Path(f.config['state'])/'local.sqlite' for f in self.f.fixtures]]
        before={p:p.read_bytes() for p in paths}
        claim=self.f.claim();self.co.run_synthetic(claim,c.SyntheticWorker())
        self.assertEqual(before,{p:p.read_bytes() for p in paths})
        self.assertEqual(self.f.fixtures[0].runner.inspect(claim['execution'])['state'],'approved')
        from src.task_orchestration import coordinator_observations
        self.assertEqual(coordinator_observations(self.f.config)['schema'],c.OBSERVATIONS)

    def test_overwritten_artifact_fails_closed_even_with_sqlite_integrity(self):
        claim=self.f.claim();self.co.run_synthetic(claim,c.SyntheticWorker())
        # Simulate out-of-band privileged corruption, bypassing append-only protection.
        with self.co.tx(True) as db:
            db.execute('DROP TRIGGER immutable_events_UPDATE')
            row=db.execute("SELECT seq,document FROM events WHERE kind='qa'").fetchone()
            d=json.loads(row['document']);d['artifact']['candidate_manifest']='a'*64
            db.execute('UPDATE events SET document=? WHERE seq=?',(json.dumps(d),row['seq']))
        with self.assertRaises(ValueError):c.observations(self.f.config)

    def test_forged_history_and_generation_rejected(self):
        f=self.f.fixtures[0];r=self.f.approvals[0]
        with f.runner.tx() as db:
            r=copy.deepcopy(r);r['history'][1]['binding']='f'*64;f.runner.save(db,r)
        with self.assertRaises(ValueError):self.f.queue()
        claim=self.f.claim(1)
        with self.assertRaises(ValueError):self.co.run_synthetic(dict(claim,generation=999),c.SyntheticWorker())



if __name__=='__main__':unittest.main()
