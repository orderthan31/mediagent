"""WF08 actual legacy API boundary; never touches the operating queue."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from video_service.repository import FilesystemJobRepository
from app.api import routes, asset_routes, workflow_routes


class LegacyApprovalApiTests(unittest.TestCase):
    def test_legacy_direct_api_requires_current_server_approval_and_exact_replay_does_not_requeue(self):
        from app.api.execution_approval_routes import router
        from video_service.execution_authorization import AuthorizationStore
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=FilesystemJobRepository(root);asset_id='b'*32
            asset=root/'.assets'/asset_id;asset.mkdir(parents=True);source=asset/'source.mp4';source.write_bytes(b'controlled fixture input')
            (asset/'asset.json').write_text(json.dumps({'asset_id':asset_id,'owner_id':None,'source_filename':'source.mp4','original_filename':'fixture.mp4','size_bytes':source.stat().st_size,'status':'ready'}))
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver']
            for r in (asset_routes.router,workflow_routes.router,router):app.include_router(r)
            config=SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0,storage_audit_interval_seconds=300)
            with patch.object(routes,'repository',repo),patch.object(workflow_routes,'settings',config),TestClient(app) as client:
                target='/api/videos/'+asset_id+'/jobs';payload={'request_id':str(uuid4()),'template':'transcribe','options':{}}
                self.assertEqual(client.post(target,json=payload).status_code,409)
                self.assertEqual(len(repo.list()),0)
                body={'path':target,'payload':payload}
                plan=client.post('/api/execution-approvals/plan',json=body)
                self.assertEqual(plan.status_code,200,plan.text)
                self.assertEqual(plan.json()['cost']['state'],'may_charge')
                self.assertIsNone(plan.json()['cost']['amount'])
                approval=client.post('/api/execution-approvals/confirm',json={**body,'token':plan.json()['token'],'request_id':str(uuid4()),'paid_confirmed':True})
                self.assertEqual(approval.status_code,200,approval.text)
                headers={'X-Execution-Approval':approval.json()['id'],'X-Execution-Request':payload['request_id']}
                created=client.post(target,json=payload,headers=headers)
                self.assertEqual(created.status_code,201,created.text)
                again=client.post(target,json=payload,headers=headers)
                self.assertEqual(again.status_code,201,again.text)
                self.assertEqual(again.json()['job_id'],created.json()['job_id'])
                self.assertEqual(len(repo.list()),1)
                mismatch=client.post(target,json={**payload,'template':'full'},headers=headers)
                self.assertEqual(mismatch.status_code,409)
                grant=AuthorizationStore(root).get(approval.json()['id'])
                self.assertEqual(grant['state'],'claimed')
                self.assertIn('execution_authorization',repo.read(created.json()['job_id']).metadata)


    def test_legacy_upload_start_and_retry_require_guard_and_do_not_requeue_exact_replay(self):
        from app.api.execution_approval_routes import router
        from video_service.models import JobStatus, QualityProfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=FilesystemJobRepository(root)
            job=repo.create_job(original_filename='fixture.mp4',expected_size=1,source_language='en',target_language='ko',quality_profile=QualityProfile.BALANCED)
            repo.source_path(job).write_bytes(b'v');job.uploaded_bytes=1;job.status=JobStatus.READY;repo.save(job)
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(routes.router);app.include_router(router)
            with patch.object(routes,'repository',repo),TestClient(app) as client:
                for operation,status in [('start',JobStatus.READY),('retry',JobStatus.FAILED)]:
                    repo.update_status(job.job_id,status)
                    path='/api/jobs/'+job.job_id+'/'+operation
                    self.assertEqual(client.post(path).status_code,409)
                    body={'path':path,'payload':{}}
                    plan=client.post('/api/execution-approvals/plan',json=body);self.assertEqual(plan.status_code,200,plan.text)
                    grant=client.post('/api/execution-approvals/confirm',json={**body,'token':plan.json()['token'],'request_id':str(uuid4()),'paid_confirmed':True});self.assertEqual(grant.status_code,200,grant.text)
                    headers={'X-Execution-Approval':grant.json()['id'],'X-Execution-Request':str(uuid4())}
                    queued=client.post(path,headers=headers);self.assertEqual(queued.status_code,200,queued.text)
                    retry_count=repo.read(job.job_id).metadata.get('retry_count',0)
                    repeated=client.post(path,headers=headers);self.assertEqual(repeated.status_code,200,repeated.text)
                    self.assertEqual(repo.read(job.job_id).metadata.get('retry_count',0),retry_count)


    def test_render_admission_binds_normalized_review_input_not_later_live_edits(self):
        from app.api.execution_approval_routes import router
        from video_service.execution_authorization import AuthorizationStore,AuthorizationConflict
        from video_service.execution_worker import legacy_execution,approved_review
        from video_service.models import JobStatus,QualityProfile
        from video_service.review import write_draft,draft_path
        from video_service.storage import write_json_atomic
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=FilesystemJobRepository(root)
            job=repo.create_job(original_filename='fixture.mp4',expected_size=1,source_language='en',target_language='ko',quality_profile=QualityProfile.BALANCED)
            repo.source_path(job).write_bytes(b'v');job.status=JobStatus.AWAITING_REVIEW;repo.save(job)
            tracks={name:[{'start':0.,'end':1.,'text':'approved '+name}] for name in ('original','translated')}
            write_draft(repo,job,tracks,2.,1)
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(routes.router);app.include_router(router)
            with patch.object(routes,'repository',repo),TestClient(app) as client:
                target='/api/jobs/'+job.job_id+'/subtitles';payload={'revision':1,'tracks':tracks,'action':'render'};body={'path':target,'payload':payload}
                self.assertEqual(client.put(target,json=payload).status_code,409)
                plan=client.post('/api/execution-approvals/plan',json=body);self.assertEqual(plan.status_code,200,plan.text)
                self.assertEqual(plan.json()['cost']['state'],'no_external_call')
                grant=client.post('/api/execution-approvals/confirm',json={**body,'token':plan.json()['token'],'request_id':str(uuid4()),'paid_confirmed':False});self.assertEqual(grant.status_code,200,grant.text)
                accepted=client.put(target,json=payload,headers={'X-Execution-Approval':grant.json()['id'],'X-Execution-Request':str(uuid4())});self.assertEqual(accepted.status_code,200,accepted.text)
            store=AuthorizationStore(root);execution=store.execution(store.get(grant.json()['id'])['execution_id'])
            approved=execution['context']['render_draft']
            changed={name:[{'start':0.,'end':1.,'text':'unapproved changed'}] for name in ('original','translated')}
            write_draft(repo,repo.read(job.job_id),changed,2.,3)
            with self.assertRaises(AuthorizationConflict):
                with legacy_execution(repo,repo.read(job.job_id)):pass
            write_json_atomic(draft_path(repo,job.job_id),approved)
            with legacy_execution(repo,repo.read(job.job_id)):
                write_draft(repo,repo.read(job.job_id),changed,2.,3)
                self.assertEqual(approved_review(repo,repo.read(job.job_id)),approved)


class NewWorkApprovalApiTests(unittest.TestCase):
    def test_same_size_mtime_bytes_change_is_rejected_and_the_actual_run_uses_the_sealed_input(self):
        import os
        from app.api.execution_approval_routes import router
        from app.api import settings_routes
        from video_service.workflow_definitions import DefinitionStore
        from work_fixtures import WorkHarness
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);h=WorkHarness(root)
            graph=dict(h.graph);identity=graph.pop('id');graph['revision']=0;DefinitionStore(root).save(identity,graph)
            asset=root/'.assets'/('b'*32);asset.mkdir(parents=True);source=asset/'source.mp4';original=b'controlled fixture input';source.write_bytes(original)
            (asset/'asset.json').write_text(json.dumps({'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'fixture.mp4','size_bytes':len(original),'status':'ready'}))
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver']
            app.include_router(settings_routes.router);app.include_router(router)
            def factory(*args):
                stat=source.stat();source.write_bytes(b'Z'*len(original));os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                return h.factory(*args)
            app.state.work_executor_factory=factory
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0)),TestClient(app) as client:
                selected={'definition_id':identity,'definition_revision':1,'asset_id':'b'*32,'options':{},'request_id':str(uuid4())}
                created=client.post('/api/settings/work-tickets',json=selected);self.assertEqual(created.status_code,201,created.text)
                ticket=created.json();self.assertIn('source_sha256',ticket['asset']);base='/api/settings/work-tickets/'+ticket['id'];plan=client.get(base+'/plan').json()
                confirmed=client.post(base+'/confirm',json={'revision':ticket['revision'],'token':plan['token'],'paid_confirmed':True});self.assertEqual(confirmed.status_code,200,confirmed.text)
                payload={'revision':confirmed.json()['revision'],'token':plan['token'],'request_id':str(uuid4())};body={'path':base+'/start','payload':payload}
                quote=client.post('/api/execution-approvals/plan',json=body);self.assertEqual(quote.status_code,200,quote.text)
                approval=client.post('/api/execution-approvals/confirm',json={**body,'token':quote.json()['token'],'request_id':str(uuid4()),'paid_confirmed':True});self.assertEqual(approval.status_code,200,approval.text)
                headers={'X-Execution-Approval':approval.json()['id'],'X-Execution-Request':payload['request_id']}
                stat=source.stat();source.write_bytes(b'X'*len(original));os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                rejected=client.post(base+'/start',json=payload,headers=headers);self.assertEqual(rejected.status_code,409,rejected.text)
                self.assertEqual(h.calls,[])
                source.write_bytes(original);os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                started=client.post(base+'/start',json=payload,headers=headers);self.assertEqual(started.status_code,200,started.text)
                self.assertEqual(started.json()['status'],'awaiting_decision',started.text)
                self.assertEqual(started.json()['source_sha256'],quote.json()['input_sha256'])
                self.assertEqual(len(h.calls),1)
                from video_service.execution_authorization import AuthorizationStore
                ledger=AuthorizationStore(root);grant=ledger.get(approval.json()['id']);attempts=ledger.execution(grant['execution_id'])['external_requests']
                self.assertEqual(len(attempts),1)
                self.assertEqual(next(iter(attempts.values()))['request']['node'],'judge')


if __name__=='__main__':unittest.main()
