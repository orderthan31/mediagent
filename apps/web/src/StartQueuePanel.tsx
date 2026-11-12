import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronsUp, Pause, Play } from 'lucide-react';
import { ApiError, request } from './api';
import { checkedStartQueue, type StartQueueSnapshot } from './start-queue-state';
import { moveQueuedJob } from './queue-state';
import { Button } from './hangyeol/primitives/button';
import { Pagination, usePagination } from './Pagination';
import './start-queue.css';

export const StartQueuePanel = ({ onChanged }: { onChanged: () => Promise<void> }) => {
  const [state, setState] = useState<StartQueueSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const pending = useRef(false);
  const sequence = useRef(0);
  const lifetime = useRef<AbortController | null>(null);
  const lastRevision = useRef<number | null>(null);
  const page = usePagination(state?.details || [], 'start-queue');
  const disabled = !state || busy || loading || !!error;
  const refresh = async (signal: AbortSignal, clearError = false) => {
    const turn = ++sequence.current;
    setLoading(true);
    try {
      const value = checkedStartQueue(await request<StartQueueSnapshot>('/queue', { signal }));
      if (!signal.aborted && turn === sequence.current) {
        if (lastRevision.current !== null && value.revision < lastRevision.current) {
          throw new Error('대기열 버전이 이전으로 바뀌었습니다. 최신 상태를 다시 확인하세요.');
        }
        lastRevision.current = value.revision;
        setState(value);
        if (clearError) {
          setError('');
        }
      }
    } catch (reason) {
      if (!signal.aborted && turn === sequence.current) {
        setError(reason instanceof Error ? reason.message : '대기열을 불러오지 못했습니다.');
      }
    } finally {
      if (!signal.aborted && turn === sequence.current) {
        setLoading(false);
      }
    }
  };
  const change = async (changes: { paused?: boolean; order?: string[] }) => {
    const controller = lifetime.current;
    if (disabled || pending.current || !controller || controller.signal.aborted || !state) {
      return;
    }
    pending.current = true;
    sequence.current++;
    setBusy(true);
    setLoading(false);
    setError('');
    try {
      checkedStartQueue(
        await request<StartQueueSnapshot>('/queue', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({ revision: state.revision, ...changes }),
        }),
      );
      await onChanged();
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(
          reason instanceof ApiError
            ? reason.message
            : '변경 응답을 확인하지 못했습니다. 대기열을 다시 확인하세요.',
        );
      }
    } finally {
      if (!controller.signal.aborted) {
        await refresh(controller.signal);
        if (!controller.signal.aborted) {
          setBusy(false);
        }
      }
      pending.current = false;
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    void refresh(controller.signal, true);
    const timer = setInterval(() => {
      if (!pending.current) {
        void refresh(controller.signal);
      }
    }, 4000);
    return () => {
      controller.abort();
      sequence.current++;
      clearInterval(timer);
    };
  }, [attempt]);
  return (
    <section
      className="queue-panel start-queue-panel"
      aria-label="새 작업 시작 대기열"
      aria-busy={busy || loading}
    >
      <div className="start-queue-heading">
        <h3>
          새 작업 시작 <span>{state ? `${state.jobs.length}개` : '개수 미확인'}</span>
        </h3>
        <Button
          variant="secondary"
          disabled={disabled}
          onClick={() => void change({ paused: !state?.paused })}
        >
          {state?.paused ? (
            <Play size={16} aria-hidden="true" />
          ) : (
            <Pause size={16} aria-hidden="true" />
          )}
          {state?.paused ? '작업 시작 재개' : '새 작업 시작 일시정지'}
        </Button>
      </div>
      <p role="status">
        {!state
          ? loading
            ? '대기열 확인 중'
            : '대기열 미확인'
          : state.paused
            ? '새 작업 시작 일시정지 중'
            : state.progression === 'disabled'
              ? '현재 새 작업 실행이 비활성입니다.'
              : '자원에 맞춰 순서대로 시작'}
      </p>
      <p>
        {state?.paused
          ? '진행 중인 작업은 계속 처리됩니다.'
          : '순서는 시작 우선순위입니다. 완료 순서는 달라질 수 있습니다.'}
      </p>
      {error && (
        <p role="alert">
          {error} {state ? '마지막 확인 정보입니다.' : '대기열과 개수는 미확인입니다.'}
        </p>
      )}
      {state?.progression === 'unconfirmed' && (
        <p role="alert">
          자동 시작 상태를 확인하지 못했습니다. 작업 상세에서 시작 조건을 확인하세요.
        </p>
      )}
      <Button
        variant="quiet"
        disabled={busy || loading}
        onClick={() => setAttempt((value) => value + 1)}
      >
        대기열 다시 확인
      </Button>
      <ol className="start-queue-items" start={page.offset + 1}>
        {page.items.map((job, offset) => {
          const index = page.offset + offset;
          return (
            <li key={job.job_id}>
              <div className="start-queue-file">
                <a href={`#/jobs/${job.job_id}`}>{job.original_filename || '파일명 기록 없음'}</a>
                <span>{state?.paused ? '시작 일시정지' : '시작 대기'}</span>
              </div>
              <small>
                #{job.ticket_number}
                {job.workflow_name ? ` · ${job.workflow_name}` : ''}
              </small>
              {job.access.can_manage && (
                <div className="start-queue-move">
                  {(
                    [
                      ['맨 앞으로', 0, ChevronsUp],
                      ['위로 이동', index - 1, ArrowUp],
                      ['아래로 이동', index + 1, ArrowDown],
                    ] as const
                  ).map(([label, destination, Icon]) => (
                    <Button
                      key={label}
                      variant="quiet"
                      aria-label={`작업 ${job.ticket_number} ${label}`}
                      title={label}
                      disabled={
                        disabled ||
                        destination < 0 ||
                        destination >= (state?.jobs.length || 0) ||
                        index === destination
                      }
                      onClick={() =>
                        state &&
                        void change({ order: moveQueuedJob(state.jobs, job.job_id, destination) })
                      }
                    >
                      <Icon size={16} aria-hidden="true" />
                      <span>{label}</span>
                    </Button>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {state && <Pagination {...page} disabled={disabled} />}
      {state && !loading && !error && !state.jobs.length && <p>시작 대기 중인 작업이 없습니다.</p>}
    </section>
  );
};
