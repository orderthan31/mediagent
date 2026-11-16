import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import {
  inspectResume,
  resumeAttempt,
  resumeExistingJob,
  resumeProof,
  type ResumeJobSnapshot,
} from './job-resume.mjs';
import './job-resume.css';

export type JobResumeControlProps = {
  job: ResumeJobSnapshot;
  onChanged: () => void | Promise<unknown>;
};

// The key fences pending preflight reads when the parent changes jobs.
export const JobResumeControl = (props: JobResumeControlProps) => (
  <ResumeSession key={props.job.id} {...props} />
);

const ResumeSession = ({ job, onChanged }: JobResumeControlProps) => {
  const current = useRef(job);
  current.current = job;
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const locked = Boolean(resumeAttempt(job));
  const eligible = Boolean(resumeProof(job));
  const notify = async () => {
    if (!mounted.current) {
      return;
    }
    try {
      await onChanged();
    } catch {
      if (mounted.current) {
        setMessage('작업 화면을 갱신하지 못했습니다. 실행 상태 확인으로 다시 조회하세요.');
      }
    }
  };
  const check = async () => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setBusy(true);
    try {
      const fresh = await inspectResume(job.id, request);
      if (!mounted.current) {
        return;
      }
      setMessage(`현재 작업 상태: ${fresh.status}. 실행 요청은 다시 보내지 않았습니다.`);
      await notify();
    } catch {
      if (mounted.current) {
        setMessage('실행 상태를 확인하지 못했습니다. 조회만 다시 시도할 수 있습니다.');
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setBusy(false);
      }
    }
  };
  const resume = async () => {
    if (inFlight.current || locked || !eligible) {
      return;
    }
    inFlight.current = true;
    setBusy(true);
    const proof = resumeProof(job);
    const result = await resumeExistingJob(
      job,
      request,
      () =>
        mounted.current &&
        current.current.id === job.id &&
        current.current.revision === job.revision &&
        resumeProof(current.current) === proof,
    );
    if (mounted.current) {
      setMessage(
        result.state === 'sent'
          ? '이어서 실행을 요청했습니다. 실행 상태를 확인하세요.'
          : result.state === 'uncertain'
            ? '실행 요청의 응답을 확인하지 못했습니다. 중복 실행을 막기 위해 재전송하지 않습니다. 실행 상태 확인만 사용할 수 있습니다.'
            : result.state === 'read-error'
              ? '실행 전 안전 확인을 완료하지 못해 실행 요청을 보내지 않았습니다.'
              : '작업 상태가 달라져 실행 요청을 보내지 않았습니다. 갱신된 상태를 확인하세요.',
      );
      await notify();
    }
    inFlight.current = false;
    if (mounted.current) {
      setBusy(false);
    }
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  if (!eligible && !message && !locked) {
    return null;
  }
  return (
    <section className="job-resume-control" aria-label="복구 후 이어서 실행" aria-busy={busy}>
      <p>복구 결과가 적용됐습니다. 아래 버튼으로 이 작업의 남은 태스크를 이어서 실행하세요.</p>
      <small>다음 단계에는 기존 승인 범위의 유료 모델 호출이 포함될 수 있습니다.</small>
      <div className="job-resume-control__actions">
        <button
          type="button"
          className="job-resume-control__primary"
          disabled={!eligible || busy || locked || Boolean(resumeAttempt(job))}
          onClick={() => void resume()}
        >
          이어서 실행
        </button>
        <button type="button" disabled={busy} onClick={() => void check()}>
          실행 상태 확인
        </button>
      </div>
      {message && <p role="status">{message}</p>}
      {locked && !message && (
        <p role="status">
          이 작업의 실행 요청을 이미 보냈거나 확인 중입니다. 재전송하지 않고 상태만 확인할 수
          있습니다.
        </p>
      )}
    </section>
  );
};
