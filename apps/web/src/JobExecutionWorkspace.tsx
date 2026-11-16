import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { executionStateLabel } from './job-execution-flow';
import './job-execution-workspace.css';

export type WorkspaceTab = 'progress' | 'data' | 'logs';
export type WorkspaceStage = {
  id: string;
  label: string;
  state: string;
  reason?: string;
  runId?: string;
  completed?: number;
  failed?: number;
  planned?: number | null;
};
export const JobExecutionWorkspace = ({
  activeTab,
  onTabChange,
  progress,
  data,
  logs,
  status,
  stages,
  selectedStageId,
  onStageSelect,
  onStageLogs,
  metadata,
}: {
  activeTab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  progress: ReactNode;
  data: ReactNode;
  logs: ReactNode;
  status: string;
  stages: WorkspaceStage[];
  selectedStageId?: string;
  onStageSelect: (stageId: string) => void;
  onStageLogs: (stageId: string, runId: string) => void;
  metadata?: { label: string; value: string }[];
}) => {
  const prefix = useId();
  const [summaryOpen, setSummaryOpen] = useState(false);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const keys: WorkspaceTab[] = ['progress', 'data', 'logs'];
  const keyboard = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? 2
          : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
    onTabChange(keys[next]);
    tabs.current[next]?.focus();
  };
  return (
    <section className="job-workspace" aria-label="작업 실행 상세">
      <div className="job-workspace__topbar">
        <div role="tablist" aria-label="작업 상세 보기" className="job-workspace__tabs">
          {keys.map((tab, index) => (
            <button
              key={tab}
              type="button"
              role="tab"
              id={`${prefix}-${tab}-tab`}
              aria-controls={`${prefix}-${tab}-panel`}
              aria-selected={activeTab === tab}
              tabIndex={activeTab === tab ? 0 : -1}
              ref={(element) => {
                tabs.current[index] = element;
              }}
              onClick={() => onTabChange(tab)}
              onKeyDown={(event) => keyboard(event, index)}
            >
              {{ progress: '진행', data: '데이터·결과', logs: '로그' }[tab]}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="job-workspace__summary-toggle"
          aria-expanded={summaryOpen}
          aria-controls={`${prefix}-summary`}
          onClick={() => setSummaryOpen(!summaryOpen)}
        >
          실행 정보 {summaryOpen ? '접기' : '보기'}
        </button>
      </div>
      <div className="job-workspace__body">
        <div className="job-workspace__content">
          {keys.map((tab) => (
            <div
              key={tab}
              id={`${prefix}-${tab}-panel`}
              role="tabpanel"
              aria-labelledby={`${prefix}-${tab}-tab`}
              hidden={activeTab !== tab}
              tabIndex={0}
              className={`job-workspace__panel is-${tab}`}
            >
              {{ progress, data, logs }[tab]}
            </div>
          ))}
        </div>
        <aside
          id={`${prefix}-summary`}
          className={`job-workspace__summary ${summaryOpen ? 'is-open' : ''}`}
          aria-label="실행 정보"
        >
          <h3>실행 정보</h3>
          <dl>
            <div>
              <dt>상태</dt>
              <dd>{status}</dd>
            </div>
            {metadata?.map((row) => (
              <div key={row.label}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
          <h3>처리 과정</h3>
          <ol className="job-workspace__timeline">
            {stages.map((stage) => (
              <li
                key={stage.id}
                data-stage-id={stage.id}
                data-state={stage.state}
                className={selectedStageId === stage.id ? 'is-selected' : ''}
              >
                <button
                  type="button"
                  className="job-workspace__stage"
                  onClick={() => onStageSelect(stage.id)}
                  aria-label={`${stage.label} 단계 보기`}
                >
                  <span className="job-workspace__stage-dot" aria-hidden="true" />
                  <span>
                    <strong>{stage.label}</strong>
                    <small>{executionStateLabel(stage.state)}</small>
                  </span>
                </button>
                {(stage.completed != null || stage.failed != null) && (
                  <p className="job-workspace__stage-counts">
                    {stage.completed != null ? `성공 ${stage.completed}` : ''}
                    {stage.failed != null ? ` · 실패 ${stage.failed}` : ''}
                    {stage.planned != null ? ` / 전체 ${stage.planned}` : ''}
                  </p>
                )}
                {stage.reason && ['failed', 'held', 'blocked'].includes(stage.state) && (
                  <p className="job-workspace__stage-reason">{stage.reason}</p>
                )}
                {stage.runId && (
                  <button
                    type="button"
                    className="job-workspace__stage-logs"
                    onClick={() => onStageLogs(stage.id, stage.runId!)}
                  >
                    {['failed', 'held', 'blocked'].includes(stage.state)
                      ? '오류 로그'
                      : '단계 로그'}
                  </button>
                )}
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </section>
  );
};
