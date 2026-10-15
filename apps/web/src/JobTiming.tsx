import { useEffect, useState } from 'react';
import type { Job } from './api';
import { statusLabels } from './video-api';
import { elapsedSeconds, timeLabel } from './queue-state';
import './queue-controls.css';

export const JobTiming = ({ job }: { job: Job }) => {
  const [now, setNow] = useState(Date.now);
  const running = ![
    'COMPLETED',
    'FAILED',
    'CANCELLED',
    'READY',
    'UPLOADING',
    'AWAITING_REVIEW',
  ].includes(job.status);
  const elapsed = elapsedSeconds(job.metadata.stage_started_at, now);
  const stageWait = Math.max(
    0,
    (job.metadata.resource_wait_seconds || 0) - (job.metadata.stage_wait_baseline_seconds || 0),
  );
  const processingElapsed = elapsed === null ? null : Math.max(0, elapsed - stageWait);
  const fraction = job.metadata.stage_progress;
  const durations = Object.entries(job.metadata.stage_durations_seconds || {});
  const estimate =
    running &&
    !job.metadata.wait_reason &&
    processingElapsed !== null &&
    processingElapsed >= 5 &&
    typeof fraction === 'number' &&
    fraction > 0.05 &&
    fraction < 0.98 &&
    ['ENCODING', 'VALIDATING', 'FACE_SWAPPING'].includes(job.status)
      ? (processingElapsed * (1 - fraction)) / fraction
      : null;
  useEffect(() => {
    if (!running) {
      return;
    }
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return (
    <div className="job-timing">
      {running && elapsed !== null && <span>현재 단계 {timeLabel(elapsed)}</span>}
      {job.metadata.wait_reason && <strong role="status">{job.metadata.wait_reason}</strong>}
      {estimate !== null && <span>현재 속도 기준 약 {timeLabel(estimate)} 남음</span>}
      {!!job.metadata.auto_recovery_count && (
        <span>저장 지점에서 복구 {job.metadata.auto_recovery_count}회</span>
      )}
      {job.metadata.recovery_required && <p role="status">{job.metadata.recovery_reason}</p>}
      {durations.length > 0 && (
        <details>
          <summary>단계별 소요 시간</summary>
          <dl>
            {durations.map(([stage, seconds]) => (
              <div key={stage}>
                <dt>{statusLabels[stage] || stage}</dt>
                <dd>{timeLabel(seconds)}</dd>
              </div>
            ))}
          </dl>
          {!!job.metadata.resource_wait_seconds && (
            <p>단계 시간에 포함된 자원 대기: {timeLabel(job.metadata.resource_wait_seconds)}</p>
          )}
        </details>
      )}
    </div>
  );
};
