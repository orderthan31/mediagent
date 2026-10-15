"""Owner-scoped storage inventory and lock-protected, explicit job cleanup."""
import os
from pathlib import Path
import shutil
import stat
import time

from video_service.locking import job_lock, JobBusyError
from video_service.models import JobStatus, TERMINAL_STATUSES
from video_service.repository import FilesystemJobRepository, JobNotFoundError
from video_service.storage import remove_path_inside

EDITABLE_SUFFIXES = {'.json', '.srt', '.smi', '.ass', '.vtt'}


def linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def files(root):
    """Never follow symlinks or Windows reparse points, including nested junctions."""
    try:
        info = root.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        return
    if stat.S_ISREG(info.st_mode):
        yield root, info.st_size
        return
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        # A Windows bind mount makes each stat a host round-trip.
                        # Reuse a single no-follow stat for type, safety and size.
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        continue
                    path = Path(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        yield path, info.st_size
        except FileNotFoundError:
            continue


def size(root):
    return sum(amount for _, amount in files(root))


def temporary_targets(directory):
    work = directory / 'work'
    if not work.exists() or linked(work):
        return []
    # Final subtitle editing and previews still read these published text files.
    return [p for p in work.iterdir()
            if p.is_dir() or p.suffix.lower() not in EDITABLE_SUFFIXES]


def assert_safe_tree(root, target):
    target.resolve().relative_to(root.resolve())
    if linked(target):
        raise ValueError('Linked storage cannot be cleaned')
    if target.is_dir():
        for child in target.iterdir():
            assert_safe_tree(root, child)


def inventory(settings, owner):
    repo = FilesystemJobRepository(settings.storage_root)
    categories = dict(input=0, work=0, output=0, library=0, uploads=0, faceswap=0, other=0)
    sizes = {}
    for path, amount in files(repo.storage_root):
        relative = path.relative_to(repo.storage_root)
        parts = relative.parts
        category = {'.assets': 'library', '.uploads': 'uploads', '.faceswap': 'faceswap'}.get(parts[0])
        if category is None:
            category = parts[1] if len(parts) > 2 and len(parts[0]) == 32 and parts[1] in ('input', 'work', 'output') else 'other'
        categories[category] += amount
        if len(parts[0]) == 32:
            values = sizes.setdefault(parts[0], dict(input=0, work=0, output=0, total_bytes=0, temporary_bytes=0))
            values['total_bytes'] += amount
            if category in ('input', 'work', 'output'):
                values[category] += amount
            if category == 'work' and (len(parts) > 3 or path.suffix.lower() not in EDITABLE_SUFFIXES):
                values['temporary_bytes'] += amount
    jobs = []
    for record in repo.list():
        if record.metadata.get('owner_id') != owner:
            continue
        directory = repo.job_dir(record.job_id)
        if not directory.exists() or linked(repo.storage_root / record.job_id):
            continue
        values = sizes.get(record.job_id, dict(input=0, work=0, output=0, total_bytes=0, temporary_bytes=0))
        if record.status != JobStatus.COMPLETED:
            values['temporary_bytes'] = 0
        jobs.append(dict(job_id=record.job_id, filename=record.original_filename, status=record.status.value,
            **values, deletable=record.status in TERMINAL_STATUSES))
    disk = shutil.disk_usage(repo.storage_root)
    host_path = os.getenv('HOST_DISK_PROBE_PATH')
    host_disk = None
    if host_path:
        try:
            host = shutil.disk_usage(host_path)
            host_disk = dict(total_bytes=host.total, used_bytes=host.used, free_bytes=host.free)
        except OSError:
            pass
    return dict(checked_at=time.time(), disk=dict(total_bytes=disk.total, used_bytes=disk.used, free_bytes=disk.free),
        host_disk=host_disk, container=Path('/.dockerenv').exists(), categories=categories,
        total_bytes=sum(categories.values()), quota_bytes=settings.service_quota_bytes, jobs=jobs)


def cleanup(settings, owner, job_ids, mode):
    repo = FilesystemJobRepository(settings.storage_root)
    results = []
    for job_id in job_ids:
        removed = 0
        try:
            with job_lock(repo, job_id, 'execution'), job_lock(repo, job_id):
                record = repo.read(job_id)
                if record.metadata.get('owner_id') != owner:
                    raise JobNotFoundError(job_id)
                if record.status not in TERMINAL_STATUSES or (mode == 'temporary' and record.status != JobStatus.COMPLETED):
                    results.append(dict(job_id=job_id, status='active', removed_bytes=0))
                    continue
                directory = repo.job_dir(job_id)
                # Check the unresolved job path too: job_dir resolves junctions.
                assert_safe_tree(repo.storage_root, repo.storage_root / job_id)
                targets = temporary_targets(directory) if mode == 'temporary' else [directory]
                for target in targets:
                    amount = size(target)
                    remove_path_inside(repo.storage_root, target)
                    removed += amount
                results.append(dict(job_id=job_id, status='cleaned', removed_bytes=removed))
        except JobBusyError:
            results.append(dict(job_id=job_id, status='busy', removed_bytes=0))
        except JobNotFoundError:
            results.append(dict(job_id=job_id, status='missing', removed_bytes=0))
        except (OSError, ValueError):
            results.append(dict(job_id=job_id, status='error', removed_bytes=removed))
    return dict(results=results, removed_bytes=sum(r['removed_bytes'] for r in results))
