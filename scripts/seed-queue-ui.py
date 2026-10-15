"""Disposable UI fixtures; refuses to touch production storage."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from video_service.repository import FilesystemJobRepository
from video_service.models import JobStatus, QualityProfile

root = Path(os.environ['VIDEO_STORAGE_ROOT'])
if root != Path('/tmp/queue-ui-jobs'):
    raise RuntimeError('UI fixtures require /tmp/queue-ui-jobs')
repo = FilesystemJobRepository(root)
for index, status in enumerate([JobStatus.QUEUED] * 3 + [JobStatus.ENCODING]):
    record = repo.create_job(original_filename=f'Synthetic-{index + 1}.mp4', expected_size=3,
        source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED,
        metadata={'workflow': {'template': 'encode'}, 'owner_id': None})
    repo.source_path(record).write_bytes(b'abc')
    repo.update_status(record.job_id, status)
    if status == JobStatus.ENCODING:
        record = repo.read(record.job_id)
        record.metadata.update(stage_started_at=(datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(),
                               stage_progress=.4, stage_durations_seconds={'ANALYZING': .4, 'EXTRACTING_AUDIO': 2.1})
        repo.save(record)
print('Created 4 synthetic UI fixtures; no worker is running.')
