import { useEffect, useId, useRef, useState, type ReactNode, type KeyboardEvent } from 'react';
import {
  currentExecutionTask,
  executionProgress,
  executionStateLabel,
  executionTask,
  type ExecutionAgent,
  type ExecutionDefinition,
  type ExecutionProgressMap,
} from './job-execution-flow';
import './job-execution-flow.css';

export type JobExecutionFlowProps = {
  /** Job identity: changing it resets manual browsing and follow mode. */
  executionId: string;
  /** The public agent/control graph, never the internal tool graph. */
  definition: ExecutionDefinition;
  agents: ExecutionAgent[];
  progressByRunId?: ExecutionProgressMap;
  /** Same TaskLogs envelopes keyed by public agent ID; run_id is still checked. */
  progressByAgentId?: ExecutionProgressMap;
  details?: ReactNode;
  edgeStates?: Record<string, { state: string; label: string }>;
  selectedNodeId?: string;
  onSelect?: (nodeId: string, source?: 'user' | 'follow') => void;
  className?: string;
};

export const JobExecutionFlow = (props: JobExecutionFlowProps) => (
  <ExecutionFlowSession key={props.executionId} {...props} />
);

const ExecutionFlowSession = ({
  definition,
  agents,
  progressByRunId = {},
  progressByAgentId = {},
  details,
  edgeStates = {},
  selectedNodeId,
  onSelect,
  className = '',
}: JobExecutionFlowProps) => {
  const titleId = useId();
  const viewport = useRef<HTMLDivElement>(null);
  const cards = useRef(new Map<string, HTMLLIElement>());
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const [following, setFollowing] = useState(true);
  const [localSelected, setLocalSelected] = useState('');
  const onSelectRef = useRef(onSelect);
  const scopedProgress = { ...progressByRunId };
  agents.forEach((agent) => {
    const projection = progressByAgentId[agent.id];
    if (projection) {
      scopedProgress[projection.run_id] = projection;
    }
  });
  const tasks = definition.nodes.map((node) =>
    executionTask(
      agents.find((agent) => agent.id === node.id) || {
        id: node.id,
        type: node.type,
        label: node.type,
        state: 'unknown',
        tools: [],
      },
      scopedProgress,
    ),
  );
  const currentId = currentExecutionTask(tasks);
  const selected = selectedNodeId ?? (following ? currentId || localSelected : localSelected);
  const current = tasks.find((task) => task.agent.id === currentId);
  const select = (id: string) => {
    setFollowing(false);
    setLocalSelected(id);
    onSelect?.(id, 'user');
  };
  const center = (id: string, focus = false) => {
    const container = viewport.current;
    const card = cards.current.get(id);
    if (!container || !card) {
      return;
    }
    const outer = container.getBoundingClientRect();
    const inner = card.getBoundingClientRect();
    container.scrollTo({
      top:
        container.scrollTop + inner.top - outer.top - (container.clientHeight - inner.height) / 2,
      behavior: 'instant',
    });
    if (focus) {
      buttons.current.get(id)?.focus({ preventScroll: true });
    }
  };
  const focusCurrent = () => {
    if (!currentId) {
      return;
    }
    setFollowing(true);
    setLocalSelected(currentId);
    onSelect?.(currentId, 'user');
    center(currentId, true);
  };
  const navigate = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next =
      event.key === 'ArrowDown'
        ? Math.min(tasks.length - 1, index + 1)
        : event.key === 'ArrowUp'
          ? Math.max(0, index - 1)
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? tasks.length - 1
              : -1;
    if (next < 0) {
      return;
    }
    event.preventDefault();
    setFollowing(false);
    center(tasks[next].agent.id, true);
  };

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);
  useEffect(() => {
    if (following && currentId) {
      center(currentId);
      onSelectRef.current?.(currentId, 'follow');
    }
    // Only task identity changes recenter, never each progress poll; no keyboard focus stealing.
  }, [currentId, following]);

  return (
    <section className={`job-execution-flow ${className}`} aria-labelledby={titleId}>
      <header className="job-execution-flow__header">
        <div>
          <h3 id={titleId}>작업 진행</h3>
          <p role="status">
            {current
              ? `${current.agent.label} · ${executionStateLabel(current.state)}`
              : '현재 실행 중인 단계 없음'}
          </p>
        </div>
        <button
          type="button"
          className="job-execution-flow__focus"
          disabled={!currentId}
          onClick={focusCurrent}
        >
          현재 단계로 이동
        </button>
      </header>
      <div
        className="job-execution-flow__viewport"
        ref={viewport}
        onWheel={() => setFollowing(false)}
        onTouchStart={() => setFollowing(false)}
      >
        {tasks.length === 0 ? (
          <p className="job-execution-flow__empty">표시할 작업 단계가 없습니다.</p>
        ) : (
          <ol className="job-execution-flow__tasks" aria-label="작업 단계">
            {tasks.map(({ agent, tool, run, state }, index) => {
              const progress = executionProgress(run);
              const outgoing = definition.edges.filter(
                (edge) =>
                  edge.source.node === agent.id &&
                  tasks.some((task) => task.agent.id === edge.target.node),
              );
              const active = ['running', 'preparing'].includes(state) ? progress.active : [];
              return (
                <li
                  key={agent.id}
                  ref={(element) => {
                    if (element) {
                      cards.current.set(agent.id, element);
                    } else {
                      cards.current.delete(agent.id);
                    }
                  }}
                  className="job-execution-flow__task"
                  data-task-id={agent.id}
                  data-node-id={agent.id}
                  data-state={state}
                  data-selected={selected === agent.id}
                  aria-current={currentId === agent.id ? 'step' : undefined}
                >
                  <button
                    type="button"
                    className="job-execution-flow__select"
                    aria-label={`${agent.label} 선택`}
                    aria-pressed={selected === agent.id}
                    ref={(element) => {
                      if (element) {
                        buttons.current.set(agent.id, element);
                      } else {
                        buttons.current.delete(agent.id);
                      }
                    }}
                    onClick={() => select(agent.id)}
                    onKeyDown={(event) => navigate(event, index)}
                  >
                    <strong>{agent.label}</strong>
                    <span>{executionStateLabel(state)}</span>
                  </button>
                  <div className="job-execution-flow__body">
                    {tool && (
                      <p className="job-execution-flow__stage">
                        {agent.tools.findIndex((item) => item.node_id === tool.node_id) + 1}/
                        {agent.tools.length} 단계 · {run?.stage_label || tool.label}
                      </p>
                    )}
                    {agent.reason && <p className="job-execution-flow__reason">{agent.reason}</p>}
                    {run?.progress ? (
                      <div className="job-execution-flow__progress">
                        <p>
                          {progress.empty
                            ? '계획된 처리 구간 없음'
                            : `처리 ${progress.processed ?? '미확인'} / ${progress.total ?? '전체 미정'}`}
                        </p>
                        <p>
                          성공 {progress.completed ?? '미확인'} · 실패 {progress.failed ?? '미확인'}
                        </p>
                        {progress.determinate && (
                          <progress
                            aria-label={`${agent.label} 처리 진행`}
                            max={progress.total!}
                            value={progress.processed!}
                            aria-valuetext={`${progress.processed}개 처리, 성공 ${progress.completed}개, 실패 ${progress.failed}개, 전체 ${progress.total}개`}
                          />
                        )}
                        {progress.inconsistent && <p>진행 수치 확인 필요</p>}
                        {active.length > 0 && <p>현재 {active.join(', ')}번 구간</p>}
                      </div>
                    ) : (
                      <p className="job-execution-flow__unknown">
                        {['waiting', 'pending', 'queued'].includes(state)
                          ? '시작 대기'
                          : '전체 처리량 미확인'}
                      </p>
                    )}
                    {outgoing.length > 0 && (
                      <ul
                        className="job-execution-flow__edges"
                        aria-label={`${agent.label} 다음 연결`}
                      >
                        {outgoing.map((edge) => (
                          <li key={edge.id} data-edge-state={edgeStates[edge.id]?.state}>
                            <span aria-hidden="true">↳</span>
                            <button
                              type="button"
                              onClick={() => {
                                select(edge.target.node);
                                center(edge.target.node, true);
                              }}
                            >
                              {
                                tasks.find((task) => task.agent.id === edge.target.node)?.agent
                                  .label
                              }
                              {edgeStates[edge.id]?.label && (
                                <span> · {edgeStates[edge.id].label}</span>
                              )}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
      {details && (
        <div
          className="job-execution-flow__details"
          onPointerDown={() => setFollowing(false)}
          onKeyDown={() => setFollowing(false)}
        >
          {details}
        </div>
      )}
    </section>
  );
};
