"""Real Agent.process with isolated storage and a stopping CPU probe, no daemon/GPU/provider."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import routes,asset_routes,workflow_routes
from app.api.execution_approval_routes import router
from video_service.repository import FilesystemJobRepository
from video_service.llm_settings import LLMSettingsStore
from video_service.models import JobStatus
from video_service.execution_authorization import AuthorizationStore
from media_agent.agent import Agent


class LegacyWorkerAuthorizationTests(unittest.TestCase):
    def test_actual_worker_uses_sealed_source_and_requeued_same_claim_never_reenters(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=FilesystemJobRepository(root);asset=root/'.assets'/('b'*32);asset.mkdir(parents=True)
            source=asset/'source.mp4';source.write_bytes(b'v');(asset/'asset.json').write_text(json.dumps({'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'fixture.mp4','size_bytes':1,'status':'ready'}))
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver']
            for r in (asset_routes.router,workflow_routes.router,router):app.include_router(r)
            settings=SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0,storage_audit_interval_seconds=300)
            with patch.object(routes,'repository',repo),patch.object(workflow_routes,'settings',settings),TestClient(app) as client:
                path='/api/videos/'+('b'*32)+'/jobs';payload={'request_id':str(uuid4()),'template':'extract_audio','options':{'audio_filter':'off'}};body={'path':path,'payload':payload}
                plan=client.post('/api/execution-approvals/plan',json=body);self.assertEqual(plan.status_code,200,plan.text)
                approval=client.post('/api/execution-approvals/confirm',json={**body,'token':plan.json()['token'],'request_id':str(uuid4()),'paid_confirmed':False});self.assertEqual(approval.status_code,200,approval.text)
                created=client.post(path,json=payload,headers={'X-Execution-Approval':approval.json()['id'],'X-Execution-Request':payload['request_id']});self.assertEqual(created.status_code,201,created.text)
                job_id=created.json()['job_id']
            source.write_bytes(b'X')
            seen=[]
            def probe(path,*args):seen.append(Path(path).read_bytes());raise RuntimeError('controlled stop before media processing')
            provider=SimpleNamespace(preferences=LLMSettingsStore(root).resolve(None))
            worker=Agent(repo,provider)
            with patch('media_agent.agent.probe',probe),patch('media_agent.agent.job_resources',lambda *args:nullcontext()):
                worker.process(job_id)
                self.assertEqual(seen,[b'v'])
                grant=AuthorizationStore(root).get(approval.json()['id']);execution=AuthorizationStore(root).execution(grant['execution_id'])
                self.assertTrue(execution['worker_started'])
                repo.update_status(job_id,JobStatus.QUEUED)
                worker.process(job_id)
                self.assertEqual(seen,[b'v'])
                self.assertEqual(repo.read(job_id).status,JobStatus.FAILED)
                self.assertTrue(repo.read(job_id).metadata['recovery_required'])


    def test_guarded_interrupted_job_is_not_automatically_requeued_even_if_auto_resume_is_enabled(self):
        from media_agent.recovery import recover_interrupted
        from video_service.models import QualityProfile
        with tempfile.TemporaryDirectory() as directory:
            repo=FilesystemJobRepository(Path(directory));job=repo.create_job(original_filename='fixture.mp4',expected_size=1,source_language='en',target_language='ko',quality_profile=QualityProfile.BALANCED)
            repo.source_path(job).write_bytes(b'v');job.status=JobStatus.FAILED;job.metadata.update(recovery_policy_version=1,interrupted=True,execution_authorization={'execution_id':'a'*32});repo.save(job)
            with patch.dict('os.environ',{'AUTO_RESUME_INTERRUPTED':'true'}):self.assertTrue(recover_interrupted(repo,job))
            self.assertEqual(repo.read(job.job_id).status,JobStatus.FAILED)
            self.assertTrue(repo.read(job.job_id).metadata['recovery_required'])


    def test_guarded_checkpoint_same_size_mtime_corruption_is_blocked_not_reexecuted(self):
        import os
        from video_service.execution_authorization import AuthorizationStore,execution_scope,AuthorizationConflict
        from media_agent.checkpoints import Checkpoints
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';work.mkdir();calls=[]
            store=AuthorizationStore(root);context={'target':'legacy','options':{},'settings':{},'inputs':{'source':{'sha256':'a'*64}},'cost':{'state':'no_external_call','amount':None}}
            grant=store.confirm('confirm',context,False);claim=store.claim(grant['id'],'run',context)
            def operation():calls.append(1);(work/'result.fixture').write_bytes(b'abc');return {'known':'result'}
            with execution_scope(store,claim['execution_id']):
                checkpoints=Checkpoints(work,{'fixed':1},lambda size:None)
                checkpoints.run('step',operation,('result.fixture',))
                original=(work/'result.fixture').stat();(work/'result.fixture').write_bytes(b'xyz');os.utime(work/'result.fixture',ns=(original.st_atime_ns,original.st_mtime_ns))
                with self.assertRaises(AuthorizationConflict):checkpoints.run('step',operation,('result.fixture',))
            self.assertEqual(calls,[1])


if __name__=='__main__':unittest.main()
