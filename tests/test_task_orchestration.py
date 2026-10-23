"""Offline controller fixtures, mock workers and GitHub reads; no live tasks."""
import ast
import copy
import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import test_catalog_promotion as promotion_fixture
import test_catalog_publication as publication_fixture
from src import task_orchestration as o
from src import orchestration_evidence as e
from src import catalog_promotion as promotion
from src.local_runner import LocalCLI, Runner, git, manifest, source_files
from src.catalog_publication import Publications


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.f=promotion_fixture.PromotionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root;self.f.store.path.chmod(0o600)
        self.execution=Path(self.f.policy['state'])/'local.sqlite';self.execution.chmod(0o600)
        self.policy=self.f.policy;self.path=self.f.policy_path
        self.c=dict(schema=o.PROTOCOL,ledger=str(self.root/'orchestration.sqlite'),policy=str(self.path),
                    discovery=str(self.f.store.path),promotion=str(self.f.ledger.path),execution=str(self.execution),
                    stop_files=self.f.stops,planning=dict(future_capacity=3,max_active_workers=1,max_recommendations=10,tasks={}))
        self.metadata();self.now=1000
        self.ledger=o.Ledger(self.c['ledger']);self.ledger.initialize()
        self.runner=Runner(self.path,self.policy['state'],lambda:self.now)
        self.config_path=self.root/'orchestration.json';self.write_config()

    def metadata(self):
        self.c['planning']['tasks']={i:dict(entry_digest=e.digest(v),priority=10 if i=='constant' else 5,
                                          risk='low',depends_on=[]) for i,v in self.policy['catalog']['tasks'].items()}

    def write_config(self):
        self.config_path.write_text(json.dumps(self.c));self.config_path.chmod(0o600)

    def view(self,remote=None):
        return o.reconcile(self.c,self.now,remote)[0]

    def row(self,identity='constant',remote=None):
        return next(t for t in self.view(remote)['tasks'] if t['id']==identity)

    def save_run(self,r):
        with self.runner.tx() as db:self.runner.save(db,r)

    def approved(self):
        r=self.runner.task_prepare('constant')
        return self.runner.approve(r['id'],'APPROVE '+r['binding'])

    def validated(self):
        r=self.approved()
        with patch.object(LocalCLI,'run',side_effect=self.f_worker):
            r=self.runner.execute(r['id'])
        self.assertEqual(r['state'],'validated',r)
        return r

    @staticmethod
    def f_worker(root,prompt,stopped,timeout):
        p=root/'tools/maze-analyzer/solver.js';p.write_text(p.read_text()+'\n// offline change\n')
        return dict(input_tokens=3,cached_input_tokens=0,output_tokens=4)

    def published(self):
        r=self.validated();publisher=Publications(self.runner);p=publisher.prepare(r['id'])
        remote=publication_fixture.Remote(p['request']);publisher.remote_inspect(p['id'],remote)
        publisher.approve(p['id'],'PUBLISH '+p['binding']);publisher.execute(p['id'],remote)
        def observe(repo,branch,number):
            return dict(repository=remote.identity,base=remote.base_sha,head=remote.branch,prs=copy.deepcopy(remote.rows))
        return r,p,remote,observe

    def test_complete_synthetic_lifecycle(self):
        self.assertEqual(self.row()['state'],'awaiting-coding-approval')
        self.assertTrue(any(t['state']=='proposed' for t in self.view()['tasks']))
        r=self.runner.task_prepare('constant');self.assertEqual(self.row()['state'],'awaiting-coding-approval')
        r=self.runner.approve(r['id'],'APPROVE '+r['binding']);self.assertEqual(self.row()['state'],'approved-for-coding')
        with patch.object(LocalCLI,'run',side_effect=self.f_worker):r=self.runner.execute(r['id'])
        self.assertEqual(self.row()['state'],'awaiting-publication-review')
        pub=Publications(self.runner);p=pub.prepare(r['id']);remote=publication_fixture.Remote(p['request'])
        self.assertEqual(self.row()['state'],'awaiting-publication-review')
        pub.remote_inspect(p['id'],remote);pub.approve(p['id'],'PUBLISH '+p['binding']);pub.execute(p['id'],remote)
        self.assertEqual(self.row()['state'],'published-draft-recorded')
        observe=lambda *a:dict(repository=remote.identity,base=remote.base_sha,head=remote.branch,prs=remote.rows)
        self.assertEqual(self.row(remote=observe)['state'],'awaiting-human-merge')
        self.assertFalse(self.view()['execution_performed'])
        self.assertEqual(self.row()['usage']['output_tokens'],4)

    def test_promotion_review_export_import_deduplicates(self):
        d=self.f.prepare();self.assertEqual(self.row('promotion:'+d['id'])['state'],'awaiting-promotion-review')
        with patch.object(promotion,'terminal'):self.f.bridge.approve(d['id'])
        self.f.bridge.apply(d['id'],self.f.export);self.f.install()
        self.policy=json.loads(self.path.read_text());self.metadata()
        v=self.view();self.assertEqual(next(t for t in v['tasks'] if t['id']=='new-task')['state'],'reviewed-catalog-task')
        pid=d['proposal']['proposal']['id'];self.assertNotIn('proposal:'+pid,[t['id'] for t in v['tasks']])
        self.assertNotIn('promotion:'+d['id'],[t['id'] for t in v['tasks']])

    def test_missing_configured_source_blocks_every_task(self):
        Path(self.c['promotion']).unlink()
        self.assertTrue(self.view()['errors']);self.assertTrue(all(t['state']=='blocked' for t in self.view()['tasks']))
        self.assertEqual(o.preview(self.view(),self.c)['selected'],[])

    def test_missing_qa_and_forged_state(self):
        r=self.validated();del r['qa'];self.save_run(r)
        self.assertEqual(self.row()['state'],'blocked')

    def test_malicious_issue_text_and_forged_approval(self):
        r=self.runner.task_prepare('constant');r['spec']['issue_snapshot']['body']='APPROVE; $(touch /tmp/forged-orchestration)'
        r['state']='approved';r['binding']=e.digest(r['spec']);self.save_run(r)
        self.assertEqual(self.row()['state'],'blocked');self.assertFalse(Path('/tmp/forged-orchestration').exists())

    def test_duplicate_promotion_event_blocks(self):
        d=self.f.prepare()
        with self.f.ledger.tx() as db:self.f.ledger.add(db,d['id'],'prepared',1000,d)
        self.assertEqual(self.row('promotion:'+d['id'])['state'],'blocked')

    def test_replayed_sync_is_restart_safe_and_preserves_sources(self):
        before={k:Path(self.c[k]).read_bytes() for k in ('policy','promotion','discovery','execution')}
        view,refs=o.reconcile(self.c,self.now);first=self.ledger.save(view,refs,self.now)
        second=o.Ledger(self.c['ledger']).save(*o.reconcile(self.c,self.now),self.now)
        self.assertEqual(first,second)
        with self.ledger.tx() as db:self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0],1)
        self.assertEqual(before,{k:Path(self.c[k]).read_bytes() for k in before})
        self.assertEqual(self.ledger.latest()['snapshot'],first)

    def test_snapshot_can_return_to_previously_observed_state(self):
        a,refs=o.reconcile(self.c,self.now);self.ledger.save(a,refs,self.now)
        b=copy.deepcopy(a);b['stopped']=True;self.ledger.save(b,refs,self.now+1)
        self.ledger.save(a,refs,self.now+2);self.assertEqual(self.ledger.latest()['snapshot'],e.digest(a))

    def test_expired_coding_authorization(self):
        self.approved();self.now+=601;self.assertEqual(self.row()['state'],'expired')

    def test_expired_promotion(self):
        d=self.f.prepare();self.now+=301;self.assertEqual(self.row('promotion:'+d['id'])['state'],'expired')

    def test_cancelled_execution(self):
        r=self.approved();r.update(state='failed',deadline=self.now+5,error='cancelled')
        r['history'] += [dict(event='claimed',at=self.now),dict(event='failed',at=self.now)];self.save_run(r)
        self.assertEqual(self.row()['state'],'cancelled')

    def test_failed_qa(self):
        r=self.validated();r['qa'][0]['code']=1;self.save_run(r);self.assertEqual(self.row()['state'],'blocked')

    def test_running_and_interrupted_claim_hold_capacity(self):
        r=self.approved();r.update(state='running',deadline=self.now+5);r['history'].append(dict(event='claimed',at=self.now));self.save_run(r)
        self.assertEqual(self.row()['state'],'running');self.assertEqual(o.preview(self.view(),self.c)['selected'],[])
        self.now+=6;self.assertEqual(self.row()['state'],'interrupted');self.assertEqual(o.preview(self.view(),self.c)['selected'],[])

    def test_interrupted_publication(self):
        r=self.validated();pub=Publications(self.runner);p=pub.prepare(r['id']);remote=publication_fixture.Remote(p['request'])
        pub.remote_inspect(p['id'],remote);pub.approve(p['id'],'PUBLISH '+p['binding'])
        pub.transition(p['id'],'approved','publishing')
        self.assertEqual(self.row()['state'],'ambiguous-publication')

    def test_changed_github_branch_and_pr_status(self):
        _,_,remote,observe=self.published()
        for change in ('head','closed','draft','duplicates','base'):
            original=copy.deepcopy(remote.rows);branch=remote.branch;base=remote.base_sha
            if change=='head':remote.branch='f'*40
            if change=='closed':remote.rows[0]['state']='closed'
            if change=='draft':remote.rows[0]['draft']=False
            if change=='duplicates':remote.rows*=2
            if change=='base':remote.base_sha='a'*40
            self.assertEqual(self.row(remote=observe)['state'],'blocked',change)
            remote.rows=original;remote.branch=branch;remote.base_sha=base

    def test_dependency_completion_fails_closed(self):
        self.c['planning']['tasks']['constant']['depends_on']=['test-case']
        p=o.preview(self.view(),self.c);self.assertNotIn('constant',[t['id'] for t in p['selected']])
        self.assertIn('test-case',[t['id'] for t in p['selected']])

    def test_dependency_cycle_and_missing_dependency(self):
        for deps in (['constant'],['missing']):
            self.c['planning']['tasks']['test-case']['depends_on']=deps
            self.c['planning']['tasks']['constant']['depends_on']=['test-case']
            self.assertEqual(o.preview(self.view(),self.c)['selected'],[])

    def test_repository_conflict_priority_and_cost_unknown(self):
        p=o.preview(self.view(),self.c);self.assertEqual([t['id'] for t in p['selected']],['constant'])
        self.assertEqual(p['selected'][0]['estimated_cost'],'unknown');self.assertEqual(p['max_active_workers'],1)
        self.assertIn('not a hard API-dollar',p['usage_policy'])
        self.assertFalse(p['selected'][0]['execution_authorized_by_preview'])

    def test_stop_state_blocks_all_and_does_not_clear(self):
        stop=Path(self.f.stops[0]);stop.touch()
        self.assertTrue(self.view()['stopped']);self.assertEqual(o.preview(self.view(),self.c)['selected'],[]);self.assertTrue(stop.exists())

    def test_capacity_configuration_rejects_more_than_one_active(self):
        self.c['planning']['max_active_workers']=3;self.write_config()
        with self.assertRaises(ValueError):o.config(self.config_path)
        self.c['planning']['max_active_workers']=True;self.write_config()
        with self.assertRaises(ValueError):o.config(self.config_path)

    def test_queue_determinism_pagination_and_bounds(self):
        v=self.view();self.assertEqual(o.queue(v),o.queue(self.view()))
        a=o.queue(v,0,1);b=o.queue(v,1,1);self.assertNotEqual(a['items'][0]['id'],b['items'][0]['id'])
        self.assertEqual(a['next_offset'],1)
        for limit in (0,101,True):
            with self.assertRaises(ValueError):o.queue(v,0,limit)

    def test_unknown_risk_and_stale_metadata_blocks_planning(self):
        del self.c['planning']['tasks']['constant'];self.assertEqual(self.row()['state'],'blocked')
        self.c['planning']['tasks']['test-case']['risk']='high'
        self.assertEqual(o.preview(self.view(),self.c)['selected'],[])

    def test_unknown_source_protocol(self):
        with sqlite3.connect(self.c['promotion']) as db:
            db.execute('DROP TRIGGER immutable_metadata_UPDATE');db.execute("UPDATE metadata SET schema='future-v9'")
        self.assertTrue(self.view()['errors'])

    def test_readonly_database_cannot_mutate(self):
        with e.readonly(self.c['promotion'],{'metadata','events'},'catalog-promotion-v1') as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute("INSERT INTO metadata VALUES ('forged')")

    def test_no_execution_approval_or_publication_capability_used(self):
        from src.local_publication import Publications as Legacy
        with patch.object(Runner,'__init__',side_effect=AssertionError('runner')), \
             patch.object(LocalCLI,'run',side_effect=AssertionError('execution')), \
             patch.object(Publications,'__init__',side_effect=AssertionError('publisher')), \
             patch.object(Legacy,'__init__',side_effect=AssertionError('publisher')), \
             patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network')):
            view,refs=o.reconcile(self.c,self.now);self.ledger.save(view,refs,self.now)
            o.preview(view,self.c);o.queue(self.ledger.latest());o.report(view)
        for module in (o,e):
            tree=ast.parse(Path(module.__file__).read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom):self.assertNotIn(n.module,('src.catalog_publication','src.local_publication','src.codex_adapter','src.execution'))
                if isinstance(n,ast.Attribute) and not (isinstance(n.value,ast.Name) and n.value.id=='db'):
                    self.assertNotIn(n.attr,('execute','approve','create_pr','create_branch','merge','deploy'))

    def test_legacy_sprint5_records_remain_unresolved_and_untouched(self):
        r=self.runner.prepare(3,'fort-custer-server',self.policy['catalog']['tasks']['constant']['issue_snapshot'])
        before=self.execution.read_bytes();v=self.view()
        legacy=next(t for t in v['tasks'] if t['id']=='execution:'+r['id'])
        self.assertEqual(legacy['state'],'blocked');self.assertEqual(before,self.execution.read_bytes())

    def test_modified_snapshot_or_missing_observation_is_rejected(self):
        view,refs=o.reconcile(self.c,self.now);self.ledger.save(view,refs,self.now)
        with sqlite3.connect(self.c['ledger']) as db:
            db.execute('DROP TRIGGER immutable_observations_DELETE');db.execute('DELETE FROM observations')
        with self.assertRaises(ValueError):self.ledger.latest()

    def test_ledger_is_exclusive_and_append_only(self):
        with self.assertRaises(FileExistsError):self.ledger.initialize()
        with self.ledger.tx(write=True) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM metadata')

    def test_clock_regression_and_future_approval(self):
        self.approved();self.now-=1;self.assertEqual(self.row()['state'],'blocked')
        v,refs=o.reconcile(self.c,1000);self.ledger.save(v,refs,1000)
        with self.assertRaises(ValueError):self.ledger.save(v,refs,999)

    def test_source_change_during_reconciliation_blocks(self):
        original=e.promotions
        def change(path):
            result=original(path);self.path.write_text(self.path.read_text()+' ');return result
        with patch.object(e,'promotions',side_effect=change):self.assertTrue(self.view()['errors'])

    def test_cli_inspection_and_reports_are_historical(self):
        view,refs=o.reconcile(self.c,self.now);self.ledger.save(view,refs,self.now)
        for command in ('queue','status','report','inspect'):
            output=io.StringIO();args=[command]+(['constant'] if command=='inspect' else [])+['--config',str(self.config_path)]
            with redirect_stdout(output):o.main(args)
            self.assertTrue(json.loads(output.getvalue())['historical_only'])

    def test_independent_client_repository_planning(self):
        source=self.root/'client';source.mkdir();(source/'demo.js').write_text('const x = 1;\n')
        git(source,'init','-q');git(source,'add','.')
        git(source,'-c','user.name=Fixture','-c','user.email=f@local','commit','-qm','client')
        identity='MZKZxyz/fort-custer-client';git(source,'remote','add','origin','https://github.com/'+identity+'.git')
        sha=git(source,'rev-parse','HEAD').decode().strip()
        self.policy['repositories']['fort-custer-client']=dict(identity=identity,source=str(source),sha=sha,branch='main',reviewed_issues=[7])
        entry=copy.deepcopy(self.policy['catalog']['tasks']['constant']);entry.update(repo='fort-custer-client',repository=identity,source=sha,
            input_hash=manifest(source_files(source,sha,['demo.js'])),issue=7,issue_snapshot=dict(number=7,state='open',html_url='https://github.com/'+identity+'/issues/7'),
            allowed=['demo.js'],checks=[dict(name='syntax',argv=['node','--check','demo.js'],timeout_seconds=3)])
        self.policy['catalog']['tasks']['client-demo']=entry;self.path.write_text(json.dumps(self.policy));self.metadata()
        p=o.preview(self.view(),self.c);self.assertEqual([t['id'] for t in p['selected']],['constant','client-demo'])
        self.assertEqual(p['max_active_workers'],1)
        self.c['planning']['max_recommendations']=1;self.assertEqual(len(o.preview(self.view(),self.c)['selected']),1)

    def test_expired_publication_is_not_approved(self):
        r=self.validated();pub=Publications(self.runner);pub.prepare(r['id']);self.now+=601
        self.assertEqual(self.row()['state'],'expired')

    def test_publication_cancelled(self):
        r=self.validated();pub=Publications(self.runner);p=pub.prepare(r['id']);pub.cancel(p['id'])
        self.assertEqual(self.row()['state'],'cancelled')

    def test_stale_source_specification(self):
        r=self.approved();r['spec']['source']='f'*40;r['binding']=e.digest(r['spec']);self.save_run(r)
        self.assertEqual(self.row()['state'],'blocked')

    def test_invalid_running_evidence_still_holds_global_capacity(self):
        r=self.approved();r['state']='running';self.save_run(r)
        self.assertEqual(self.row()['state'],'blocked')
        self.assertEqual(o.preview(self.view(),self.c)['selected'],[])

    def test_coding_approval_is_not_publication_authority(self):
        self.approved();self.assertEqual(self.row()['state'],'approved-for-coding')
        self.assertEqual(o.report(self.view())['qa_validations'],0)

    def test_duplicate_execution_claims_fail_closed(self):
        r=self.approved();r['id']='f'*32;self.save_run(r)
        self.assertEqual(self.row()['state'],'blocked')

    def test_forged_publication_branch_with_recomputed_binding(self):
        _,p,_,_=self.published()
        with sqlite3.connect(self.execution) as db:
            q=json.loads(db.execute('SELECT request FROM publications WHERE id=?',(p['id'],)).fetchone()[0])
            q['branch']='main'
            db.execute('UPDATE publications SET request=?,binding=? WHERE id=?',(e.canonical(q),e.digest(q),p['id']))
        self.assertEqual(self.row()['state'],'blocked')

    def test_missing_independent_approval_history(self):
        r=self.approved();r['history'][1]['binding']='f'*64;self.save_run(r)
        self.assertEqual(self.row()['state'],'blocked')

    def test_json_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):e.decode('{"state":"pending","state":"approved"}')

    def test_initialization_never_replaces_source_ledger(self):
        self.c['ledger']=self.c['execution'];self.write_config();before=self.execution.read_bytes()
        with self.assertRaises(ValueError):o.config(self.config_path)
        self.assertEqual(before,self.execution.read_bytes())

    def test_config_rejects_unknown_fields(self):
        self.c['approve']=True;self.write_config()
        with self.assertRaises(ValueError):o.config(self.config_path)

    def test_optional_github_reads_retained_as_immutable_evidence(self):
        _,_,_,observe=self.published();view,refs=o.reconcile(self.c,self.now,observe)
        self.assertTrue(any(doc['source']=='github' for doc in refs.values()))
        self.ledger.save(view,refs,self.now)
        self.assertEqual(next(t for t in self.ledger.latest()['tasks'] if t['id']=='constant')['state'],'awaiting-human-merge')

    def test_remote_read_failure_blocks_publication(self):
        self.published()
        def failed(*args):raise OSError('unavailable')
        self.assertEqual(self.row(remote=failed)['state'],'blocked')

    def test_symlink_source_is_rejected(self):
        link=self.root/'source-link';link.symlink_to(self.c['promotion']);self.c['promotion']=str(link)
        self.assertTrue(self.view()['errors'])

    def test_corrupted_export_receipt_blocks_promotion(self):
        d=self.f.exported()
        with self.f.ledger.tx() as db:
            db.execute('DROP TRIGGER immutable_events_UPDATE')
            db.execute("UPDATE events SET document=? WHERE id=? AND kind='exported'",(e.canonical(dict(path='/different',digest='f'*64)),d['id']))
        self.assertEqual(self.row('promotion:'+d['id'])['state'],'blocked')

    def test_real_promotion_clock_calls_can_differ(self):
        tick=[1000.0]
        def clock():
            tick[0]+=0.001
            return tick[0]
        self.f.bridge.clock=clock;d=self.f.prepare()
        with patch.object(promotion,'terminal'):self.f.bridge.approve(d['id'])
        self.now=1001
        self.assertEqual(self.row('promotion:'+d['id'])['state'],'awaiting-promotion-review')

    def test_promotion_replayed_under_another_identity(self):
        d=self.f.prepare()
        with self.f.ledger.tx() as db:self.f.ledger.add(db,'f'*32,'prepared',1000,d)
        self.assertEqual(self.row('promotion:'+'f'*32)['state'],'blocked')
