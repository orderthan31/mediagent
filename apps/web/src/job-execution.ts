import type { Job } from './api';
import type { CanvasDefinition, CanvasSpec } from './WorkflowCanvas';
import { resolvePorts } from './workflow-spec';

export type Cue = { start: number; end: number; text: string };
export type JobPreview = {
  video_available: boolean;
  expired: boolean;
  tracks: Record<'original' | 'translated', { available: boolean; partial: boolean; cues: Cue[] }>;
};
export type ExecutionArtifact = {
  id: string;
  label: string;
  type: string;
  url?: string;
  text?: string;
  data?: unknown;
  cues?: Cue[];
  partial?: boolean;
  expired?: boolean;
  track?: 'original' | 'translated';
  final?: boolean;
};
export type NodeRun = {
  id: string;
  node_id: string;
  status: string;
  attempt: number;
  iteration: number;
  generation: number;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  progress?: number;
  settings: Record<string, unknown> | null;
  model?: { name: string; model: string; provider: string; revision: number };
  inputs: ExecutionArtifact[];
  outputs: ExecutionArtifact[];
  error?: { code: string; message: string };
  events?: { at: string; message: string }[];
};
export type JobExecution = {
  version: 1;
  job_id: string;
  source: 'snapshot' | 'legacy_stages' | 'fixture';
  definition: CanvasDefinition;
  catalog: CanvasSpec[];
  runs: NodeRun[];
  inputs: ExecutionArtifact[];
  outputs: ExecutionArtifact[];
  notice?: string;
};
export const runLabels: Record<string, string> = {
  pending: '대기',
  running: '처리 중',
  completed: '완료',
  failed: '실패',
  review_required: '검수 대기',
  cancelled: '취소',
  skipped: '건너뜀',
  quarantined: '결과 격리',
  unknown: '기록 미제공',
};

// A terminal is a read-only projection of graph sink ports, never a new saved
// workflow node or a hard-coded video output. Branches remain separate edges.
export const executionGraph = (execution: JobExecution) => {
  const definition = structuredClone(execution.definition);
  const catalog = [...execution.catalog];
  const sinks = definition.nodes.filter(
    (node) => !definition.edges.some((edge) => edge.source.node === node.id),
  );
  const inputs: Record<string, string> = {};
  for (const node of sinks) {
    const spec = resolvePorts(
      catalog.find((item) => item.id === node.type),
      node.options,
    );
    for (const [port, type] of Object.entries(spec?.outputs || {})) {
      const terminalPort = `${node.id}.${port}`;
      inputs[terminalPort] = type;
      definition.edges.push({
        id: `$terminal-${terminalPort}`,
        source: { node: node.id, port },
        target: { node: '$output', port: terminalPort },
      });
    }
  }
  // With no processing nodes, direct typed input-to-output is still valid.
  if (!definition.nodes.length) {
    for (const [port, type] of Object.entries(definition.inputs)) {
      inputs[port] = type;
      definition.edges.push({
        id: `$terminal-${port}`,
        source: { node: '$input', port },
        target: { node: '$output', port },
      });
    }
  }
  catalog.push({ id: '$output', label: '종료 · 결과', inputs, outputs: {}, options: {} });
  definition.nodes.push({
    id: '$output',
    type: '$output',
    options: {},
    position: {
      x: Math.max(40, ...definition.nodes.map((node) => node.position?.x || 0)) + 290,
      y: Math.max(24, ...sinks.map((node) => node.position?.y || 0)),
    },
  });
  return { definition, catalog };
};

// Legacy only exposes a sequential stage list and final job artifacts. Never
// substitute today's editable workflow or pretend those are exact node receipts.
export const legacyExecution = (
  job: Job,
  preview: JobPreview | null,
  catalog: CanvasSpec[],
): JobExecution => {
  const stages = job.metadata.workflow?.stages || [];
  const specs = new Map(catalog.map((spec) => [spec.id, spec]));
  const nodes = stages.map((type, index) => ({
    id: `legacy-${index}`,
    type,
    position: { x: 310 + (index % 4) * 275, y: 70 + Math.floor(index / 4) * 160 },
    options: {},
  }));
  const edges: CanvasDefinition['edges'] = [];
  nodes.forEach((node, index) => {
    const previous = nodes[index - 1];
    const source = previous ? specs.get(previous.type)?.outputs || {} : { video: 'video' };
    for (const [port, type] of Object.entries(specs.get(node.type)?.inputs || {})) {
      const output = Object.keys(source).find((name) => source[name] === type);
      if (output)
        edges.push({
          id: `legacy-edge-${index}-${port}`,
          source: { node: previous?.id || '$input', port: output },
          target: { node: node.id, port },
        });
    }
  });
  const outputs: ExecutionArtifact[] = [];
  if (preview?.video_available && !preview.expired)
    outputs.push({
      id: 'final-video',
      label: '최종 영상',
      type: 'video',
      url: `/jobs/${job.job_id}/stream`,
      final: true,
    });
  for (const track of ['original', 'translated'] as const) {
    const result = preview?.tracks[track];
    if (result?.available)
      outputs.push({
        id: track,
        label: track === 'original' ? '작업 최종 전사 자료' : '작업 최종 번역 자료',
        type: 'transcript',
        cues: result.cues,
        partial: result.partial,
        expired: preview?.expired,
        track,
        url: `/jobs/${job.job_id}/results/${track}.srt`,
      });
  }
  return {
    version: 1,
    job_id: job.job_id,
    source: 'legacy_stages',
    definition: {
      id: job.metadata.workflow?.definition_id || job.job_id,
      name: job.metadata.workflow?.name || '저장된 처리 단계',
      revision: job.metadata.workflow?.revision || 0,
      inputs: { video: 'video' },
      nodes,
      edges,
    },
    catalog,
    runs: [],
    inputs: job.metadata.asset_id
      ? [
          {
            id: 'source',
            label: job.original_filename,
            type: 'video',
            url: `/videos/${job.metadata.asset_id}/stream`,
          },
        ]
      : [],
    outputs,
    notice: '기존 작업의 단계 목록입니다. 노드별 실행 기록·적용 설정은 제공되지 않았습니다.',
  };
};
