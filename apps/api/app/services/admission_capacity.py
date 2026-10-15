"""Short quota admission checks under the shared admission lock."""
import time

from video_service.capacity import remaining_reservations, reserve_preview_capacity
from video_service.storage import read_json


def check_admission_capacity(repo, settings, additional, *, strict, overrides=None):
    audit_path = repo.storage_root / '.storage-audit.json'
    audit = read_json(audit_path) if audit_path.exists() else None
    max_age = settings.storage_audit_interval_seconds * 2
    if audit and time.time() - audit.get('started_at', 0) <= max_age:
        reserve_preview_capacity(repo, settings.service_quota_bytes,
                                 settings.min_free_space_bytes, additional, max_age=max_age)
    else:
        strict(repo.storage_root, settings.service_quota_bytes, settings.min_free_space_bytes,
               remaining_reservations(repo, overrides) + additional)
