import { processingLabel, type ProcessingProjection } from './processing-review-state';

type RunProgress = { status: string; dispatch?: { phase: string } | null };
export type JobProgress = {
  status: string;
  display_status?: string | null;
  execution_state?: string | null;
  dispatch_phase?: string | null;
  processing_review?: ProcessingProjection | null;
  runs?: RunProgress[];
};
const phases = ['unknown', 'sending', 'sent', 'received', 'pending'];
export const currentDispatchPhase = (runs: RunProgress[] = []) =>
  phases.find((phase) =>
    runs.some(
      (run) => ['running', 'waiting'].includes(run.status) && run.dispatch?.phase === phase,
    ),
  );

export const jobStateLabel = (job: JobProgress) => {
  const state = job.display_status || job.status;
  const terminal: Record<string, string> = {
    held: '보류 · 응답 확인 필요',
    unknown: '응답 확인 필요',
    failed: '실패',
    completed: '완료',
    cancelled: '취소',
    cancelling: '취소 처리 중',
    blocked: '선행 실패로 차단',
    quarantined: '결과 확인 필요',
    review_required: '검수 대기',
  };
  if (terminal[state]) {
    return terminal[state];
  }
  const review = processingLabel(job.processing_review);
  if (review) {
    return review;
  }
  if (job.status === 'draft') {
    return '시작 전';
  }
  if (['waiting', 'running'].includes(job.status)) {
    const phase = job.dispatch_phase || currentDispatchPhase(job.runs);
    const labels: Record<string, string> = {
      pending: '전송 대기',
      sending: '전송 중',
      sent: '수신 확인 대기',
      received: '처리 중',
      unknown: '전송 결과 확인 필요',
    };
    if (phase && labels[phase]) {
      return labels[phase];
    }
    if (job.execution_state === 'preparing') {
      return '준비 중';
    }
    return job.status === 'waiting' ? '준비 대기' : '처리 중';
  }
  return '상태 확인 필요';
};
