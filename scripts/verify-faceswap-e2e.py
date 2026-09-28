"""Opt-in local GPU integration check. Requires public FaceFusion example fixtures.

Set FACEFUSION_ENABLED/PATH/PYTHON. Creates a new isolated data directory.
Never reads existing user jobs, calls LLM providers, or downloads models.
"""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('apps/api', 'workers/media', 'packages/shared')]
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile
from video_service.faceswap import public_capabilities
from media_worker.worker import Worker
from media_worker.faceswap.runner import refresh_capabilities
from media_worker.media import executable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--multi', action='store_true', help='Swap panel order halfway through a two-person clip')
    args = parser.parse_args()
    root = ROOT / 'data/facefusion-e2e' / uuid4().hex
    root.mkdir(parents=True)
    repo = FilesystemJobRepository(root / 'jobs')
    fixture = ROOT / 'data/facefusion-fixtures'
    target = root / 'target.mp4'
    if args.multi:
        from PIL import Image, ImageOps
        frame = root / 'target.png'
        subprocess.run([executable('ffmpeg'), '-v', 'error', '-i', str(fixture / 'target.mp4'),
                        '-frames:v', '1', str(frame)], check=True)
        left = ImageOps.pad(Image.open(fixture / 'source.jpg').convert('RGB'), (320, 240))
        right = ImageOps.pad(Image.open(frame).convert('RGB'), (320, 240))
        for i in range(10):
            combined = Image.new('RGB', (640, 240))
            combined.paste(left if i < 5 else right, (0, 0))
            combined.paste(right if i < 5 else left, (320, 0))
            combined.save(root / f'frame-{i:02d}.png')
        subprocess.run([executable('ffmpeg'), '-v', 'error', '-framerate', '5', '-i', str(root / 'frame-%02d.png'),
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-t', '2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(target)], check=True)
    else:
        subprocess.run([executable('ffmpeg'), '-v', 'error', '-i', str(fixture / 'target.mp4'),
                        '-t', '1', '-vf', 'fps=5', '-c:v', 'libx264', '-c:a', 'aac', str(target)], check=True)
    refresh_capabilities(repo, Event(), force=True)
    cap = public_capabilities(repo.storage_root)
    assert cap['ready'], cap
    with patch.object(routes, 'repository', repo):
        client = TestClient(app)
        def api(method, path, **kwargs):
            response = client.request(method, '/api' + path, **kwargs)
            assert response.is_success, response.text
            return response.json() if response.content else None
        upload = repo.create_job(original_filename='facefusion-example.mp4', expected_size=target.stat().st_size,
            source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED)
        repo.source_path(upload).write_bytes(target.read_bytes())
        repo.update_status(upload.job_id, JobStatus.READY)
        asset = api('POST', f'/jobs/{upload.job_id}/register-source')
        session = api('POST', f"/videos/{asset['asset_id']}/faceswap-sessions", json={'request_id': str(uuid4())})
        base = '/faceswap/sessions/' + session['session_id']
        session = api('POST', base + '/source?revision=0', content=(fixture / 'source.jpg').read_bytes())
        session = api('PUT', base, json={'revision': session['revision'],
                      'settings': {**session['settings'], 'preset': 'fast', 'source_position': 0, 'face_position': 1 if args.multi else 0}})
        def no_llm(_):
            raise AssertionError('Face-swap must not initialize LLM providers')
        worker = Worker(repo, None, provider_factory=no_llm)
        ids = {}
        for operation in ('analyze_source', 'analyze_reference', 'preview', 'render'):
            print('RUN', operation, flush=True)
            job = api('POST', base + '/requests', json={'request_id': str(uuid4()),
                'revision': session['revision'], 'operation': operation, 'preview_frame': 8 if args.multi else 4,
                'preview_job_id': ids.get('preview')})
            ids[operation] = job['job_id']
            worker.process(job['job_id'])
            finished = repo.read(job['job_id'])
            print(finished.status, finished.error, flush=True)
            assert finished.status == JobStatus.COMPLETED, (finished.error, str(repo.job_dir(job['job_id'])))
            if args.multi and operation == 'analyze_reference':
                assert len(finished.metadata['faceswap_result']['faces']) == 2
            if args.multi and operation == 'preview':
                from PIL import ImageChops, ImageStat
                folder = repo.job_dir(job['job_id']) / 'output'
                difference = ImageChops.difference(Image.open(folder / 'original.png'), Image.open(folder / 'preview.png'))
                left_change = sum(ImageStat.Stat(difference.crop((0, 0, 320, 240))).mean)
                right_change = sum(ImageStat.Stat(difference.crop((320, 0, 640, 240))).mean)
                print('Multi-person changed halves:', left_change, right_change, flush=True)
                assert left_change > right_change * 3 + .1, 'Reference identity followed array position instead of person'
            if args.multi and operation == 'render':
                from PIL import ImageChops, ImageStat
                final_frame = root / 'render-frame-8.png'
                subprocess.run([executable('ffmpeg'), '-v', 'error', '-i',
                    str(repo.job_dir(job['job_id']) / 'output/final.mp4'),
                    '-vf', 'select=eq(n\\,7)', '-frames:v', '1', str(final_frame)], check=True)
                original = repo.job_dir(ids['preview']) / 'output/original.png'
                difference = ImageChops.difference(Image.open(original).convert('RGB'), Image.open(final_frame).convert('RGB'))
                left_change = sum(ImageStat.Stat(difference.crop((0, 0, 320, 240))).mean)
                right_change = sum(ImageStat.Stat(difference.crop((320, 0, 640, 240))).mean)
                print('Rendered changed halves:', left_change, right_change, flush=True)
                assert left_change > right_change * 1.5 + .1, 'Rendered identity did not match preview'
        promoted = api('POST', f"/jobs/{ids['render']}/promote-video")
        assert promoted['provenance']['parent_asset_id'] == asset['asset_id']
        result = {'root': str(root), 'asset_id': asset['asset_id'], 'session_id': session['session_id'],
                  'jobs': ids, 'promoted_asset_id': promoted['asset_id'], 'multi_person': args.multi, 'status': 'passed'}
        (root / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    os.environ['MIN_FREE_SPACE_BYTES'] = '0'
    os.environ['PAID_LLM_ENABLED'] = 'false'
    main()
