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

const logTime = (at: string | null) => {
  if (at === null) {
    return '시각 미기록';
  }
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? '시각 확인 불가' : date.toLocaleString('ko-KR');
};
const logLevel = (level: string) =>
  (({ info: '정보', warning: '경고', error: '오류' }) as Record<string, string>)[level] || level;

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
  const entries = visibleLogs?.entries ?? [];
  const issues = entries.filter((entry) => ['warning', 'error'].includes(entry.level));
  // The API sorts timestamped events before undated responses; do not infer a live segment.
  const latestDatedEntry = [...entries].reverse().find((entry) => entry.at !== null);
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
      {hasChunkProgress && (
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
      {unitRecoveryEnabled && runId && (
        <UnitRecoveryPanel
          jobId={jobId}
          runId={runId}
          canManage={canManage}
          onChanged={onChanged}
        />
      )}
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
            {visibleLogs && (
              <>
                <div className="task-log-counts">
                  <span>기록된 요청 {visibleLogs.total_calls}건</span>
                  <span>표시된 요청 {visibleLogs.shown_calls}건</span>
                  <span>
                    {visibleLogs.received_responses == null
                      ? '응답 확인 건수 미제공'
                      : `응답 확인 ${visibleLogs.received_responses}건${progress ? '' : ' (표시된 요청 기준)'}`}
                  </span>
                </div>
                <p>요청 건수는 전체 예정 구간 수나 현재 실행 중인 구간 수를 뜻하지 않습니다.</p>
                {visibleLogs.has_more && <p>이전 요청 기록은 생략되었습니다.</p>}
              </>
            )}
            {issues.length > 0 && (
              <section className="task-log-issues" aria-label="기록된 경고 및 오류">
                <strong>확인할 경고·오류 {issues.length}건 (표시된 기록 기준)</strong>
                <ul>
                  {issues.map((entry, index) => (
                    <li data-level={entry.level} key={index}>
                      [{logLevel(entry.level)}] {entry.message}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <h3 className="task-console-heading">에이전트·툴 원본 로그</h3>
            {visibleLogs?.console?.content_policy === 'private_diagnostics_v1' && (
              <p className="task-console-policy">
                요청·응답·인증 본문과 자유형 출력은 숨깁니다. 실제 stdout/stderr 실행 진단만
                표시합니다.
              </p>
            )}
            {visibleLogs?.console?.truncated && <p>콘솔 로그 표시 상한에 도달했습니다.</p>}
            {visibleLogs?.console?.lines.length ? (
              <pre className="task-console-text">
                {visibleLogs.console.lines.map((line, index) => (
                  <span className="task-console-line" data-stream={line.stream} key={index}>
                    {`${logTime(line.at)} [${line.stream}] ${line.text}\n`}
                  </span>
                ))}
              </pre>
            ) : (
              !visibleError && <p>수집된 에이전트·툴 원본 로그가 없습니다.</p>
            )}
            <h3 className="task-console-heading">실행 기록 · 상태·요청 이력</h3>
            {latestDatedEntry && (
              <p className="task-log-latest">
                최근 시각이 기록된 이벤트: {logTime(latestDatedEntry.at)} —{' '}
                {latestDatedEntry.message}
              </p>
            )}
            {entries.length > 0 ? (
              <ul className="task-log-list" aria-label="처리 기록">
                {entries.map((entry, index) => (
                  <li data-level={entry.level} key={index}>
                    <span className="task-log-time">{logTime(entry.at)}</span>{' '}
                    <strong>[{logLevel(entry.level)}]</strong>
                    <p>{entry.message}</p>
                  </li>
                ))}
              </ul>
            ) : (
              !visibleError && <p>보존된 처리 기록이 없습니다.</p>
            )}
          </>
        )}
      </div>
    </section>
  );
};
