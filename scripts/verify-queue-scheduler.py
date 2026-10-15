"""Synthetic media proof that encoding/extraction progress while STT is waiting.

Uses a local provider stub, no external requests, and isolated /tmp storage only.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread
import time

os.environ.update(VIDEO_STORAGE_ROOT='/tmp/queue-scheduler-jobs', MIN_FREE_SPACE_BYTES='0',
    VIDEO_SERVICE_QUOTA_BYTES=str(1024**3), VIDEO_ENCODER='libx264', PAID_LLM_ENABLED='false',
    FACEFUSION_ENABLED='false', MAX_CONCURRENT_JOBS='3', MAX_IO_JOBS='2', MAX_LLM_JOBS='1',
    JOB_INDEX_ENABLED='true', AUTO_RESUME_INTERRUPTED='true')
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile
from video_service.workflows import workflow_plan
from video_service.transcript import TranscriptSegment
from media_worker.worker import Worker

root = Path('/tmp/queue-scheduler-jobs')
if root.exists():
    raise RuntimeError('Requires a fresh isolated container')
repo = FilesystemJobRepository(root)
fixture = root / 'fixture.mp4'
subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
    'testsrc2=size=320x180:rate=15', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '2',
    '-c:v', 'libx264', '-c:a', 'aac', str(fixture)], check=True)
identities = []
for template in ('transcribe', 'encode', 'extract_audio'):
    record = repo.create_job(original_filename='synthetic.mp4', expected_size=fixture.stat().st_size,
        source_language='en', target_language='ko', quality_profile=QualityProfile.COMPACT,
        video_codec='h264', subtitle_mode='none', audio_filter='off',
        metadata={'workflow': workflow_plan(template, subtitle_mode='none')})
    shutil.copyfile(fixture, repo.source_path(record))
    repo.update_status(record.job_id, JobStatus.QUEUED)
    identities.append(record.job_id)

overlap_verified = False
class LocalProvider:
    transcription_model = translation_model = audio_filter_model = 'local-stub'
    def transcribe(self, audio, language, check, **kwargs):
        global overlap_verified
        kwargs['progress']({'total': 1, 'completed': 0, 'in_flight': 1, 'retrying': 0,
                            'failed': 0, 'draining': False})
        deadline = time.monotonic() + 20
        while any(repo.read(identity).status != JobStatus.COMPLETED for identity in identities[1:]):
            check()
            if time.monotonic() > deadline:
                raise RuntimeError('Independent jobs did not progress while STT was waiting')
            time.sleep(.05)
        overlap_verified = True
        kwargs['progress']({'total': 1, 'completed': 1, 'in_flight': 0, 'retrying': 0,
                            'failed': 0, 'draining': False})
        return [TranscriptSegment(.1, 1.0, 'Synthetic speech.')]

worker = Worker(repo, None, provider_factory=lambda owner: LocalProvider())
thread = Thread(target=worker.run, args=(.1,))
start = time.monotonic()
thread.start()
try:
    deadline = start + 30
    while time.monotonic() < deadline:
        records = [repo.read(identity) for identity in identities]
        if all(record.status in {JobStatus.COMPLETED, JobStatus.FAILED} for record in records):
            break
        time.sleep(.05)
    assert all(record.status == JobStatus.COMPLETED for record in records), [(r.status, r.error) for r in records]
    assert overlap_verified
    print(json.dumps({'status': 'passed', 'completed': len(records), 'overlap_verified': True,
        'external_model_calls': 0, 'seconds': round(time.monotonic() - start, 2)}), flush=True)
finally:
    worker.stop.set()
    thread.join(15)
    if thread.is_alive():
        raise RuntimeError('Worker did not stop promptly')
