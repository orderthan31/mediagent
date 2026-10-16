"""Only interrupted work is eligible; ambiguous paid calls require manual retry."""
import os
from video_service.models import JobStatus, utc_now_iso


def recover_interrupted(repo, record):
    if os.getenv('AUTO_RESUME_INTERRUPTED', 'false').lower() != 'true':
        return False
    if record.metadata.get('execution_authorization'):
        repo.update_status(record.job_id,JobStatus.FAILED,error='서버 승인을 소비한 중단 실행입니다. 자동 재큐잉하지 않으며 결과/위험과 새 남은 계획 확인이 필요합니다.',metadata={'interrupted':True,'recovery_required':True,'wait_reason':None,'stage_progress':None})
        return True
    # Do not unexpectedly rerun historical failures when this feature is deployed.
    if record.metadata.get('recovery_policy_version') != 1:
        return False
    if record.metadata.get('cancel_requested'):
        repo.update_status(record.job_id, JobStatus.CANCELLED, metadata={'wait_reason': None})
        return True
    maximum = int(os.getenv('MAX_AUTO_RECOVERIES', '2'))
    count = record.metadata.get('auto_recovery_count', 0)
    reason = None
    if record.metadata.get('paid_operation_in_flight'):
        reason = '유료 요청의 응답 저장 여부를 확인할 수 없습니다. 저장된 결과를 확인한 뒤 재시도해 주세요.'
    elif count >= maximum:
        reason = '자동 복구 횟수를 초과했습니다. 오류를 확인한 뒤 재시도해 주세요.'
    else:
        try:
            if not repo.source_path(record).is_file():
                reason = '원본 파일이 없어 자동 복구할 수 없습니다.'
        except (OSError, ValueError, KeyError):
            reason = '원본 파일을 확인할 수 없어 자동 복구할 수 없습니다.'
    if reason:
        repo.update_status(record.job_id, JobStatus.FAILED, error=reason, metadata={
            'interrupted': True, 'recovery_required': True, 'recovery_reason': reason,
            'wait_reason': None, 'stage_progress': None})
    else:
        repo.update_status(record.job_id, JobStatus.QUEUED, message='중단된 작업을 저장 지점부터 복구합니다.',
            error=None, metadata={'interrupted': False, 'recovery_required': False,
                'auto_recovery_count': count + 1, 'recovered_at': utc_now_iso(),
                'recovered_stage': record.metadata.get('failed_stage', record.status.value),
                'stage_progress': None, 'wait_reason': None})
    return True
