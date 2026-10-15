from pathlib import Path
from types import SimpleNamespace
import shutil
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/shared'), str(ROOT / 'apps/api')]
from app.services.storage_settings import inventory, cleanup
from app.api import settings_routes
from app.api.auth_routes import AuthConfig
from app.main import create_app
from fastapi.testclient import TestClient
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile
from video_service.locking import job_lock, download_lock
from video_service.auth import AuthStore


class StorageSettingsTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'data/test-runs' / uuid4().hex
        self.repo = FilesystemJobRepository(self.root)
        self.addCleanup(shutil.rmtree, self.root)
        self.config = SimpleNamespace(storage_root=self.root, service_quota_bytes=100000)

    def job(self, status=JobStatus.COMPLETED, owner=None):
        job = self.repo.create_job(original_filename='video.mp4', expected_size=100,
            source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED,
            metadata={'owner_id': owner})
        root = self.repo.job_dir(job.job_id)
        (root / 'input/source.mp4').write_bytes(b'source')
        (root / 'work/audio.wav').write_bytes(bytes(1234))
        (root / 'work/transcript.json').write_text('[]')
        (root / 'work/translated.json').write_text('[]')
        (root / 'output/final.mp4').write_bytes(b'result')
        return self.repo.update_status(job.job_id, status)

    def test_accounting_and_owner_visibility(self):
        mine = self.job()
        other = self.job(owner='other')
        result = inventory(self.config, None)
        self.assertEqual([j['job_id'] for j in result['jobs']], [mine.job_id])
        self.assertEqual(result['categories']['work'], 2 * 1238)
        self.assertEqual(result['jobs'][0]['temporary_bytes'], 1234)
        self.assertEqual(result['total_bytes'], sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()))
        self.assertGreater(result['disk']['total_bytes'], result['disk']['free_bytes'])
        response = cleanup(self.config, None, [other.job_id], 'jobs')
        self.assertEqual(response['results'][0]['status'], 'missing')
        self.assertTrue(self.repo.job_file(other.job_id).exists())

    def test_temporary_preserves_editing_and_outputs(self):
        job = self.job()
        directory = self.repo.job_dir(job.job_id)
        nested = directory / 'work/chunks'
        nested.mkdir()
        (nested / 'frame.png').write_bytes(bytes(20))
        result = cleanup(self.config, None, [job.job_id], 'temporary')
        self.assertEqual(result['removed_bytes'], 1254)
        self.assertEqual((directory / 'work/transcript.json').read_text(), '[]')
        self.assertTrue((directory / 'output/final.mp4').exists())
        self.assertTrue((directory / 'input/source.mp4').exists())
        self.assertEqual(cleanup(self.config, None, [job.job_id], 'temporary')['removed_bytes'], 0)

    def test_active_failed_and_download_protection(self):
        for status in (JobStatus.QUEUED, JobStatus.AWAITING_REVIEW, JobStatus.UPLOADING):
            job = self.job(status)
            self.assertEqual(cleanup(self.config, None, [job.job_id], 'jobs')['results'][0]['status'], 'active')
        failed = self.job(JobStatus.FAILED)
        self.assertEqual(cleanup(self.config, None, [failed.job_id], 'temporary')['removed_bytes'], 0)
        for lock in (download_lock(self.repo, failed.job_id), job_lock(self.repo, failed.job_id, 'execution')):
            with lock:
                self.assertEqual(cleanup(self.config, None, [failed.job_id], 'jobs')['results'][0]['status'], 'busy')
        self.assertGreater(cleanup(self.config, None, [failed.job_id], 'jobs')['removed_bytes'], 0)
        self.assertFalse(self.repo.job_dir(failed.job_id).exists())

    def test_host_disk_probe_optional(self):
        with patch.dict('os.environ', {'HOST_DISK_PROBE_PATH': str(self.root)}):
            result = inventory(self.config, None)
        self.assertEqual(result['host_disk']['total_bytes'], result['disk']['total_bytes'])

    def test_nested_junction_is_not_followed_or_deleted(self):
        job = self.job()
        outside = self.root / 'retained'
        outside.mkdir()
        valuable = outside / 'keep.bin'
        valuable.write_bytes(b'keep me')
        link = self.repo.job_dir(job.job_id) / 'work/linked'
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
            self.assertEqual(result.returncode, 0)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            self.assertEqual(inventory(self.config, None)['jobs'][0]['work'], 1238)
            for mode in ('temporary', 'jobs'):
                self.assertEqual(cleanup(self.config, None, [job.job_id], mode)['results'][0]['status'], 'error')
            self.assertEqual(valuable.read_bytes(), b'keep me')
        finally:
            if os.name == 'nt':
                link.rmdir()
            else:
                link.unlink()

    def test_full_delete_keeps_library_and_settings(self):
        job = self.job()
        library = self.root / '.assets'
        library.mkdir()
        (library / 'original.mp4').write_bytes(b'original')
        settings_file = self.root / '.preferences.json'
        settings_file.write_text('{}')
        self.assertEqual(cleanup(self.config, None, [job.job_id], 'jobs')['results'][0]['status'], 'cleaned')
        self.assertEqual((library / 'original.mp4').read_bytes(), b'original')
        self.assertTrue(settings_file.exists())

    def test_api_cleans_selected_job_and_refreshes_usage(self):
        app = create_app()
        app.state.auth = AuthConfig(None)
        client = TestClient(app)
        job = self.job()
        with patch.object(settings_routes, 'settings', self.config):
            before = client.get('/api/settings/storage').json()
            response = client.post('/api/settings/storage/cleanup', json={'mode': 'temporary', 'job_ids': [job.job_id]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['removed_bytes'], 1234)
            after = client.get('/api/settings/storage').json()
            self.assertEqual(before['categories']['work'] - after['categories']['work'], 1234)
            self.assertEqual(after['jobs'][0]['temporary_bytes'], 0)
            self.assertTrue(after['jobs'][0]['deletable'])
            response = client.post('/api/settings/storage/cleanup', json={'mode': 'jobs', 'job_ids': [job.job_id]})
            self.assertEqual(response.json()['results'][0]['status'], 'cleaned')
            self.assertEqual(client.get('/api/settings/storage').json()['jobs'], [])

    def test_api_validation_origin_and_auth(self):
        app = create_app()
        app.state.auth = AuthConfig(None)
        client = TestClient(app)
        job = self.job()
        with patch.object(settings_routes, 'settings', self.config):
            self.assertEqual(client.get('/api/settings/storage').status_code, 200)
            for ids in (['../outside'], [], [job.job_id] * 2):
                self.assertEqual(client.post('/api/settings/storage/cleanup', json={'mode': 'jobs', 'job_ids': ids}).status_code, 422)
            payload = {'mode': 'jobs', 'job_ids': [job.job_id]}
            self.assertEqual(client.post('/api/settings/storage/cleanup', json=payload, headers={'Origin': 'https://evil.example'}).status_code, 403)
            store = AuthStore(self.root / 'auth.sqlite3')
            store.create_user('alice', 'test-password-12345')
            app.state.auth = AuthConfig(store, secure=False)
            self.assertEqual(client.get('/api/settings/storage').status_code, 401)
            login = client.post('/api/auth/login', json={'username': 'alice', 'password': 'test-password-12345'})
            self.assertEqual(client.post('/api/settings/storage/cleanup', json=payload).status_code, 403)
            response = client.post('/api/settings/storage/cleanup', json=payload, headers={'X-CSRF-Token': login.json()['csrf_token']})
            self.assertEqual(response.json()['results'][0]['status'], 'missing')
            self.assertTrue(self.repo.job_file(job.job_id).exists())


if __name__ == '__main__':
    unittest.main()
