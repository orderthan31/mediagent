export type ProcessingProjection = {
  case_id: string;
  state: string;
  source_attempt_id?: string;
  child_id?: string | null;
};
export const processingLabel = (value?: ProcessingProjection | null): string | null => {
  if (!value?.case_id) {
    return null;
  }
  return (
    (
      {
        needs_review: '처리 여부 확인 필요',
        held: '관리자 확인 보류',
        child_created: '새 복구 작업 연결됨',
      } as Record<string, string>
    )[value.state] || '처리 여부 확인 필요'
  );
};
export const processingReasons: Record<string, string> = {
  verified_terminal_receipt_required:
    '원 실행의 검증된 종료 결과가 없어 보류합니다. 수신 기록이 없다는 것만으로 재처리하지 않습니다.',
  single_encode_scope_required:
    '이번 복구는 모델 호출이 없고 인코딩 노드가 정확히 1개인 작업만 지원합니다.',
  other_attempt_outcome_unconfirmed:
    '같은 작업의 다른 실행 회차가 처리 중이거나 종료 근거가 불명확해 보류합니다.',
  quarantine_object_unavailable: '격리 결과의 실제 파일과 해시를 확인할 수 없습니다.',
  fresh_bound_worker_required: '원 실행과 연결된 최신 실행기 근거가 필요합니다.',
  bound_worker_not_quiescent: '같은 실행 회차의 실행기가 정상 대기 중인지 확인해야 합니다.',
  bound_remote_receive_evidence_required: '원 요청과 일치하는 실행기 수신·종료 근거가 필요합니다.',
  registered_execution_target_required: '등록된 실행 대상 근거가 필요합니다.',
  sender_still_active: '전송 프로그램이 아직 시도를 소유하고 있습니다.',
  child_already_created: '이미 새 복구 작업이 연결되어 있습니다. 원 작업을 다시 실행하지 않습니다.',
};
