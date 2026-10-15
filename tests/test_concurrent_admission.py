import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('apps/api', 'packages/shared')]
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes, video_upload_routes
from app.services.upload_service import UploadService, UploadConflictError
from app.services.request_locks import admission_lock
from video_service.locking import job_lock, JobBusyError, async_job_lock
from video_service.repository import FilesystemJobRepository
from video_service.models import QualityProfile
from video_service.storage import write_json_atomic


class ConcurrentAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'data/test-runs' / uuid4().hex
        self.repo = FilesystemJobRepository(self.root)
        self.addCleanup(shutil.rmtree, self.root)

    def test_parallel_creates_wait_and_repeated_ids_do_not_duplicate(self):
        def slow_capacity(*args):
            time.sleep(.04)
        payloads = [{'filename': f'fixture-{i}.mp4', 'size': 4, 'request_id': str(uuid4())} for i in range(6)]
        def create(payload):
            return TestClient(app).post('/api/video-uploads', json=payload)
        with patch.object(routes, 'repository', self.repo), patch.object(video_upload_routes, 'assert_capacity', slow_capacity):
            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(create, payloads * 2))
        self.assertTrue(all(r.status_code == 201 for r in results), [r.text for r in results])
        self.assertEqual(len({r.json()['upload_id'] for r in results}), 6)
        self.assertEqual([r.json()['upload_id'] for r in results[:6]], [r.json()['upload_id'] for r in results[6:]])

    def test_recent_audit_admits_upload_without_recursive_scan(self):
        write_json_atomic(self.root / '.storage-audit.json', {'started_at': time.time(), 'used_bytes': 0})
        from types import SimpleNamespace
        settings = SimpleNamespace(max_upload_bytes=1000000, service_quota_bytes=10000000,
                                   min_free_space_bytes=0, storage_audit_interval_seconds=300)
        with patch.object(routes, 'repository', self.repo), patch.object(video_upload_routes, 'settings', settings), \
                patch('video_service.capacity.used_bytes', side_effect=AssertionError('recursive scan')):
            response = TestClient(app).post('/api/video-uploads', json={
                'filename': 'fixture.mp4', 'size': 100, 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)

    def test_busy_timeout_stays_typed_and_body_is_never_replayed(self):
        with job_lock(self.repo, '0' * 32), self.assertRaises(JobBusyError):
            with admission_lock(self.repo, timeout=.05):
                self.fail('Acquired a busy lock')
        calls = []
        with self.assertRaises(JobBusyError):
            with admission_lock(self.repo):
                calls.append(1)
                raise JobBusyError('inner lock')
        self.assertEqual(calls, [1])


class ConcurrentChunkTests(unittest.IsolatedAsyncioTestCase):
    async def test_competing_chunks_wait_without_blocking_or_duplicate_bytes(self):
        root = ROOT / 'data/test-runs' / uuid4().hex
        repo = FilesystemJobRepository(root)
        self.addCleanup(shutil.rmtree, root)
        job = repo.create_job(original_filename='fixture.mp4', expected_size=8, source_language='en',
                              target_language='ko', quality_profile=QualityProfile.BALANCED)
        service = UploadService(repo)
        entered = asyncio.Event()
        async def slow_body():
            entered.set()
            await asyncio.sleep(.1)
            yield b'abcd'
        async def duplicate_body():
            yield b'abcd'
        first = asyncio.create_task(service.append_chunk(job_id=job.job_id, expected_offset=0, body=slow_body()))
        await entered.wait()
        with self.assertRaises(UploadConflictError) as conflict:
            await service.append_chunk(job_id=job.job_id, expected_offset=0, body=duplicate_body())
        self.assertEqual(conflict.exception.expected_offset, 4)
        self.assertEqual(await first, 4)
        self.assertEqual(repo.source_path(job).read_bytes(), b'abcd')
        with job_lock(repo, job.job_id):
            async def wait():
                async with async_job_lock(repo, job.job_id):
                    self.fail('Cancelled waiter entered')
            waiter = asyncio.create_task(wait())
            await asyncio.sleep(.02)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
        with job_lock(repo, job.job_id):
            pass
