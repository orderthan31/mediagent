from __future__ import annotations

import shutil
import re
import os
import sqlite3
import logging
from pathlib import Path
from typing import Iterable
from uuid import uuid4
from datetime import datetime

from .models import JobOptions, JobRecord, JobStatus, QualityProfile, TERMINAL_STATUSES, utc_now_iso
from .storage import ensure_dir, read_json, resolve_under, safe_suffix, write_json_atomic


class JobNotFoundError(KeyError):
    pass


class FilesystemJobRepository:
    def __init__(self, storage_root: str | Path) -> None:
        self.storage_root = ensure_dir(Path(storage_root))

    @property
    def preserve_artifacts(self) -> bool:
        return (self.storage_root / ".preserve-artifacts").exists()

    def create_job(
        self,
        *,
        original_filename: str,
        expected_size: int,
        source_language: str,
        target_language: str,
        quality_profile: QualityProfile,
        metadata: dict | None = None,
        video_codec: str = "hevc",
        subtitle_mode: str = "burn",
        resolution: str = "original",
        additional_languages: list[str] | None = None,
        audio_filter: str = "silence3",
        review_subtitles: bool = False,
        video_description: str = "",
        vad_mode: str = "off",
    ) -> JobRecord:
        job_id = uuid4().hex
        source_filename = f"source{safe_suffix(original_filename)}"
        job_dir = self.job_dir(job_id)
        ensure_dir(job_dir / "input")
        ensure_dir(job_dir / "work")
        ensure_dir(job_dir / "output")
        record = JobRecord(
            job_id=job_id,
            status=JobStatus.UPLOADING,
            original_filename=original_filename,
            source_filename=source_filename,
            expected_size=expected_size,
            options=JobOptions(source_language, target_language, quality_profile, video_codec, subtitle_mode, resolution,
                list(additional_languages or []), audio_filter, review_subtitles, video_description, vad_mode),
            metadata=dict(metadata or {}),
        )
        self.save(record)
        return record

    def job_dir(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise JobNotFoundError(job_id)
        return resolve_under(self.storage_root, job_id)

    def source_path(self, record: JobRecord) -> Path:
        if record.metadata.get('source_asset_id'):
            from .assets import VideoAssetRepository
            assets = VideoAssetRepository(self)
            return assets.source_path(assets.read(record.metadata['source_asset_id'],
                                                  owner_id=record.metadata.get('owner_id')))
        return resolve_under(self.storage_root, record.job_id, "input", record.source_filename)

    def job_file(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def read(self, job_id: str) -> JobRecord:
        path = self.job_file(job_id)
        if not path.exists():
            raise JobNotFoundError(job_id)
        return JobRecord.from_dict(read_json(path))

    def save(self, record: JobRecord) -> JobRecord:
        if record.status == JobStatus.QUEUED:
            record.metadata.setdefault('stage_started_at', record.metadata.get('queued_at', record.created_at))
        record.touch()
        write_json_atomic(self.job_file(record.job_id), record.to_dict())
        if record.status == JobStatus.QUEUED:
            try:
                # Shared wake signal; ordinary workflows should wake the worker too.
                (self.storage_root / '.faceswap-wakeup').touch()
            except OSError:
                # The durable queue is authoritative; polling is the fallback.
                pass
        return record

    def list(self) -> list[JobRecord]:
        if os.getenv('JOB_INDEX_ENABLED', 'false').lower() == 'true':
            from .job_index import indexed_jobs
            try:
                return indexed_jobs(self.storage_root)
            except (OSError, sqlite3.Error):
                logging.getLogger(__name__).warning('Job index unavailable; reading durable manifests')
        records: list[JobRecord] = []
        if not self.storage_root.exists():
            return records
        for path in sorted(self.storage_root.glob("*/job.json"), reverse=True):
            try:
                records.append(JobRecord.from_dict(read_json(path)))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records

    def find_by_statuses(self, statuses: Iterable[JobStatus]) -> list[JobRecord]:
        status_set = set(statuses)
        return [record for record in self.list() if record.status in status_set]

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        message: str | None = None,
        error: str | None = None,
        metadata: dict | None = None,
    ) -> JobRecord:
        record = self.read(job_id)
        now = utc_now_iso()
        if status != record.status:
            started = record.metadata.get('stage_started_at')
            timings = dict(record.metadata.get('stage_durations_seconds', {}))
            if started and record.status not in TERMINAL_STATUSES:
                elapsed = max(0, (datetime.fromisoformat(now) - datetime.fromisoformat(started)).total_seconds())
                timings[record.status.value] = round(timings.get(record.status.value, 0) + elapsed, 3)
            record.metadata.update(stage_started_at=now, stage_durations_seconds=timings)
            record.metadata['stage_wait_baseline_seconds'] = record.metadata.get('resource_wait_seconds', 0)
        record.status = status
        if status == JobStatus.QUEUED:
            record.metadata["queued_at"] = utc_now_iso()
            record.completed_at = None
        record.status_message = message
        record.error = error
        if metadata:
            record.metadata.update(metadata)
        if status in TERMINAL_STATUSES:
            record.completed_at = utc_now_iso()
        return self.save(record)

    def update_upload_progress(self, job_id: str, uploaded_bytes: int) -> JobRecord:
        record = self.read(job_id)
        record.uploaded_bytes = uploaded_bytes
        return self.save(record)

    def heartbeat(self, job_id: str) -> JobRecord:
        record = self.read(job_id)
        record.heartbeat()
        return self.save(record)

    def delete_job_dir(self, job_id: str) -> None:
        target = self.job_dir(job_id)
        if target.exists():
            shutil.rmtree(target)
