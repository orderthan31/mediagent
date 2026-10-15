import shutil
import math
import time
import os
from datetime import datetime
from pathlib import Path


class StorageLimitError(ValueError):
    pass


def used_bytes(root: Path) -> int:
    total = 0
    pending = [root]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            continue
    return total


def audited_usage(root, max_age=600):
    """Conservative worker estimate; only enumerate manifests, never media trees.

    Include full reservations for live jobs and jobs changed since the scan began,
    plus admission charges. Missing/stale audits require an authoritative scan.
    """
    from .storage import read_json
    from .repository import FilesystemJobRepository
    from .models import TERMINAL_STATUSES
    path = root / '.storage-audit.json'
    if not path.exists():
        return None
    audit = read_json(path)
    age = time.time() - audit['started_at']
    if age < 0 or age > max_age:
        return None
    total = audit['used_bytes']
    repositories = [FilesystemJobRepository(root)]
    if (root / '.uploads').exists():
        repositories.append(FilesystemJobRepository(root / '.uploads'))
    for repository in repositories:
        for job in repository.list():
            if (job.status not in TERMINAL_STATUSES or
                    datetime.fromisoformat(job.updated_at).timestamp() >= audit['started_at']):
                reserved = job.metadata.get('reserved_bytes', job.expected_size * 4)
                if not isinstance(reserved, int) or reserved < 0:
                    raise StorageLimitError('Invalid workspace reservation')
                total += reserved
    budget_path = root / '.faceswap-budget.json'
    if budget_path.exists():
        budget = read_json(budget_path)
        total += budget.get('previous', 0) + budget.get('charged', 0)
    return total


def assert_capacity(root: Path, quota: int, minimum_free: int, additional=0):
    if used_bytes(root) + additional > quota:
        raise StorageLimitError("Service storage quota exceeded")
    assert_free_space(root, minimum_free, additional)


def assert_free_space(root: Path, minimum_free: int, additional=0):
    """Check physical headroom without enumerating files on the upload path."""
    if shutil.disk_usage(root).free - additional < minimum_free:
        raise StorageLimitError("Insufficient free disk space")


def reserve_preview_capacity(repository, quota, minimum_free, additional, max_age=600):
    """Bounded interactive writes use an audit and conservative charges, under admission lock.

    Keep a previous audit window's charges too, covering writes concurrent with the
    scan. Heavy workflows retain their authoritative admission checks.
    """
    from .storage import read_json, write_json_atomic
    from .models import TERMINAL_STATUSES
    root = repository.storage_root
    audit_path = root / '.storage-audit.json'
    audit = read_json(audit_path) if audit_path.exists() else None
    if not audit or time.time() - audit['started_at'] > max_age:
        return assert_capacity(root, quota, minimum_free, remaining_reservations(repository) + additional)
    budget_path = root / '.faceswap-budget.json'
    budget = read_json(budget_path) if budget_path.exists() else {}
    if budget.get('audit') != audit['started_at']:
        budget = {'audit': audit['started_at'], 'previous': budget.get('charged', 0), 'charged': 0}
    pending = 0
    growth = 0
    jobs = repository.list()
    if (root / '.uploads').exists():
        from .repository import FilesystemJobRepository
        jobs += FilesystemJobRepository(root / '.uploads').list()
    for job in jobs:
        reserved = job.metadata.get('reserved_bytes', job.expected_size * 4)
        if not isinstance(reserved, int) or reserved < 0:
            raise StorageLimitError('Invalid workspace reservation')
        if job.status not in TERMINAL_STATUSES:
            pending += reserved
        if (not job.metadata.get('faceswap_operation') and
                datetime.fromisoformat(job.updated_at).timestamp() >= audit['started_at']):
            growth += reserved
    estimated = audit['used_bytes'] + growth + pending + budget['previous'] + budget['charged'] + additional
    if estimated > quota:
        raise StorageLimitError('Service storage quota exceeded')
    assert_free_space(root, minimum_free, pending + additional)
    budget['charged'] += additional
    write_json_atomic(budget_path, budget)


def workspace_reservation(expected_size: int, duration: float) -> int:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duration must be positive and finite")
    # Source/output allowance plus extracted and processed mono 16-bit 16kHz PCM.
    pcm_bytes = math.ceil(duration * 16000) * 2
    return expected_size * 4 + pcm_bytes * 2 + 1024**2


def remaining_reservations(repository, overrides=None):
    from .models import TERMINAL_STATUSES

    overrides = overrides or {}
    remaining = 0
    for record in repository.list():
        if record.status in TERMINAL_STATUSES:
            continue
        reserved = overrides.get(record.job_id, record.metadata.get("reserved_bytes", record.expected_size * 4))
        if not isinstance(reserved, int) or reserved < 0:
            raise StorageLimitError("Invalid workspace reservation")
        remaining += max(0, reserved - used_bytes(repository.job_dir(record.job_id)))
    upload_root = repository.storage_root / '.uploads'
    if upload_root.exists():
        from .repository import FilesystemJobRepository
        remaining += remaining_reservations(FilesystemJobRepository(upload_root), overrides)
    return remaining


def reserve_workspace(repository, job_id, duration, quota, minimum_free, check=lambda: None):
    from .locking import wait_for_job_lock

    # Share the API admission lock so simultaneous analyses cannot oversubscribe.
    with wait_for_job_lock(repository, "0" * 32, check=check), wait_for_job_lock(repository, job_id, check=check):
        record = repository.read(job_id)
        reserved = max(record.metadata.get("reserved_bytes", 0), workspace_reservation(record.expected_size, duration))
        estimate = audited_usage(repository.storage_root)
        if estimate is None:
            additional = remaining_reservations(repository, {job_id: reserved})
            assert_capacity(repository.storage_root, quota, minimum_free, additional)
        else:
            previous = record.metadata.get('reserved_bytes', record.expected_size * 4)
            growth = max(0, reserved - previous)
            if estimate + growth > quota:
                raise StorageLimitError('Service storage quota exceeded')
            # Admission still serializes reservation growth and live disk checks.
            reserve_preview_capacity(repository, quota, minimum_free, growth)
        record.metadata.update(reserved_bytes=reserved, source_duration=duration)
        repository.save(record)
        return reserved
