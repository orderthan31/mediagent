import type { Job } from './api';
import { failureMessage, isContentBlocked } from './job-failure';
import { Badge } from './hangyeol/primitives/badge';
import { StageProgress } from './StageProgress';
import { workflowName } from './job-identity';

export const TicketSummary = ({ job, labels }: { job: Job; labels: Record<string, string> }) => (
  <section className="ticket-summary ticket-summary-compact" aria-label="작업 상태">
    <div className="ticket-status-heading">
      <Badge tone={job.status === 'FAILED' ? 'danger' : 'info'}>
        {job.status === 'AWAITING_REVIEW' && job.metadata.content_block_review
          ? '차단 구간 검토'
          : isContentBlocked(job)
            ? '콘텐츠 차단'
            : labels[job.status] || job.status}
      </Badge>
      <span>{workflowName(job)}</span>
      <time dateTime={job.created_at}>{new Date(job.created_at).toLocaleString('ko-KR')}</time>
    </div>
    {job.error && <p role="alert">{failureMessage(job) || job.error}</p>}
    {job.metadata.cancel_requested &&
      !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) && (
        <p>중단 요청됨 · 실행 중인 요청의 정리를 기다리고 있어요.</p>
      )}
    <StageProgress job={job} />
  </section>
);
