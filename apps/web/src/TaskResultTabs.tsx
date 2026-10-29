import { useEffect, useId, useRef, useState, type ReactNode, type KeyboardEvent } from 'react';
import { request } from './api';
import './task-result-tabs.css';

type TaskLog = {
  run_id: string;
  node_id: string;
  state: string;
  has_more: boolean;
  shown_calls: number;
  total_calls: number;
  entries: { at: string | null; level: string; message: string }[];
};
const states: Record<string, string> = {
  completed: '완료',
  running: '처리 중',
  held: '보류 · 응답 확인 필요',
  failed: '실패',
  cancelled: '취소됨',
  waiting: '대기 중',
  review_required: '검수 대기',
  quarantined: '늦은 결과 보존',
};

export const TaskResultTabs = ({
  jobId,
  runId,
  initialState,
  children,
}: {
  jobId: string;
  runId?: string;
  initialState: string;
  children: ReactNode;
}) => {
  const [active, setActive] = useState<'output' | 'logs'>('output');
  const [logs, setLogs] = useState<TaskLog | null>(null);
  const [loading, setLoading] = useState(!!runId);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const prefix = useId();
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const keyboard = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index;
    setActive(next === 0 ? 'output' : 'logs');
    tabs.current[next]?.focus();
  };
  useEffect(() => {
    const controller = new AbortController();
    setLogs(null);
    setError('');
    setActive('output');
    setLoading(!!runId);
    if (!runId) {
      return () => controller.abort();
    }
    const load = async () => {
      const turn = ++sequence.current;
      try {
        const value = await request<TaskLog>(`/renewal/jobs/${jobId}/runs/${runId}/logs`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted && turn === sequence.current) {
          if (value.run_id !== runId) {
            throw new Error('task identity changed');
          }
          setLogs(value);
          setError('');
        }
      } catch {
        if (!controller.signal.aborted && turn === sequence.current) {
          setError('최근 처리 기록을 불러오지 못했습니다.');
        }
      } finally {
        if (!controller.signal.aborted && turn === sequence.current) {
          setLoading(false);
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      sequence.current++;
    };
  }, [jobId, runId]);
  return (
    <section className="task-result-tabs">
      <p role="status">
        {error
          ? '상태 확인 필요'
          : loading && !logs
            ? '상태 확인 중'
            : states[logs?.state || initialState] || '상태 확인 필요'}
      </p>
      <div role="tablist" aria-label="태스크 상세" className="task-result-tablist">
        {(['output', 'logs'] as const).map((tab, index) => (
          <button
            type="button"
            role="tab"
            id={`${prefix}-${tab}-tab`}
            key={tab}
            ref={(element) => {
              tabs.current[index] = element;
            }}
            aria-selected={active === tab}
            aria-controls={`${prefix}-${tab}-panel`}
            tabIndex={active === tab ? 0 : -1}
            onClick={() => setActive(tab)}
            onKeyDown={(event) => keyboard(event, index)}
          >
            {tab === 'output' ? '출력' : '로그'}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${prefix}-output-panel`}
        aria-labelledby={`${prefix}-output-tab`}
        className="task-result-tab-panel"
        hidden={active !== 'output'}
        tabIndex={0}
      >
        {children}
      </div>
      <div
        role="tabpanel"
        id={`${prefix}-logs-panel`}
        aria-labelledby={`${prefix}-logs-tab`}
        className="task-result-tab-panel"
        hidden={active !== 'logs'}
        tabIndex={0}
      >
        {error && (
          <p role="alert">
            {error}
            {logs ? ' 아래는 마지막으로 확인한 기록입니다.' : ''}
          </p>
        )}
        {loading && !logs ? (
          <p>처리 기록을 불러오는 중입니다.</p>
        ) : (
          <>
            {logs?.has_more && (
              <p>
                전체 {logs.total_calls}개 요청 중 최근 {logs.shown_calls}개 기록입니다.
              </p>
            )}
            {logs?.entries.length ? (
              <ol className="task-log-list">
                {logs.entries.map((entry, index) => (
                  <li key={index} data-level={entry.level}>
                    {entry.at ? (
                      <time dateTime={entry.at}>{new Date(entry.at).toLocaleString('ko-KR')}</time>
                    ) : (
                      <span className="task-log-time">시각 기록 없음</span>
                    )}
                    <p>{entry.message}</p>
                  </li>
                ))}
              </ol>
            ) : (
              !error && <p>아직 기록된 로그가 없습니다.</p>
            )}
          </>
        )}
      </div>
    </section>
  );
};
