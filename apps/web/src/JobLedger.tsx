import type { Job } from './api';
import { ticketNumber, workflowName } from './job-identity';
import { rowClick, rowKeyDown } from './row-navigation';
import { jobStateLabel } from './job-display';
import { statusLabels } from './video-api';

export const JobLedger = ({ items }: { items: Job[] }) => (
  <div className="job-ledger-scroll" role="region" aria-label="작업 목록" tabIndex={0}>
    <table className="job-ledger">
      <colgroup>
        <col className="job-ticket-column" />
        <col />
        <col />
        <col className="job-state-column" />
        <col className="job-created-column" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col">티켓번호</th>
          <th scope="col">원본</th>
          <th scope="col">워크플로우</th>
          <th scope="col">상태</th>
          <th scope="col">생성일</th>
        </tr>
      </thead>
      <tbody>
        {items.map((job) => (
          <tr
            key={job.job_id}
            className="job-ledger-row"
            tabIndex={0}
            aria-label={`작업 ${ticketNumber(job)} 상세 열기`}
            onClick={(event) => rowClick(event, `#/jobs/${job.job_id}`)}
            onKeyDown={(event) => rowKeyDown(event, `#/jobs/${job.job_id}`)}
          >
            <td className="job-ticket-cell">
              <a
                className="job-ticket-link"
                href={`#/jobs/${job.job_id}`}
                title={ticketNumber(job)}
              >
                {ticketNumber(job)}
              </a>
            </td>
            <td className="job-filename-cell">
              <span title={job.original_filename}>{job.original_filename}</span>
            </td>
            <td className="job-workflow-cell">
              <span className="job-workflow" title={workflowName(job)}>
                {workflowName(job)}
              </span>
            </td>
            <td className="job-status-cell">
              <span className={'status job-state ' + job.status.toLowerCase()}>
                {job.metadata.raw_status
                  ? jobStateLabel({
                      status: job.metadata.raw_status,
                      display_status: job.metadata.display_status,
                      execution_state: job.metadata.execution_state,
                      dispatch_phase: job.metadata.dispatch_phase,
                      processing_review: job.metadata.processing_review,
                    })
                  : job.status === 'AWAITING_REVIEW'
                    ? '검토 대기'
                    : statusLabels[job.status] || job.status}
              </span>
            </td>
            <td className="job-created-cell">
              <time className="job-created" dateTime={job.created_at}>
                {new Date(job.created_at).toLocaleString('ko-KR', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </time>
            </td>
          </tr>
        ))}
        {!items.length && (
          <tr>
            <td colSpan={5}>
              <p className="ui02-empty">작업이 없습니다.</p>
            </td>
          </tr>
        )}
      </tbody>
    </table>
  </div>
);
