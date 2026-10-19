from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import os
import shutil
import sys
import subprocess
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('apps/api', 'agents/media', 'packages/shared')]
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes, asset_routes, faceswap_routes
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile, utc_now_iso
from video_service.storage import write_json_atomic
from video_service.faceswap import FaceSwapSessions, reservation
from media_agent.agent import Agent


class FaceSwapTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'data/test-runs' / uuid4().hex
        self.repo = FilesystemJobRepository(self.root)
        self.addCleanup(shutil.rmtree, self.root)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(routes, 'repository', self.repo))
        self.stack.enter_context(patch.object(asset_routes, 'inspect_video', lambda _: {
            'duration': 1, 'has_audio': True, 'width': 320, 'height': 240, 'frame_rate': '5/1'}))
        self.stack.enter_context(patch.object(asset_routes, 'reserve_copy', lambda _: None))
        self.stack.enter_context(patch.object(faceswap_routes, 'capacity', lambda *args, **kwargs: None))
        self.stack.enter_context(patch.dict(os.environ, {'MIN_FREE_SPACE_BYTES': '0', 'FACEFUSION_ENABLED': 'false'}))
        self.client = TestClient(app)
        job = self.repo.create_job(original_filename='sample.mp4', expected_size=5,
                                  source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED)
        self.repo.source_path(job).write_bytes(b'video')
        self.repo.update_status(job.job_id, JobStatus.READY)
        self.asset = self.client.post(f'/api/jobs/{job.job_id}/register-source').json()
        self.cap()
        self.session = self.client.post(f"/api/videos/{self.asset['asset_id']}/faceswap-sessions",
                                       json={'request_id': str(uuid4())}).json()
        self.base = '/api/faceswap/sessions/' + self.session['session_id']
        image = BytesIO()
        Image.new('RGB', (64, 64), 'red').save(image, 'PNG')
        self.image = image.getvalue()

    def cap(self, **overrides):
        write_json_atomic(self.root / '.faceswap-capabilities.json', {
            'ready': True, 'fingerprint': 'engine1', 'presets': ['fast', 'balanced', 'quality'],
            'checked_at': utc_now_iso(), **overrides})

    def upload(self):
        response = self.client.post(self.base + f"/source?revision={self.session['revision']}", content=self.image)
        self.assertEqual(response.status_code, 200, response.text)
        self.session = response.json()
        self.session = self.client.put(self.base, json={'revision': self.session['revision'],
            'settings': {**self.session['settings'], 'source_position': 0, 'face_position': 0}}).json()

    def execute(self, operation, **extra):
        return self.client.post(self.base + '/requests', json={'request_id': str(uuid4()),
            'revision': self.session['revision'], 'operation': operation, **extra})

    def test_revision_source_validation_and_snapshot(self):
        bad = self.client.post(self.base + '/source?revision=0', content=b'not-image')
        self.assertEqual(bad.status_code, 422)
        self.upload()
        stale = self.client.put(self.base, json={'revision': 0, 'settings': self.session['settings']})
        self.assertEqual(stale.status_code, 409)
        job = self.execute('preview').json()
        snapshot = (self.repo.job_dir(job['job_id']) / 'input/source.jpg').read_bytes()
        self.upload()
        self.assertEqual((self.repo.job_dir(job['job_id']) / 'input/source.jpg').read_bytes(), snapshot)
        self.assertEqual(self.repo.read(job['job_id']).metadata['faceswap']['revision'], 2)

    def test_mask_validation_and_cursor_analysis_preserve_identity(self):
        self.upload()
        options = {**self.session['settings'], 'reference_frame': 3,
                   'mask_types': ['box', 'occlusion', 'area', 'region'],
                   'mask_areas': ['lower-face'], 'mask_regions': ['skin', 'nose'],
                   'mask_padding': [10, 20, 30, 40], 'detector_angles': [0, 90]}
        for invalid in ({'mask_types': []}, {'mask_types': ['polygon']}, {'mask_blur': .33},
                        {'mask_padding': [101, 0, 0, 0]}, {'mask_padding': [0]},
                        {'mask_areas': []}, {'mask_regions': ['invalid']}, {'detector_angles': [45]}):
            response = self.client.put(self.base, json={'revision': self.session['revision'], 'settings': {**options, **invalid}})
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.put(self.base, json={'revision': self.session['revision'], 'settings': options})
        self.assertEqual(response.status_code, 200, response.text)
        self.session = response.json()
        job = self.execute('analyze_reference', analysis_frame=5).json()
        self.assertEqual(job['metadata']['faceswap']['settings'], options)
        self.assertEqual(job['metadata']['analysis_frame'], 5)
        self.assertEqual(self.client.get(self.base).json()['settings']['reference_frame'], 3)

    def test_legacy_sessions_receive_mask_defaults_without_revision_change(self):
        store = FaceSwapSessions(self.repo)
        record = store.read_session(self.session['session_id'], self.session['owner_id'])
        record['settings'] = {'reference_frame': 7, 'face_position': 0, 'source_position': 0,
                              'distance': .3, 'preset': 'fast', 'video_codec': 'h264'}
        store.save_session(record)
        loaded = self.client.get(self.base).json()
        self.assertEqual(loaded['settings']['mask_types'], ['box'])
        self.assertEqual(loaded['settings']['reference_frame'], 7)
        self.assertEqual(loaded['revision'], record['revision'])

    def test_idempotency_request_limits_and_render_gate(self):
        self.upload()
        payload = {'request_id': str(uuid4()), 'revision': self.session['revision'], 'operation': 'preview'}
        first = self.client.post(self.base + '/requests', json=payload)
        second = self.client.post(self.base + '/requests', json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()['job_id'], second.json()['job_id'])
        self.assertEqual(self.client.post(self.base + '/requests', json={**payload, 'preview_frame': 2}).status_code, 409)
        self.assertEqual(self.execute('render').status_code, 422)
        self.assertEqual(self.execute('render', preview_job_id=first.json()['job_id']).status_code, 409)
        self.repo.update_status(first.json()['job_id'], JobStatus.COMPLETED)
        render = self.execute('render', preview_job_id=first.json()['job_id'])
        self.assertEqual(render.status_code, 202, render.text)
        self.assertFalse(render.json()['metadata']['internal'])
        self.cap(fingerprint='engine2')
        self.assertEqual(self.execute('render', preview_job_id=first.json()['job_id']).status_code, 409)

    def test_disabled_and_stale_capability_refuses_execution(self):
        self.cap(ready=False, reason='disabled')
        self.assertEqual(self.execute('analyze_reference').status_code, 503)
        self.cap(checked_at='2000-01-01T00:00:00+00:00')
        self.assertEqual(self.execute('analyze_reference').status_code, 503)

    def test_owner_isolation_for_sessions_and_files(self):
        store = FaceSwapSessions(self.repo)
        record = store.read_session(self.session['session_id'], None)
        record['owner_id'] = 'someone-else'
        store.save_session(record)
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.assertEqual(self.client.post(self.base + '/source?revision=0', content=self.image).status_code, 404)
        self.assertEqual(self.client.delete(self.base).status_code, 404)
        self.assertEqual(self.execute('analyze_reference').status_code, 404)

    def test_worker_skips_llm_and_publishes_preview(self):
        self.upload()
        response = self.execute('preview')
        job_id = response.json()['job_id']
        factory = Mock(side_effect=AssertionError('LLM must not be initialized'))
        def fake(payload, work, check, timeout):
            check()
            output = Path(payload['output'])
            output.mkdir()
            (output / 'preview.png').write_bytes(self.image)
            (output / 'original.png').write_bytes(self.image)
            write_json_atomic(output / 'result.json', {'matched_faces': 1})
        with patch('media_agent.faceswap.runner.invoke', side_effect=fake), patch.dict(os.environ, {'FACEFUSION_ENABLED': 'true'}), \
                patch('media_agent.agent.assert_capacity', side_effect=AssertionError('Preview must not scan the library')):
            Agent(self.repo, None, provider_factory=factory).process(job_id)
        self.assertEqual(self.repo.read(job_id).status, JobStatus.COMPLETED)
        factory.assert_not_called()
        self.assertEqual(self.client.get(f'/api/faceswap/jobs/{job_id}/files/preview.png').status_code, 200)
        self.assertEqual(self.client.get(f'/api/faceswap/jobs/{job_id}/files/source.jpg').status_code, 404)
        self.assertNotIn(job_id, [j['job_id'] for j in self.client.get('/api/jobs').json()['jobs']])
        record = self.repo.read(job_id)
        record.metadata['owner_id'] = 'another'
        self.repo.save(record)
        self.assertEqual(self.client.get(f'/api/faceswap/jobs/{job_id}/files/preview.png').status_code, 404)

    def test_cancel_failure_recovery_and_session_delete(self):
        job_id = self.execute('analyze_reference').json()['job_id']
        self.assertEqual(self.client.delete(self.base).status_code, 409)
        self.client.post(f'/api/jobs/{job_id}/cancel')
        Agent(self.repo, None).process(job_id)
        self.assertEqual(self.repo.read(job_id).status, JobStatus.CANCELLED)
        self.repo.update_status(job_id, JobStatus.FACE_SWAPPING)
        Agent(self.repo, None).collect(expire=False)
        self.assertEqual(self.repo.read(job_id).status, JobStatus.FAILED)
        self.assertTrue(self.repo.read(job_id).metadata['interrupted'])
        self.assertEqual(self.client.delete(self.base).status_code, 204)
        self.assertTrue(self.repo.source_path(self.repo.read(job_id)).is_file())

    def test_capacity_and_asset_deletion_protection(self):
        self.assertGreater(reservation(self.asset, True), self.asset['size_bytes'] * 4)
        from video_service.assets import AssetConflictError, VideoAssetRepository
        with self.assertRaises(AssetConflictError):
            VideoAssetRepository(self.repo).delete(self.asset['asset_id'])
        from video_service.capacity import StorageLimitError
        with patch.object(faceswap_routes, 'capacity', side_effect=StorageLimitError('full')):
            self.assertEqual(self.execute('analyze_reference').status_code, 507)

    def test_unselected_faces_and_expired_preview_are_rejected(self):
        self.upload()
        preview = self.execute('preview').json()
        self.repo.update_status(preview['job_id'], JobStatus.COMPLETED,
                                metadata={'results_expired_at': utc_now_iso()})
        self.assertEqual(self.execute('render', preview_job_id=preview['job_id']).status_code, 409)
        self.session = self.client.put(self.base, json={'revision': self.session['revision'],
            'settings': {**self.session['settings'], 'source_position': -1}}).json()
        self.assertEqual(self.execute('preview').status_code, 422)

    def test_no_match_preview_cannot_start_full_render(self):
        self.upload()
        preview = self.execute('preview').json()
        self.repo.update_status(preview['job_id'], JobStatus.COMPLETED,
                                metadata={'faceswap_result': {'matched_faces': 0}})
        self.assertEqual(self.execute('render', preview_job_id=preview['job_id']).status_code, 409)


class FaceSwapProcessTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'data/test-runs' / uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.pid_file = self.root / 'grandchild.pid'
        self.script = self.root / 'tree.py'
        self.script.write_text(
            'import subprocess,sys,time\nfrom pathlib import Path\n'
            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])\n'
            f'Path({str(self.pid_file)!r}).write_text(str(child.pid))\n'
            'time.sleep(60)\n', encoding='utf-8')

    def assert_child_stopped(self):
        pid = int(self.pid_file.read_text())
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x100000, False, pid)
            if handle:
                try:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 3000), 0)
                finally:
                    kernel.CloseHandle(handle)
        else:
            for _ in range(30):
                stat = Path(f'/proc/{pid}/stat')
                if not stat.exists() or stat.read_text().split()[2] == 'Z':
                    return
                time.sleep(.1)
            self.fail('Engine grandchild remained alive')

    def test_cancel_and_timeout_stop_process_tree(self):
        from media_agent.faceswap.process import run
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                self.pid_file.unlink(missing_ok=True)
                def check():
                    if cancel and self.pid_file.exists():
                        raise RuntimeError('cancelled')
                with self.assertRaises(RuntimeError if cancel else TimeoutError):
                    run([sys.executable, str(self.script)], cwd=self.root, env=os.environ.copy(),
                        log=self.root / 'engine.log', check=check, timeout=3)
                self.assertTrue(self.pid_file.is_file())
                self.assert_child_stopped()

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Object parent-death guarantee')
    def test_worker_death_stops_process_tree(self):
        wrapper = self.root / 'worker.py'
        wrapper.write_text(
            'import os,sys\nfrom pathlib import Path\n'
            f'sys.path.insert(0, {str(ROOT / "agents/media")!r})\n'
            'from media_agent.faceswap.process import run\n'
            f'run([sys.executable,{str(self.script)!r}],cwd=Path({str(self.root)!r}),'
            f'env=os.environ.copy(),log=Path({str(self.root / "parent.log")!r}),'
            'check=lambda:None,timeout=60)\n', encoding='utf-8')
        parent = subprocess.Popen([sys.executable, str(wrapper)])
        try:
            deadline = time.monotonic() + 10
            while not self.pid_file.exists() and time.monotonic() < deadline:
                time.sleep(.1)
            self.assertTrue(self.pid_file.exists())
        finally:
            parent.kill()
            parent.wait(timeout=5)
        self.assert_child_stopped()


if __name__ == '__main__':
    unittest.main()
