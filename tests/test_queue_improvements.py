from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from contextlib import ExitStack
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/shared'), str(ROOT / 'apps/api'), str(ROOT / 'workers/media')]
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile
from video_service.queue_control import QueueControl, QueueConflict
from video_service.locking import job_lock
from video_service.job_index import indexed_jobs
from media_worker.worker import Worker
from media_worker.resources import job_resources, resource_slot
from media_worker.process import Cancelled
from media_worker.recovery import recover_interrupted


class QueueImprovementTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.repo = FilesystemJobRepository(self.root)
        patched = patch.object(routes, 'repository', self.repo)
        patched.start()
        self.addCleanup(patched.stop)
        self.client = TestClient(app)
        self.controls = QueueControl(self.root)

    def job(self, owner=None, status=JobStatus.QUEUED):
        record = self.repo.create_job(original_filename='synthetic.mp4', expected_size=3,
            source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED,
            metadata={'owner_id': owner, 'recovery_policy_version': 1})
        self.repo.source_path(record).write_bytes(b'abc')
        self.repo.update_status(record.job_id, status)
        return self.repo.read(record.job_id)

    def test_queue_order_pause_and_revision_are_persistent(self):
        first, second = self.job(), self.job()
        result = self.client.patch('/api/queue', json={'revision': 0, 'paused': True,
            'order': [second.job_id, first.job_id]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/queue').json()['jobs'], [second.job_id, first.job_id])
        self.assertTrue(QueueControl(self.root).read()['paused'])
        self.assertEqual(self.controls.ordered(self.repo.list()), [])
        conflict = self.client.patch('/api/queue', json={'revision': 0, 'paused': False})
        self.assertEqual(conflict.status_code, 409)
        self.assertNotIn('code', conflict.json())
        self.client.patch('/api/queue', json={'revision': 1, 'paused': False})
        self.assertEqual([j.job_id for j in self.controls.ordered(self.repo.list())], [second.job_id, first.job_id])

    def test_paused_queue_does_not_enter_worker_pipeline(self):
        job = self.job()
        self.controls.update(None, 0, paused=True)
        with patch('media_worker.worker.probe') as probe:
            Worker(self.repo, None).process(job.job_id)
        probe.assert_not_called()
        self.assertEqual(self.repo.read(job.job_id).status, JobStatus.QUEUED)

    def test_owner_isolation_and_batch_authorization_before_changes(self):
        own, foreign = self.job(), self.job('someone-else')
        self.assertEqual(self.client.get('/api/queue').json()['jobs'], [own.job_id])
        response = self.client.patch('/api/queue', json={'revision': 0, 'order': [foreign.job_id]})
        self.assertEqual(response.status_code, 404)
        response = self.client.post('/api/queue/cancel-pending', json={'job_ids': [own.job_id, foreign.job_id]})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.repo.read(own.job_id).status, JobStatus.QUEUED)

    def test_batch_cancels_only_pending_preserving_running_and_source(self):
        queued, running = self.job(), self.job(status=JobStatus.ENCODING)
        response = self.client.post('/api/queue/cancel-pending', json={'job_ids': [queued.job_id, running.job_id]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['cancelled'], [queued.job_id])
        self.assertEqual(response.json()['skipped'], [running.job_id])
        self.assertTrue(self.repo.source_path(queued).exists())
        self.assertEqual(self.repo.read(running.job_id).status, JobStatus.ENCODING)

    def test_reorder_rejects_started_and_duplicate_jobs(self):
        job = self.job(status=JobStatus.ENCODING)
        self.assertEqual(self.client.patch('/api/queue', json={'revision': 0, 'order': [job.job_id]}).status_code, 409)
        self.assertEqual(self.client.patch('/api/queue', json={'revision': 0, 'order': [job.job_id, job.job_id]}).status_code, 422)

    def test_simultaneous_queue_writers_have_one_winner(self):
        self.controls.update(None, 0)
        def update():
            try:
                QueueControl(self.root).update(None, 1, paused=True)
                return 'success'
            except QueueConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: update(), range(4)))
        self.assertEqual(outcomes.count('success'), 1)
        self.assertEqual(outcomes.count('conflict'), 3)

    def test_index_reconciles_updates_deletions_corruption_and_rebuild(self):
        first, second = self.job(), self.job()
        self.assertEqual(len(indexed_jobs(self.root)), 2)
        with patch('video_service.job_index.read_json', side_effect=AssertionError('unchanged JSON reread')):
            self.assertEqual(len(indexed_jobs(self.root)), 2)
        self.repo.update_status(first.job_id, JobStatus.COMPLETED)
        self.assertEqual(next(j for j in indexed_jobs(self.root) if j.job_id == first.job_id).status, JobStatus.COMPLETED)
        self.repo.job_file(second.job_id).write_text('{broken')
        self.assertEqual(len(indexed_jobs(self.root)), 1)
        (self.root / '.job-index.sqlite3').unlink()
        self.assertEqual(len(indexed_jobs(self.root)), 1)
        self.repo.delete_job_dir(first.job_id)
        self.assertEqual(indexed_jobs(self.root), [])

    def test_unavailable_index_falls_back_to_manifest(self):
        job = self.job()
        (self.root / '.job-index.sqlite3').write_bytes(b'not a database')
        with patch.dict(os.environ, {'JOB_INDEX_ENABLED': 'true'}):
            self.assertEqual(self.repo.list()[0].job_id, job.job_id)

    def test_native_database_directory_is_shared_but_separates_job_roots(self):
        from video_service.databases import database_path
        folder = self.root / 'native-db'
        uploads = self.root / '.uploads'
        uploads.mkdir()
        with patch.dict(os.environ, {'JOB_DATABASE_DIR': str(folder)}):
            main = database_path(self.root, 'queue-control')
            other = database_path(uploads, 'queue-control')
            self.assertEqual(main.parent, folder)
            self.assertNotEqual(main, other)
            QueueControl(self.root).update(None, 0, paused=True)
            self.assertTrue(QueueControl(self.root).read()['paused'])
            self.assertFalse(QueueControl(uploads).read()['paused'])
            self.assertEqual(len(indexed_jobs(self.root)), 0)

    def test_resource_limit_is_reentrant_and_bounds_concurrent_gpu_work(self):
        jobs = [self.job() for _ in range(4)]
        counts, maximum = 0, 0
        mutex = Lock()
        def operation(job):
            nonlocal counts, maximum
            with job_resources(self.repo, job.job_id), resource_slot('gpu'), resource_slot('gpu'):
                with mutex:
                    counts += 1
                    maximum = max(maximum, counts)
                time.sleep(.04)
                with mutex:
                    counts -= 1
        with patch.dict(os.environ, {'MAX_GPU_JOBS': '1'}), ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(operation, jobs))
        self.assertEqual(maximum, 1)
        self.assertTrue(any(self.repo.read(j.job_id).metadata.get('resource_wait_seconds', 0) > 0 for j in jobs))

    def test_resource_wait_is_cancellable_and_clears_wait_reason(self):
        first, second = self.job(), self.job()
        entered, finish = Event(), Event()
        def holder():
            with job_resources(self.repo, first.job_id), resource_slot('gpu'):
                entered.set()
                finish.wait(3)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(holder)
            self.assertTrue(entered.wait(2))
            def check():
                if self.repo.read(second.job_id).metadata.get('wait_reason'):
                    raise Cancelled()
            try:
                with job_resources(self.repo, second.job_id), self.assertRaises(Cancelled), resource_slot('gpu', check):
                    self.fail('must not acquire occupied GPU')
            finally:
                finish.set()
                future.result()
        self.assertIsNone(self.repo.read(second.job_id).metadata.get('wait_reason'))

    def test_io_can_run_while_gpu_is_occupied(self):
        first, second = self.job(), self.job()
        entered, finish = Event(), Event()
        def holder():
            with job_resources(self.repo, first.job_id), resource_slot('gpu'):
                entered.set()
                finish.wait(3)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(holder)
            self.assertTrue(entered.wait(2))
            try:
                with job_resources(self.repo, second.job_id), resource_slot('io'):
                    self.assertFalse(future.done())
            finally:
                finish.set()
                future.result()

    def test_scheduler_runs_bounded_jobs_and_collect_skips_live_executions(self):
        jobs = [self.job() for _ in range(3)]
        entered, finish, mutex = [], Event(), Lock()
        def process(worker, identity):
            with job_lock(worker.repository, identity, 'execution'):
                worker.repository.update_status(identity, JobStatus.ANALYZING)
                with mutex:
                    entered.append(identity)
                finish.wait(3)
                worker.repository.update_status(identity, JobStatus.COMPLETED)
        worker = Worker(self.repo, None)
        with patch.dict(os.environ, {'MAX_CONCURRENT_JOBS': '2', 'MAX_LLM_JOBS': '2'}), \
                patch('media_worker.faceswap.runner.refresh_capabilities'), \
                patch.object(Worker, 'process', process):
            try:
                worker.tick()
                deadline = time.monotonic() + 2
                while len(entered) < 2 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(len(entered), 2)
                worker.tick()
                self.assertEqual(len(entered), 2)
                self.assertEqual(sum(j.status == JobStatus.ANALYZING for j in self.repo.list()), 2)
            finally:
                finish.set()
                worker.close()

    def test_recovery_resumes_only_safe_interrupted_work_and_caps_attempts(self):
        job = self.job(status=JobStatus.ENCODING)
        with patch.dict(os.environ, {'AUTO_RESUME_INTERRUPTED': 'true', 'MAX_AUTO_RECOVERIES': '2'}):
            Worker(self.repo, None).collect(expire=False)
            record = self.repo.read(job.job_id)
            self.assertEqual(record.status, JobStatus.QUEUED)
            self.assertEqual(record.metadata['auto_recovery_count'], 1)
            record.metadata.update(auto_recovery_count=2)
            self.repo.save(record)
            self.repo.update_status(job.job_id, JobStatus.ENCODING)
            Worker(self.repo, None).collect(expire=False)
            self.assertTrue(self.repo.read(job.job_id).metadata['recovery_required'])

    def test_waiting_llm_jobs_do_not_block_independent_encode_admission(self):
        first, second, encoded = self.job(), self.job(), self.job()
        encoded.metadata['workflow'] = {'template': 'encode'}
        self.repo.save(encoded)
        started, finish = [], Event()
        def process(worker, identity):
            with job_lock(worker.repository, identity, 'execution'):
                worker.repository.update_status(identity, JobStatus.ANALYZING)
                started.append(identity)
                finish.wait(3)
                worker.repository.update_status(identity, JobStatus.COMPLETED)
        worker = Worker(self.repo, None)
        with patch.dict(os.environ, {'MAX_CONCURRENT_JOBS': '2', 'MAX_LLM_JOBS': '1'}), \
                patch('media_worker.faceswap.runner.refresh_capabilities'), patch.object(Worker, 'process', process):
            try:
                worker.tick()
                deadline = time.monotonic() + 2
                while len(started) < 2 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(set(started), {first.job_id, encoded.job_id})
                self.assertEqual(self.repo.read(second.job_id).status, JobStatus.QUEUED)
            finally:
                finish.set()
                worker.close()

    def test_recovery_never_automatically_replays_ambiguous_paid_or_old_failure(self):
        job = self.job(status=JobStatus.TRANSCRIBING)
        job.metadata['paid_operation_in_flight'] = True
        self.repo.save(job)
        old = self.job(status=JobStatus.FAILED)
        old.metadata.pop('recovery_policy_version')
        old.metadata['interrupted'] = True
        self.repo.save(old)
        with patch.dict(os.environ, {'AUTO_RESUME_INTERRUPTED': 'true'}):
            Worker(self.repo, None).collect(expire=False)
        self.assertEqual(self.repo.read(job.job_id).status, JobStatus.FAILED)
        self.assertTrue(self.repo.read(job.job_id).metadata['recovery_required'])
        self.assertEqual(self.repo.read(old.job_id).status, JobStatus.FAILED)

    def test_cancelled_interrupted_job_is_not_requeued(self):
        job = self.job(status=JobStatus.ENCODING)
        job.metadata['cancel_requested'] = True
        self.repo.save(job)
        with patch.dict(os.environ, {'AUTO_RESUME_INTERRUPTED': 'true'}):
            Worker(self.repo, None).collect(expire=False)
        self.assertEqual(self.repo.read(job.job_id).status, JobStatus.CANCELLED)
