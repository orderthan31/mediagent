import { useEffect, useId, useRef, useState, type ReactNode, type KeyboardEvent } from 'react';
import { request } from './api';
import { taskLogForRun } from './task-log-scope.mjs';
import './task-result-tabs.css';

type TaskLog = {
  run_id: string;
  node_id: string;
  state: string;
  display_state?: string;
  has_more: boolean;
  shown_calls: number;
  total_calls: number;
  entries: { at: string | null; level: string; message: string }[];
  console: {
    available: boolean;
    truncated: boolean;
    lines: { at: string; stream: string; text: string }[];
  };
};
const states: Record<string, string> = {
  completed: '완료',
  preparing: '준비 중',
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
  toolbar,
  children,
}: {
  jobId: string;
  runId?: string;
  initialState: string;
  toolbar?: ReactNode;
  children: ReactNode;
}) => {
  const [active, setActive] = useState<'output' | 'logs'>('output');
  const [logs, setLogs] = useState<TaskLog | null>(null);
  const [loading, setLoading] = useState(!!runId);
  const [error, setError] = useState('');
  const [completedScope, setCompletedScope] = useState<string | null>(null);
  const currentScope = runId ? jobId + ':' + runId : null;
  const visibleLogs = taskLogForRun(logs, runId);
  const pending = Boolean(runId) && (loading || completedScope !== currentScope);
  const visibleError = completedScope === currentScope ? error : '';
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
    setCompletedScope(null);
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
          setCompletedScope(jobId + ':' + runId);
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
        {visibleError
          ? '상태 확인 필요'
          : pending && !visibleLogs
            ? '상태 확인 중'
            : states[visibleLogs?.display_state || visibleLogs?.state || initialState] ||
              '상태 확인 필요'}
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
      {toolbar}
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
        {visibleError && (
          <p role="alert">
            {visibleError}
            {visibleLogs ? ' 아래는 마지막으로 확인한 기록입니다.' : ''}
          </p>
        )}
        {pending && !visibleLogs ? (
          <p>처리 기록을 불러오는 중입니다.</p>
        ) : (
          <>
            {visibleLogs?.console?.truncated && <p>콘솔 로그 표시 상한에 도달했습니다.</p>}
            {visibleLogs?.console?.lines.length ? (
              <pre className="task-console-text">
                {visibleLogs.console.lines.map((line, index) => (
                  <span className="task-console-line" data-stream={line.stream} key={index}>
                    {`${new Date(line.at).toLocaleString('ko-KR')} [${line.stream}] ${line.text}\n`}
                  </span>
                ))}
              </pre>
            ) : (
              !visibleError && <p>보존된 콘솔 로그가 없습니다.</p>
            )}
          </>
        )}
      </div>
    </section>
  );
};
