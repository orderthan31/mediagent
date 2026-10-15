from pathlib import Path
import shutil
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('workers/media', 'packages/shared')]
from media_worker.faceswap.retention import prune_previews
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile
from video_service.locking import job_lock


class PreviewRetentionTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'data/test-runs' / uuid4().hex
        self.repo = FilesystemJobRepository(self.root)
        self.addCleanup(shutil.rmtree, self.root)

    def job(self, operation='preview', status=JobStatus.COMPLETED, owner='a', session='s', preview=None):
        job = self.repo.create_job(original_filename='fixture', expected_size=1,
            source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED,
            metadata={'owner_id': owner, 'faceswap': {'session_id': session},
                      'faceswap_operation': operation, 'faceswap_request': {'preview_job_id': preview}})
        self.repo.update_status(job.job_id, status)
        return job.job_id

    def test_bounds_history_and_preserves_other_sessions_and_render(self):
        old = [self.job() for _ in range(5)]
        protected = [self.job(owner='b'), self.job(session='t'), self.job(operation='render'),
                     self.job(status=JobStatus.QUEUED)]
        prune_previews(self.repo, 's', 'a')
        remaining = {j.job_id for j in self.repo.list()}
        self.assertEqual(remaining, set(old[-2:] + protected))

    def test_keeps_last_success_after_failures_and_in_use_preview(self):
        referenced = self.job()
        locked = self.job()
        success = self.job()
        failures = [self.job(status=JobStatus.FAILED) for _ in range(3)]
        render = self.job(operation='render', status=JobStatus.QUEUED, preview=referenced)
        with job_lock(self.repo, locked, 'execution'):
            prune_previews(self.repo, 's', 'a')
        self.assertEqual({j.job_id for j in self.repo.list()},
                         {referenced, locked, success, render, *failures[-2:]})
        prune_previews(self.repo, 's', 'a')
        self.assertNotIn(locked, {j.job_id for j in self.repo.list()})
