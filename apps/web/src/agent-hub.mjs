export const canonicalAgentIdentity = (identity) =>
  ({ transcription: 'transcribe', translation: 'translate' })[identity] || identity;

export const agentStateLabel = (state) =>
  ({
    idle: '대기 중',
    ready: '준비됨',
    preparing: '준비 중',
    processing: '처리 중',
    completed: '완료',
    failed: '오류',
    cancelled: '취소됨',
    held: '확인 필요',
    unknown: '확인 필요',
  })[state] || '확인 필요';
