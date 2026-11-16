import { useEffect, useId, useRef, useState, type ReactNode, type KeyboardEvent } from 'react';
import { request } from './api';
import { UnitRecoveryPanel } from './UnitRecoveryPanel';

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
  received_responses?: number;
  progress?: {
    planned_segments: number | null;
    completed_segments: number;
    failed_segments: number;
    active_segments: number[];
    unresolved_segments: number;
    observed_segments: number;
    total_calls: number;
    finished_segments: number;
  };
  entries: { at: string | null; level: string; message: string }[];
  console: {
    available: boolean;
    content_policy?: string;
    truncated: boolean;
    lines: { at: string | null; stream: string; text: string }[];
    terminal_lines?: { at: string | null; stream: string; text: string }[];
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
  initialTab = 'output',
  activeTab,
  onTabChange,
  canManage = false,
  unitRecoveryEnabled = false,
  showProgress = true,
  onChanged,
}: {
  jobId: string;
  runId?: string;
  initialState: string;
  toolbar?: ReactNode;
  children: ReactNode;
  initialTab?: 'output' | 'logs';
  activeTab?: 'output' | 'logs';
  onTabChange?: (tab: 'output' | 'logs') => void;
  canManage?: boolean;
  unitRecoveryEnabled?: boolean;
  showProgress?: boolean;
  onChanged?: () => void | Promise<void>;
}) => {
  const [localActive, setLocalActive] = useState<'output' | 'logs'>(initialTab);
  const active = activeTab ?? localActive;
  const setActive = (tab: 'output' | 'logs') => {
    setLocalActive(tab);
    onTabChange?.(tab);
  };
  const [logs, setLogs] = useState<TaskLog | null>(null);
  const [loading, setLoading] = useState(!!runId);
  const [error, setError] = useState('');
  const [completedScope, setCompletedScope] = useState<string | null>(null);
  const currentScope = runId ? jobId + ':' + runId : null;
  const visibleLogs = taskLogForRun(logs, runId);
  const progress = visibleLogs?.progress;
  const plannedSegments = progress?.planned_segments;
  const finishedSegments = progress?.finished_segments;
  const validPlannedProgress =
    plannedSegments != null &&
    Number.isSafeInteger(plannedSegments) &&
    plannedSegments > 0 &&
    finishedSegments != null &&
    Number.isSafeInteger(finishedSegments) &&
    finishedSegments >= 0 &&
    finishedSegments <= plannedSegments;
  const hasChunkProgress = Boolean(progress) || (visibleLogs?.total_calls ?? 0) > 0;
  const consoleOutput = visibleLogs?.console;
  const terminalLines =
    consoleOutput?.content_policy === 'private_diagnostics_v1'
      ? consoleOutput.terminal_lines || []
      : consoleOutput?.lines || [];
  const terminalText = terminalLines.map((line) => line.text).join('\n');
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
    let timer: number | undefined;
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
          timer = window.setTimeout(() => void load(), 4000);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
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
      {unitRecoveryEnabled && runId && (
        <UnitRecoveryPanel
          jobId={jobId}
          runId={runId}
          canManage={canManage}
          onChanged={onChanged}
        />
      )}
      {showProgress && hasChunkProgress && (
        <section className="task-chunk-progress" aria-label="청크 진행 상태">
          <h3>청크 진행</h3>
          {progress ? (
            <>
              <div className="task-log-counts">
                <span>전체 {plannedSegments ?? '확인 중'}</span>
                <span>완료 {progress.completed_segments}</span>
                <span>실패 {progress.failed_segments}</span>
                {progress.unresolved_segments > 0 && (
                  <span>결과 미확인 {progress.unresolved_segments}</span>
                )}
              </div>
              {validPlannedProgress && (
                <>
                  <progress
                    aria-label="청크 처리 진행"
                    max={plannedSegments ?? undefined}
                    value={finishedSegments}
                  />
                  <p>
                    처리 {finishedSegments} / {plannedSegments}청크 · 성공과 실패를 구분해
                    표시합니다.
                  </p>
                </>
              )}
              {plannedSegments == null && <p>전체 청크 수를 아직 확인하지 못했습니다.</p>}
              {plannedSegments === 0 && finishedSegments === 0 ? (
                <p>처리할 청크가 없습니다.</p>
              ) : (
                plannedSegments != null &&
                !validPlannedProgress && <p>진행 수치를 확인해야 합니다.</p>
              )}
              {progress.active_segments.length > 0 && (
                <p>현재 {progress.active_segments.join(', ')}번 청크 처리 중</p>
              )}
            </>
          ) : (
            <p>전체 청크 수와 구간별 진행 정보는 아직 제공되지 않았습니다.</p>
          )}
        </section>
      )}
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
            {consoleOutput?.truncated && <small>이전 로그 일부 생략됨</small>}
            <pre className="task-console-text" aria-label="터미널 출력">
              {terminalText || '로그 없음'}
            </pre>
          </>
        )}
      </div>
    </section>
  );
};
