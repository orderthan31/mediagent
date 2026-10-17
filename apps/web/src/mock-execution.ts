// Synthetic node receipts, imported exclusively by the DEV mock transport.
import type { Job } from './api';
import type { CanvasDefinition, CanvasSpec } from './WorkflowCanvas';
import type { ReviewTask } from './form-contract';
import type { ExecutionArtifact, JobExecution, NodeRun } from './job-execution';
import { cueTracks, seedModels } from './mock-data';
import { resolvePorts } from './workflow-spec';

export const mockExecution = (
  job: Job,
  definition: CanvasDefinition,
  catalog: CanvasSpec[],
  tasks: ReviewTask[],
): JobExecution => {
  const review = tasks.find((task) => task.job_id === job.job_id);
  const activeType = job.status === 'TRANSCRIBING' ? 'transcribe' : job.metadata.failed_stage;
  const active = review
    ? definition.nodes.findIndex((node) => node.id === review.node_id)
    : definition.nodes.findIndex((node) => node.type === activeType);
  const artifact = (type: string, id: string, label: string, nodeType = ''): ExecutionArtifact => {
    if (type === 'video') return { id, label, type, url: `/jobs/${job.job_id}/stream` };
    if (type === 'audio') return { id, label, type, url: `/jobs/${job.job_id}/results/audio.wav` };
    if (type === 'transcript' || type === 'subtitle') {
      const track = nodeType === 'transcribe' ? 'original' : 'translated';
      return {
        id,
        label,
        type,
        cues: structuredClone(cueTracks[track]),
        track,
        url: `/jobs/${job.job_id}/results/${track}.srt`,
      };
    }
    return {
      id,
      label,
      type,
      data:
        type === 'timeline_map'
          ? { source_clock: 'original', intervals: [[0, 12]] }
          : { sample: true, duration_seconds: 12 },
    };
  };
  const inputs = Object.entries(definition.inputs).map(([port, type]) => {
    const item = artifact(type, `input-${port}`, job.original_filename);
    if (type === 'video' && job.metadata.asset_id)
      item.url = `/videos/${job.metadata.asset_id}/stream`;
    return item;
  });
  const produced = new Map<string, ExecutionArtifact[]>();
  const runs: NodeRun[] = definition.nodes.map((node, index) => {
    const task = tasks.find((task) => task.job_id === job.job_id && task.node_id === node.id);
    const status =
      job.status === 'COMPLETED'
        ? 'completed'
        : index === active
          ? job.status === 'FAILED'
            ? 'failed'
            : task
              ? 'review_required'
              : 'running'
          : active >= 0 && index < active
            ? 'completed'
            : 'pending';
    const spec = resolvePorts(
      catalog.find((spec) => spec.id === node.type),
      node.options,
    );
    const hasOutput =
      status === 'completed' ||
      status === 'running' ||
      (status === 'review_required' && task?.contract.phase === 'after');
    const outputs = hasOutput
      ? Object.entries(spec?.outputs || {}).map(([port, type]) => ({
          ...artifact(
            type,
            `${node.id}-${port}`,
            `${spec?.label || node.type} · ${port}`,
            node.type,
          ),
          partial: status === 'running',
        }))
      : [];
    produced.set(node.id, outputs);
    const modelVersion = seedModels().find((model) => model.id === node.model_ref?.model_id)
      ?.versions[String(node.model_ref?.revision)];
    return {
      id: `${node.id}-attempt-1`,
      node_id: node.id,
      status,
      attempt: 1,
      iteration: 0,
      generation: 1,
      settings: structuredClone(node.options),
      ...(modelVersion
        ? {
            model: {
              name: modelVersion.name,
              model: modelVersion.model,
              provider: modelVersion.provider,
              revision: modelVersion.revision,
            },
          }
        : {}),
      ...(status !== 'pending' ? { started_at: job.created_at } : {}),
      ...(status === 'completed'
        ? {
            completed_at: job.completed_at || job.created_at,
            duration_seconds: job.metadata.stage_durations_seconds?.[node.type] ?? 1,
          }
        : {}),
      ...(status === 'running' ? { progress: job.metadata.stage_progress || 0 } : {}),
      inputs: definition.edges
        .filter((edge) => edge.target.node === node.id)
        .flatMap((edge) =>
          edge.source.node === '$input'
            ? inputs.filter((item) => item.id === `input-${edge.source.port}`)
            : (produced.get(edge.source.node) || []).filter(
                (item) => item.id === `${edge.source.node}-${edge.source.port}`,
              ),
        ),
      outputs,
      ...(status === 'failed'
        ? { error: { code: 'sample_timeout', message: job.error || '샘플 실행 오류' } }
        : {}),
      events:
        status === 'pending'
          ? []
          : [
              {
                at: job.created_at,
                message: task
                  ? task.state === 'confirmed'
                    ? '검수 확정 · 아직 실행 전'
                    : '사람 검수 대기'
                  : `샘플 실행 기록 · ${status}`,
              },
            ],
    };
  });
  const sinks = definition.nodes.filter(
    (node) => !definition.edges.some((edge) => edge.source.node === node.id),
  );
  const outputs = sinks
    .flatMap((node) => produced.get(node.id) || [])
    .map((item) => ({ ...item, final: job.status === 'COMPLETED' }));
  return {
    version: 1,
    job_id: job.job_id,
    source: 'fixture',
    definition: structuredClone(definition),
    catalog: structuredClone(catalog),
    inputs,
    outputs,
    runs,
  };
};
