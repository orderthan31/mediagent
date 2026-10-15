"""Preview artifacts are a bounded working set, not permanent job history."""
from video_service.locking import job_lock, JobBusyError
from video_service.models import TERMINAL_STATUSES, JobStatus
from video_service.repository import JobNotFoundError


def prune_previews(repo, session_id, owner_id, keep=2):
    try:
        with job_lock(repo, '0' * 32):
            jobs = [j for j in repo.list() if j.metadata.get('owner_id') == owner_id
                    and j.metadata.get('faceswap', {}).get('session_id') == session_id]
            protected = {j.metadata.get('faceswap_request', {}).get('preview_job_id')
                         for j in jobs if j.status not in TERMINAL_STATUSES}
            for operation in ('analyze_source', 'analyze_reference', 'preview'):
                candidates = sorted([j for j in jobs if j.metadata.get('faceswap_operation') == operation
                                     and j.status in TERMINAL_STATUSES],
                                    key=lambda j: (j.created_at, j.job_id), reverse=True)
                protected.update(j.job_id for j in candidates[:keep])
                latest_success = next((j for j in candidates if j.status == JobStatus.COMPLETED), None)
                if latest_success:
                    protected.add(latest_success.job_id)
                for candidate in candidates:
                    if candidate.job_id in protected:
                        continue
                    try:
                        with job_lock(repo, candidate.job_id, 'execution'), job_lock(repo, candidate.job_id):
                            if repo.read(candidate.job_id).status in TERMINAL_STATUSES:
                                repo.delete_job_dir(candidate.job_id)
                    except (JobBusyError, JobNotFoundError, OSError):
                        pass
    except JobBusyError:
        pass
