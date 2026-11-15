// Public goal-owning agents and control nodes only. Internal tools stay inside cards.
export type ExecutionDefinition = {
  nodes: { id: string; type: string }[];
  edges: { id: string; source: { node: string }; target: { node: string } }[];
};
export type ExecutionTool = {
  node_id: string;
  role: string;
  label: string;
  state: string;
  run_id: string | null;
  reason?: string;
};
export type ExecutionAgent = {
  id: string;
  type: string;
  label: string;
  state: string;
  status_label?: string;
  reason?: string;
  selected_tool_id?: string;
  tools: ExecutionTool[];
};
/** Pass the TaskLogs projection keyed by run_id, not agent/node ID or model calls. */
export type ExecutionRunProgress = {
  run_id: string;
  state?: string;
  display_state?: string;
  stage_label?: string;
  progress?: {
    planned_segments?: number | null;
    completed_segments?: number;
    failed_segments?: number;
    finished_segments?: number;
    active_segments?: number[];
  };
};
export type ExecutionProgressMap = Record<string, ExecutionRunProgress | undefined>;
export const executionStateLabel = (state: string) =>
  ({
    running: '처리 중',
    preparing: '준비 중',
    failed: '실패',
    held: '보류',
    waiting: '대기',
    pending: '대기',
    queued: '실행 대기',
    completed: '완료',
    succeeded: '완료',
    skipped: '건너뜀',
    cancelled: '취소',
    canceled: '취소',
    blocked: '진행 차단',
    awaiting_review: '검수 대기',
  })[state] || '상태 확인 중';
const blocker = (state: string) => ['failed', 'held', 'blocked', 'awaiting_review'].includes(state);
export const executionTask = (agent: ExecutionAgent, progress: ExecutionProgressMap) => {
  const tool = agent.tools.find((item) => item.node_id === agent.selected_tool_id);
  const candidate = tool?.run_id ? progress[tool.run_id] : undefined;
  const run = candidate?.run_id === tool?.run_id ? candidate : undefined;
  // An explicit held/cancelled/failed agent must not be revived by an old raw run status.
  const terminal =
    blocker(agent.state) ||
    ['completed', 'succeeded', 'cancelled', 'canceled', 'skipped'].includes(agent.state);
  const state = terminal ? agent.state : run?.display_state || agent.state;
  return { agent, tool, run, state };
};
export const currentExecutionTask = (tasks: ReturnType<typeof executionTask>[]) =>
  tasks.find((task) => ['running', 'preparing'].includes(task.state))?.agent.id ||
  tasks.find((task) => blocker(task.state))?.agent.id ||
  null;
const count = (value: unknown): number | null =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
export const executionProgress = (run?: ExecutionRunProgress) => {
  const source = run?.progress;
  const total = count(source?.planned_segments);
  const completed = count(source?.completed_segments);
  const failed = count(source?.failed_segments);
  const processed = completed !== null && failed !== null ? completed + failed : null;
  const finished = count(source?.finished_segments);
  const inconsistent =
    (processed !== null && total !== null && processed > total) ||
    (processed !== null && finished !== null && processed !== finished) ||
    (total === 0 && Boolean(source?.active_segments?.length));
  return {
    total,
    completed,
    failed,
    processed,
    inconsistent,
    determinate: !inconsistent && total !== null && total > 0 && processed !== null,
    empty: !inconsistent && total === 0 && processed === 0,
    active: source?.active_segments || [],
  };
};
