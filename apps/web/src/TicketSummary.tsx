import type { Job } from './api';
import { stageLabels } from './video-api';
import { failureMessage, isContentBlocked } from './job-failure';
import { Badge } from './hangyeol/primitives/badge';
import { StageProgress } from './StageProgress';
import { workflowName } from './job-identity';

const currentStages: Record<string, string> = {
  ANALYZING: 'analyze',
  EXTRACTING_AUDIO: 'extract_audio',
  PREPROCESSING_AUDIO: 'preprocess_audio',
  TRANSCRIBING: 'transcribe',
  TRANSLATING: 'translate',
  GENERATING_SUBTITLE: 'generate_subtitle',
  ENCODING: 'encode',
  FACE_SWAPPING: 'faceswap',
  VALIDATING: 'validate_video',
};

export const TicketSummary = ({ job, labels }: { job: Job; labels: Record<string, string> }) => (
  <section className="ticket-summary" aria-label="티켓 상태와 처리 흐름">
    <div className="ticket-status-heading">
      <Badge tone={job.status === 'FAILED' ? 'danger' : 'info'}>
        {job.status === 'AWAITING_REVIEW' && job.metadata.content_block_review
          ? '차단 구간 검토'
          : isContentBlocked(job)
            ? '콘텐츠 차단'
            : labels[job.status] || job.status}
      </Badge>
      <span>{workflowName(job)}</span>
    </div>
    {job.error && <p role="alert">{failureMessage(job) || job.error}</p>}
    {job.metadata.cancel_requested &&
      !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) && (
        <p>중단 요청됨 · 실행 중인 요청의 정리를 기다리고 있어요.</p>
      )}
    {job.metadata.asset_id && (
      <a className="ticket-input-link" href={`#/videos/${job.metadata.asset_id}`}>
        입력 영상 정보 열기
      </a>
    )}
    <div className="ticket-plan">
      <h2>요청된 처리 흐름</h2>
      {job.metadata.workflow?.stages.length ? (
        <ol>
          {job.metadata.workflow.stages.map((stage, index) => (
            <li
              key={`${stage}-${index}`}
              aria-current={currentStages[job.status] === stage ? 'step' : undefined}
            >
              {stageLabels[stage] || stage}
              {currentStages[job.status] === stage && <span>현재 단계</span>}
            </li>
          ))}
        </ol>
      ) : (
        <p>단계 목록이 제공되지 않았어요. 현재 티켓 상태를 기준으로 확인하세요.</p>
      )}
    </div>
    <StageProgress job={job} />
  </section>
);
