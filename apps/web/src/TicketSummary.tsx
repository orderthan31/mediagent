import type { Job } from './api';
import { stageLabels, templates } from './video-api';
import { failureMessage, isContentBlocked } from './job-failure';
import { Badge } from './hangyeol/primitives/badge';
import { StageProgress } from './StageProgress';

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
const explanations: Record<string, string> = {
  UPLOADING: '입력 영상을 전송하고 있어요. 전송 완료와 처리 완료는 다릅니다.',
  READY: '실행 대기 중입니다. 작업 목록에서 가능한 행동을 확인하세요.',
  QUEUED: '처리 시작을 기다리고 있어요.',
  AWAITING_REVIEW: '자막 검수를 기다리고 있어요. 초안 저장과 최종 출력을 구분해 진행하세요.',
  COMPLETED: '티켓 처리가 완료됐어요. 보관 중인 결과를 확인할 수 있어요.',
  FAILED: '처리에 실패했어요. 오류와 남아 있는 결과를 확인하세요.',
  CANCELLED: '처리가 중단됐어요. 이미 생성된 결과와 현재 상태를 구분해 확인하세요.',
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
      <span>
        {job.metadata.workflow
          ? templates[job.metadata.workflow.template] || job.metadata.workflow.template
          : job.metadata.faceswap_chunks
            ? '얼굴 합성 티켓'
            : '처리 티켓'}
      </span>
    </div>
    <p>
      {explanations[job.status] ||
        job.status_message ||
        '표시된 티켓 상태와 현재 단계, 확인 가능한 결과를 함께 확인하세요.'}
    </p>
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
