"""WF08 authorization tests: temporary storage, no network/providers/worker."""
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


class AuthorizationTests(unittest.TestCase):
    def test_confirm_is_durable_idempotent_and_does_not_extend_expiry(self):
        from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict
        with tempfile.TemporaryDirectory() as root:
            clock=[1000.0];store=AuthorizationStore(root,'owner',clock=lambda:clock[0])
            context={'target':'work:a:start','source_sha256':'a'*64,'plan':'frozen','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm-1',context,True)
            self.assertEqual(grant['expires_at'],1900.0)
            self.assertEqual(grant['state'],'confirmed')
            clock[0]=1200
            self.assertEqual(store.confirm('confirm-1',context,True),grant)
            self.assertEqual(store.confirm('confirm-2',context,True)['expires_at'],1900.0)
            clock[0]=1900
            with self.assertRaises(AuthorizationConflict):store.claim(grant['id'],'run-1',context)
            self.assertEqual(store.confirm('confirm-1',context,True)['expires_at'],1900.0)
            new=store.confirm('confirm-3',context,True)
            self.assertNotEqual(new['id'],grant['id'])
            self.assertEqual(new['expires_at'],2800.0)
            self.assertEqual(AuthorizationStore(root,'owner',clock=lambda:clock[0]).get(grant['id'])['expires_at'],1900.0)

    def test_atomic_claim_replay_conflict_and_unknown_are_durable(self):
        from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict
        with tempfile.TemporaryDirectory() as root:
            store=AuthorizationStore(root,'owner');context={'target':'work:a:start','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True)
            barrier=Barrier(2)
            def claim():
                barrier.wait();return store.claim(grant['id'],'request',context)
            with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:claim(),range(2)))
            self.assertEqual(len({r['execution_id'] for r in results}),1)
            self.assertEqual(sum(not r['replay'] for r in results),1)
            with self.assertRaises(AuthorizationConflict):store.claim(grant['id'],'different',context)
            with self.assertRaises(AuthorizationConflict):store.claim(grant['id'],'request',{**context,'target':'other'})
            fresh=AuthorizationStore(root,'owner')
            self.assertTrue(fresh.claim(grant['id'],'request',context)['replay'])
            self.assertEqual(fresh.get(grant['id'])['state'],'claimed')

    def test_owner_scope_and_cost_classification_fail_closed(self):
        from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict
        with tempfile.TemporaryDirectory() as root:
            store=AuthorizationStore(root,'owner')
            for cost in ({}, {'state':'unknown'}, {'state':'free'}, {'state':'error'}):
                with self.subTest(cost=cost),self.assertRaises(AuthorizationConflict):store.confirm('x',{'target':'a','cost':cost},True)
            with self.assertRaises(AuthorizationConflict):store.confirm('x',{'target':'a','cost':{'state':'may_charge','amount':None}},False)
            grant=store.confirm('ok',{'target':'a','cost':{'state':'no_external_call','amount':None}},False)
            with self.assertRaises(FileNotFoundError):AuthorizationStore(root,'other').get(grant['id'])

    def test_external_request_is_recorded_before_send_and_never_replayed(self):
        from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict
        with tempfile.TemporaryDirectory() as root:
            store=AuthorizationStore(root,'owner');context={'target':'a','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context)
            request={'node':'n','generation':'g','input_sha256':'b'*64,'provider':'openai','model':'fixed','chunk':0}
            identity=store.before_external(claim['execution_id'],request)
            self.assertEqual(store.external_state(claim['execution_id'],identity)['state'],'unknown')
            fresh=AuthorizationStore(root,'owner')
            with self.assertRaises(AuthorizationConflict):fresh.before_external(claim['execution_id'],request)
            fresh.finish_external(claim['execution_id'],identity,'succeeded')
            with self.assertRaises(AuthorizationConflict):fresh.before_external(claim['execution_id'],request)
            other=fresh.before_external(claim['execution_id'],{**request,'chunk':1})
            self.assertNotEqual(identity,other)

    def test_consumed_execution_is_not_expired_or_refunded(self):
        from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict
        with tempfile.TemporaryDirectory() as root:
            clock=[0];store=AuthorizationStore(root,'owner',clock=lambda:clock[0]);context={'target':'a','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context)
            clock[0]=10000
            self.assertTrue(store.claim(grant['id'],'run',context)['replay'])
            store.finish(claim['execution_id'],{'status':'failed'})
            with self.assertRaises(AuthorizationConflict):store.claim(grant['id'],'new',context)
            self.assertEqual(store.claim(grant['id'],'run',context)['result'],{'status':'failed'})


    def test_sealed_legacy_inputs_and_worker_claim_are_durable_and_never_reentered(self):
        from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict
        with tempfile.TemporaryDirectory() as root:
            store=AuthorizationStore(root);context={'target':'legacy','cost':{'state':'may_charge','amount':None},'inputs':{'source':{'sha256':'a'*64,'bytes':1}}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context)
            store.seal_inputs(claim['execution_id'],{'source':'.execution-authorizations/public/inputs/sealed.mp4'})
            self.assertTrue(store.begin_worker(claim['execution_id']))
            with self.assertRaises(AuthorizationConflict):AuthorizationStore(root).begin_worker(claim['execution_id'])
            self.assertIn('source',store.execution(claim['execution_id'])['sealed_inputs'])


    def test_legacy_unknown_risk_ack_is_distinct_from_cost_confirmation(self):
        from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict
        with tempfile.TemporaryDirectory() as root:
            store=AuthorizationStore(root);context={'target':'legacy','risk_required':True,'cost':{'state':'may_charge','amount':None}}
            with self.assertRaises(AuthorizationConflict):store.confirm('confirm',context,True)
            grant=store.confirm('confirm-2',context,True,risk_confirmed=True)
            self.assertTrue(grant['risk_confirmed'])


    def test_legacy_cancel_blocks_new_logical_request_before_journal_and_transport(self):
        from video_service.execution_authorization import AuthorizationStore,AuthorizationConflict
        from video_service.repository import FilesystemJobRepository
        from video_service.models import JobStatus,QualityProfile
        with tempfile.TemporaryDirectory() as root:
            repo=FilesystemJobRepository(Path(root));job=repo.create_job(original_filename='fixture.mp4',expected_size=1,source_language='en',target_language='ko',quality_profile=QualityProfile.BALANCED)
            store=AuthorizationStore(root);context={'target':'/api/jobs/'+job.job_id+'/start','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context)
            store.seal_inputs(claim['execution_id'],{'source':'.execution-authorizations/public/input.fixture'})
            store.begin_worker(claim['execution_id'],job_id=job.job_id)
            job.status=JobStatus.CANCELLED;job.metadata['execution_authorization']={'execution_id':claim['execution_id']};repo.save(job)
            with self.assertRaises(AuthorizationConflict):store.before_external(claim['execution_id'],{'node':'TRANSCRIBING','generation':claim['execution_id'],'input_sha256':'a'*64,'provider':'openai','model':'fixed','chunk':0})
            self.assertEqual(store.execution(claim['execution_id'])['external_requests'],{})


class TransportAuthorizationTests(unittest.TestCase):
    def test_registered_invalid_response_remains_unknown_with_node_generation(self):
        from video_service.execution_authorization import AuthorizationStore, execution_scope, node_scope
        from media_worker.registered_nodes import RegisteredDecisionProvider
        from work_fixtures import WorkHarness
        with tempfile.TemporaryDirectory() as root:
            h=WorkHarness(root);binding=h.registry.resolve({'model_id':'c'*32,'revision':1},'decision')
            prefs={'model_binding':binding,'decision_provider':'openai','decision_model':'gpt-4o-mini','api_keys':{}}
            store=AuthorizationStore(root);context={'target':'test','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context);calls=[]
            def bad(*args):calls.append(1);return {'unexpected':'invalid'}
            with execution_scope(store,claim['execution_id']),node_scope('judge','generation-1'):
                with self.assertRaises(ValueError):RegisteredDecisionProvider(prefs,paid_allowed=True,transport=bad).decide({'input_sha256':'a'*64})
            attempts=store.execution(claim['execution_id'])['external_requests']
            self.assertEqual(len(attempts),1)
            row=next(iter(attempts.values()));self.assertEqual(row['state'],'unknown');self.assertEqual(row['request']['node'],'judge');self.assertEqual(row['request']['generation'],'generation-1')
            self.assertEqual(calls,[1])

    def test_guarded_gemini_request_does_not_fallback_or_retry(self):
        import asyncio
        from video_service.execution_authorization import AuthorizationStore, execution_scope, node_scope
        from media_worker.providers import GeminiProvider
        with tempfile.TemporaryDirectory() as root:
            prefs={'api_keys':{},'transcription_provider':'gemini','transcription_model':'fixed','transcription_fallback_provider':'gemini','transcription_fallback_model':'fallback','fallback_on_error':True}
            provider=GeminiProvider(prefs);calls=[]
            async def timeout(*args,**kwargs):calls.append(args[3]);raise TimeoutError('controlled unknown')
            provider._request_once=timeout
            store=AuthorizationStore(root);context={'target':'test','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context)
            with execution_scope(store,claim['execution_id']),node_scope('transcribe','g'):
                with self.assertRaises(TimeoutError):asyncio.run(provider._request([{'text':'input'}],{},lambda:None,'fixed',stt_language='en'))
            self.assertEqual(calls,['fixed'])
            self.assertEqual(len(store.execution(claim['execution_id'])['external_requests']),1)

    def test_guarded_segment_queue_does_not_automatically_retry_unknown(self):
        import asyncio
        from video_service.execution_authorization import AuthorizationStore, execution_scope
        from media_worker.transcription_queue import run_segment_queue, RetryableTranscriptionError, PartialTranscriptionError
        with tempfile.TemporaryDirectory() as root:
            store=AuthorizationStore(root);context={'target':'test','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context);calls=[]
            async def operation(index,attempt):calls.append((index,attempt));raise RetryableTranscriptionError('controlled unknown',delay=0)
            with execution_scope(store,claim['execution_id']):
                with self.assertRaises(PartialTranscriptionError):asyncio.run(run_segment_queue(1,operation,lambda:None,lambda *args,**kwargs:None,attempts=3))
            self.assertEqual(calls,[(0,1)])


    def test_direct_transport_entry_keeps_unknown_attempt_even_when_dispatch_is_disabled(self):
        import asyncio
        from video_service.execution_authorization import AuthorizationStore, execution_scope, node_scope
        from media_worker.translation_transport import request_provider
        with tempfile.TemporaryDirectory() as root:
            store=AuthorizationStore(root);context={'target':'test','cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context)
            with execution_scope(store,claim['execution_id']),node_scope('translate','g'):
                with self.assertRaises(RuntimeError):asyncio.run(request_provider('openai','','fixed',{'model':'fixed'},lambda:None,1,lambda *args:0,url='https://example.invalid',parse=lambda *args:{}))
            self.assertEqual(len(store.execution(claim['execution_id'])['external_requests']),1)
            self.assertEqual(next(iter(store.execution(claim['execution_id'])['external_requests'].values()))['state'],'unknown')


    def test_guarded_segment_cache_cannot_be_changed_and_silently_reused(self):
        import asyncio,json
        from video_service.execution_authorization import AuthorizationStore,execution_scope,AuthorizationConflict
        from media_worker.transcription_queue import run_segment_queue
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'queue.json';store=AuthorizationStore(root);context={'target':'test','options':{},'settings':{},'inputs':{'source':{'sha256':'a'*64}},'cost':{'state':'may_charge','amount':None}}
            grant=store.confirm('confirm',context,True);claim=store.claim(grant['id'],'run',context);calls=[]
            async def operation(index,attempt):calls.append(index);return {'text':'verified chunk'}
            with execution_scope(store,claim['execution_id']):
                asyncio.run(run_segment_queue(1,operation,lambda:None,lambda value:None,path=path))
                saved=json.loads(path.read_text());saved['results']['0']={'text':'unverified replacement'};path.write_text(json.dumps(saved))
                with self.assertRaises(AuthorizationConflict):asyncio.run(run_segment_queue(1,operation,lambda:None,lambda value:None,path=path))
            self.assertEqual(calls,[0])


    def test_installed_sdk_attempts_one_never_retries_500_or_timeout(self):
        import asyncio
        import httpx,tenacity
        from google.genai._api_client import retry_args
        from google.genai.errors import ServerError
        from google.genai.types import HttpRetryOptions
        for error in (ServerError(500,{'error':{'code':500,'message':'controlled fixture'}}),httpx.ReadTimeout('controlled fixture')):
            calls=[]
            async def operation():calls.append(1);raise error
            async def run():
                await tenacity.AsyncRetrying(**retry_args(HttpRetryOptions(attempts=1)))(operation)
            with self.assertRaises(type(error)):asyncio.run(run())
            self.assertEqual(calls,[1])


if __name__=='__main__':unittest.main()
