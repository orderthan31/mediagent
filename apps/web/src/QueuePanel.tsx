import { Button } from './hangyeol/primitives/button';
import { Badge } from './hangyeol/primitives/badge';
import { useEffect, useRef, useState } from 'react';
import { ArrowUp, ArrowDown, ChevronsUp, Pause, Play } from 'lucide-react';
import { request, type Job } from './api';
import { moveQueuedJob, type QueueState } from './queue-state';
import { Pagination, usePagination } from './Pagination';
import './queue-controls.css';

export const QueuePanel = ({
  jobs,
  onChanged,
}: {
  jobs: Job[];
  onChanged: () => Promise<void>;
}) => {
  const [state, setState] = useState<QueueState | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);
  const pending = useRef(false);
  const byId = new Map(jobs.map((job) => [job.job_id, job]));
  const ids = (state?.jobs || []).filter((id) => byId.get(id)?.status === 'QUEUED');
  const page = usePagination(ids, 'queue');
  const selection = selected.filter((id) => ids.includes(id));
  const refresh = async (signal?: AbortSignal) => {
    const next = await request<QueueState>('/queue', { signal });
    if (!signal?.aborted) {
      setState((previous) => (!previous || next.revision >= previous.revision ? next : previous));
    }
  };
  const change = async (operation: () => Promise<unknown>) => {
    if (pending.current) {
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      await operation();
      setConfirmCancel(false);
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '큐를 변경하지 못했습니다.');
    } finally {
      try {
        await refresh();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '큐 상태를 불러오지 못했습니다.');
      }
      pending.current = false;
      setBusy(false);
    }
  };
  const update = (changes: { paused?: boolean; order?: string[] }) =>
    change(() =>
      request('/queue', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: state?.revision, ...changes }),
      }),
    );
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        if (!pending.current) {
          await refresh(controller.signal);
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '큐 조회 실패');
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 2500);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  return (
    <section className="queue-panel" aria-label="실행 순서" aria-busy={busy}>
      <div className="queue-toolbar">
        <h2>
          실행 순서 <Badge>{state ? `${ids.length}개` : '개수 미확인'}</Badge>
        </h2>
        <Button
          variant="secondary"
          disabled={busy || !state}
          onClick={() => void update({ paused: !state?.paused })}
        >
          {state?.paused ? <Play size={16} /> : <Pause size={16} />}
          {state?.paused ? '작업 시작 재개' : '새 작업 시작 일시정지'}
        </Button>
      </div>
      <Badge tone="info">
        {!state
          ? '조회 중 · 상태 미확인'
          : state.paused
            ? '새 작업 시작 일시정지'
            : '자원에 맞춰 순서대로 시작'}
      </Badge>
      {state?.paused && <p className="muted">진행 중인 작업은 계속 처리됩니다.</p>}
      {error && (
        <p className="alert" role="alert">
          {error}
          {state
            ? ' 마지막 조회 정보입니다. 변경 전에 최신 상태를 다시 확인하세요.'
            : ' 큐 상태와 개수는 아직 확인되지 않았습니다.'}
        </p>
      )}
      <div className="queue-toolbar">
        <label>
          <input
            type="checkbox"
            checked={ids.length > 0 && selection.length === ids.length}
            disabled={busy || !ids.length}
            onChange={(event) => setSelected(event.target.checked ? ids : [])}
          />{' '}
          대기 작업 전체 선택
        </label>
        <Button
          variant="secondary"
          disabled={busy || !selection.length}
          onClick={() => setConfirmCancel(true)}
        >
          선택한 대기 작업 취소 ({selection.length})
        </Button>
      </div>
      {confirmCancel && (
        <div className="queue-confirm" role="group" aria-label="대기 작업 취소 확인">
          <p>선택한 대기 작업 {selection.length}개를 취소할까요? 원본 영상은 보관됩니다.</p>
          <Button
            variant="secondary"
            disabled={busy || !selection.length}
            onClick={() =>
              void change(() =>
                request('/queue/cancel-pending', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ job_ids: selection }),
                }),
              )
            }
          >
            취소 실행
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => setConfirmCancel(false)}>
            닫기
          </Button>
        </div>
      )}
      <ol className="queue-items" start={page.first || 1}>
        {page.items.map((id, pageIndex) => {
          const index = page.offset + pageIndex;
          return (
            <li key={id}>
              <label>
                <input
                  type="checkbox"
                  aria-label={`${byId.get(id)?.original_filename} 선택`}
                  checked={selection.includes(id)}
                  disabled={busy}
                  onChange={(event) =>
                    setSelected(
                      event.target.checked
                        ? [...selection, id]
                        : selection.filter((item) => item !== id),
                    )
                  }
                />
              </label>
              <span>{index + 1}</span>
              <a href={`#/jobs/${id}`}>{byId.get(id)?.original_filename}</a>
              <div className="queue-move">
                <Button
                  variant="secondary"
                  title="가장 먼저 처리"
                  aria-label="가장 먼저 처리"
                  disabled={busy || index === 0}
                  onClick={() => void update({ order: moveQueuedJob(ids, id, 0) })}
                >
                  <ChevronsUp size={16} />
                </Button>
                <Button
                  variant="secondary"
                  title="위로 이동"
                  aria-label="위로 이동"
                  disabled={busy || index === 0}
                  onClick={() => void update({ order: moveQueuedJob(ids, id, index - 1) })}
                >
                  <ArrowUp size={16} />
                </Button>
                <Button
                  variant="secondary"
                  title="아래로 이동"
                  aria-label="아래로 이동"
                  disabled={busy || index === ids.length - 1}
                  onClick={() => void update({ order: moveQueuedJob(ids, id, index + 1) })}
                >
                  <ArrowDown size={16} />
                </Button>
              </div>
            </li>
          );
        })}
      </ol>
      {state && <Pagination {...page} disabled={busy || !!error} />}
      {state && !error && !ids.length && <p className="muted">대기 중인 작업이 없습니다.</p>}
    </section>
  );
};
