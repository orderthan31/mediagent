import type { CanvasDefinition } from './WorkflowCanvas';
type JobGraph = {
  snapshot: { definition: CanvasDefinition; tool_definition?: CanvasDefinition };
  agent_workflow?: { definition: CanvasDefinition } | null;
};
export const publicAgentGraph = (job: JobGraph | null): CanvasDefinition | null => {
  const value = job?.agent_workflow?.definition || job?.snapshot.definition;
  return value?.catalog_version === 2 &&
    value.nodes.every((n) =>
      [
        'transcription_agent',
        'translation_agent',
        'subtitle_video_agent',
        'audio_extraction_agent',
        'subtitle_file_agent',
        'video_conversion_agent',
      ].includes(n.type),
    )
    ? value
    : null;
};
