import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/shared'), str(ROOT / 'workers/media')]
from video_service.capacity import audited_usage, used_bytes, reserve_workspace, StorageLimitError
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile
from video_service.storage import write_json_atomic
from media_worker.worker_storage import CapacityEstimate
from media_worker.process import run_process


class PipelinePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = FilesystemJobRepository(self.root)

    def job(self):
        return self.repo.create_job(original_filename='synthetic.mp4', expected_size=1000,
            source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED)

    def audit(self, age=0):
        write_json_atomic(self.root / '.storage-audit.json',
            {'used_bytes': 100, 'started_at': time.time() - age})

    def test_fresh_audit_bounds_active_growth_without_media_walks(self):
        self.audit()
        job = self.job()
        with patch('video_service.capacity.used_bytes', side_effect=AssertionError('media walk')), \
                patch('media_worker.worker_storage.used_bytes', side_effect=AssertionError('media walk')):
            self.assertGreaterEqual(audited_usage(self.root), 4100)
            estimate = CapacityEstimate(self.root)
            estimate.check(10**9, 0)
            with self.assertRaises(StorageLimitError):
                estimate.check(4000, 0)
            reserved = reserve_workspace(self.repo, job.job_id, 60, 10**9, 0)
            self.assertEqual(self.repo.read(job.job_id).metadata['reserved_bytes'], reserved)

    def test_missing_stale_or_future_audit_falls_back_to_scan(self):
        self.assertIsNone(audited_usage(self.root))
        for age in (601, -60):
            self.audit(age)
            self.assertIsNone(audited_usage(self.root))
            with patch('media_worker.worker_storage.used_bytes', return_value=1000) as scan:
                CapacityEstimate(self.root).check(2000, 0)
                scan.assert_called_once()

    def test_failed_reservation_keeps_record_unchanged(self):
        self.audit()
        job = self.job()
        with self.assertRaises(StorageLimitError):
            reserve_workspace(self.repo, job.job_id, 600, 5000, 0)
        self.assertNotIn('reserved_bytes', self.repo.read(job.job_id).metadata)

    def test_scandir_counts_nested_files_and_missing_root(self):
        (self.root / 'nested').mkdir()
        (self.root / 'nested/a').write_bytes(b'abc')
        (self.root / 'b').write_bytes(b'12345')
        self.assertEqual(used_bytes(self.root), 8)
        self.assertEqual(used_bytes(self.root / 'missing'), 0)

    def test_status_progress_does_not_reset_stage_clock(self):
        job = self.job()
        self.repo.update_status(job.job_id, JobStatus.ANALYZING)
        record = self.repo.read(job.job_id)
        started = record.metadata['stage_started_at']
        self.repo.update_status(job.job_id, JobStatus.ANALYZING, metadata={'stage_progress': .5})
        self.assertEqual(self.repo.read(job.job_id).metadata['stage_started_at'], started)
        self.repo.update_status(job.job_id, JobStatus.COMPLETED)
        self.assertIn('ANALYZING', self.repo.read(job.job_id).metadata['stage_durations_seconds'])

    def test_ordinary_queued_job_wakes_worker_after_publication(self):
        job = self.job()
        marker = self.root / '.faceswap-wakeup'
        self.assertFalse(marker.exists())
        self.repo.update_status(job.job_id, JobStatus.QUEUED)
        self.assertTrue(marker.exists())
        self.assertEqual(self.repo.read(job.job_id).status, JobStatus.QUEUED)

    def test_process_metrics_separate_control_work_and_exclude_arguments(self):
        run_process([sys.executable, '-c', 'import time; time.sleep(.1)'], cwd=self.root,
            log_name='probe.log', check=lambda: time.sleep(.05))
        data = json.loads((self.root / 'process-timings.jsonl').read_text())
        self.assertGreaterEqual(data['control_seconds'], .05)
        self.assertGreaterEqual(data['elapsed_seconds'], data['control_seconds'])
        self.assertEqual(data['returncode'], 0)
        self.assertNotIn('args', data)
