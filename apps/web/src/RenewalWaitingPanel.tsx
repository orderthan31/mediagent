import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { Button } from './hangyeol/primitives/button';
import './renewal-waiting.css';

type Delivery = { phase: string; run_status: string; count: number };
type WaitingJob = {
  job_id: string;
  ticket_number: string;
  status: string;
  original_filename: string | null;
  workflow_name: string | null;
  queued_at: string;
  deliveries: Delivery[];
  access: { can_manage: boolean };
};
export type WaitingSnapshot = { jobs: WaitingJob[]; has_more: boolean; limit: number };

export const deliveryLabel = ({ phase, run_status }: Delivery) => {
  if (phase === 'unknown') {
    return '전송 결과 확인 필요';
  }
  const labels: Record<string, string> = {
    pending: '전송 대기',
    sending: '전송 중',
    sent: '수신 확인 대기',
    received: run_status === 'running' ? '처리 중' : '수신됨',
  };
  const terminal: Record<string, string> = {
    failed: '실행 실패',
    completed: '실행 완료',
    cancelled: '실행 취소',
    quarantined: '결과 확인 필요',
  };
  const label = labels[phase] || '전달 상태 확인 필요';
  return terminal[run_status] ? `${label} · ${terminal[run_status]}` : label;
};

export const WaitingContents = ({
  state,
  loading,
  error,
  onReload,
}: {
  state: WaitingSnapshot | null;
  loading: boolean;
  error: string;
  onReload: () => void;
}) => (
  <section className="renewal-waiting-panel" aria-label="전달 현황" aria-busy={loading}>
    <div className="renewal-waiting-heading">
      <span role="status">
        {state
          ? `${error || loading ? '마지막 확인 · ' : ''}${state.jobs.length}개${state.has_more ? ' 표시 · 추가 항목 있음' : ''}`
          : loading
            ? '전달 현황 확인 중'
            : '전달 현황 미확인'}
      </span>
      <Button variant="quiet" disabled={loading} onClick={onReload}>
        다시 확인
      </Button>
    </div>
    {error && (
      <p role="alert">
        {error}
        {state ? ' 마지막 확인 결과입니다.' : ' 현재 목록을 확인하지 못했습니다.'}
      </p>
    )}
    {!!state?.jobs.length && (
      <ul className="renewal-waiting-jobs">
        {state.jobs.map((job) => (
          <li key={job.job_id}>
            <div className="renewal-waiting-job-title">
              <strong>#{job.ticket_number}</strong>
              <span>{job.original_filename || '파일명 기록 없음'}</span>
            </div>
            {job.workflow_name && <small>{job.workflow_name}</small>}
            <ul
              className="renewal-delivery-states"
              aria-label={`작업 ${job.ticket_number} 전달 상태`}
            >
              {job.deliveries.map((delivery) => (
                <li key={`${delivery.phase}:${delivery.run_status}`} data-phase={delivery.phase}>
                  {deliveryLabel(delivery)} · {delivery.count}건
                </li>
              ))}
            </ul>
            {job.deliveries.some((delivery) => delivery.phase === 'unknown') && (
              <p className="renewal-waiting-warning">자동으로 다시 보내지 않습니다.</p>
            )}
            <a href={`#/jobs/${job.job_id}`}>
              {job.access.can_manage &&
              ['waiting', 'running', 'review_required'].includes(job.status)
                ? '상세 · 취소 확인'
                : '상세 보기'}
            </a>
            {!job.access.can_manage && <span className="renewal-waiting-readonly">읽기 전용</span>}
          </li>
        ))}
      </ul>
    )}
    {state && !loading && !error && !state.jobs.length && <p>대기 중인 전달이 없습니다.</p>}
  </section>
);

export const RenewalWaitingPanel = () => {
  const [state, setState] = useState<WaitingSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const sequence = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      const turn = ++sequence.current;
      setLoading(true);
      try {
        const value = await request<WaitingSnapshot>('/renewal/execution-waiting', {
          signal: controller.signal,
        });
        if (!value || !Array.isArray(value.jobs) || typeof value.has_more !== 'boolean') {
          throw new Error('전달 현황 응답을 확인하지 못했습니다.');
        }
        if (!controller.signal.aborted && turn === sequence.current) {
          setState(value);
          setError('');
        }
      } catch (reason) {
        if (!controller.signal.aborted && turn === sequence.current) {
          setError(reason instanceof Error ? reason.message : '전달 현황을 불러오지 못했습니다.');
        }
      } finally {
        if (!controller.signal.aborted && turn === sequence.current) {
          setLoading(false);
          timer = setTimeout(load, 4000);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      sequence.current++;
      clearTimeout(timer);
    };
  }, [attempt]);
  return (
    <WaitingContents
      state={state}
      loading={loading}
      error={error}
      onReload={() => setAttempt((value) => value + 1)}
    />
  );
};
