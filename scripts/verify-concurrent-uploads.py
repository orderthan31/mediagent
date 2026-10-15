"""Run inside an isolated API container (no production data mounted).

Creates synthetic videos, performs real concurrent HTTP uploads and queues jobs.
Never runs a worker or calls a transcription provider.
"""
import concurrent.futures
import json
import subprocess
import time
import urllib.request
import urllib.error
import threading
from uuid import uuid4
from pathlib import Path
import os


def main():
    if os.getenv('VIDEO_STORAGE_ROOT') != '/tmp/stability-jobs':
        raise RuntimeError('Requires isolated /tmp/stability-jobs API storage')
    root = Path('/tmp/stability-check')
    root.mkdir(exist_ok=True)
    source = root / 'fixture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'color=c=blue:s=160x90:r=5:d=1', '-c:v', 'libx264', str(source)], check=True)
    data = source.read_bytes()
    transient_busy = 0
    counters = threading.Lock()
    def api(path, payload=None, method='POST', raw=False):
        nonlocal transient_busy
        body = payload if raw else json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request('http://127.0.0.1:8000/api' + path, data=body, method=method,
              headers={'Content-Type': 'application/octet-stream' if raw else 'application/json'})
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                body = json.loads(exc.read())
                if exc.code != 409 or body.get('code') != 'job_busy' or time.monotonic() >= deadline:
                    raise
                # Preserve the payload/request ID, as the web client does.
                with counters:
                    transient_busy += 1
                time.sleep(.25)
    def upload(index):
        payload = {'filename': f'concurrent-fixture-{index}.mp4', 'size': len(data), 'request_id': str(uuid4())}
        result = api('/video-uploads', payload)
        assert api('/video-uploads', payload)['upload_id'] == result['upload_id']
        base = '/video-uploads/' + result['upload_id']
        api(base + '/chunks?offset=0', data, 'PUT', True)
        video = api(base + '/complete')['video']
        assert api(base + '/complete')['video']['asset_id'] == video['asset_id']
        workflow = {'request_id': str(uuid4()), 'template': 'extract_audio', 'options': {'audio_filter': 'off'}}
        job = api('/videos/' + video['asset_id'] + '/jobs', workflow)
        assert api('/videos/' + video['asset_id'] + '/jobs', workflow)['job_id'] == job['job_id']
        assert job['status'] == 'QUEUED', job
        return result['upload_id'], video['asset_id'], job['job_id']
    start = time.monotonic()
    hold_seconds = float(os.getenv('VERIFY_BUSY_SECONDS', '0'))
    if hold_seconds:
        from video_service.locking import job_lock
        from video_service.repository import FilesystemJobRepository
        held = threading.Event()
        def hold_admission():
            with job_lock(FilesystemJobRepository(Path('/tmp/stability-jobs')), '0' * 32):
                held.set()
                time.sleep(hold_seconds)
        holder = threading.Thread(target=hold_admission, daemon=True)
        holder.start()
        if not held.wait(5):
            raise RuntimeError('Could not acquire test contention lock')
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(upload, range(12)))
    assert all(len({r[i] for r in results}) == 12 for i in range(3))
    jobs = api('/jobs', method='GET')['jobs']
    assert len(jobs) == 12 and all(j['status'] == 'QUEUED' for j in jobs)
    if hold_seconds > 5:
        assert transient_busy > 0, 'Contention scenario must exercise retries'
    print(json.dumps({'simultaneous_uploads': 12, 'queued_jobs': len(jobs),
                      'duplicate_jobs': 0, 'http_busy_errors': 0,
                      'transient_busy_retries': transient_busy,
                      'seconds': round(time.monotonic() - start, 2), 'status': 'passed'}), flush=True)


if __name__ == '__main__':
    main()
