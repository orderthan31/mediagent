import type { CanvasDefinition } from './WorkflowCanvas';

export type EditableWorkflow = CanvasDefinition & { catalog_version: number };
const identity = () => crypto.randomUUID().replaceAll('-', '');

/** An editable draft, not a saved workflow, ticket, cost consent, or execution. */
export const createLegacyWorkflow = ({
  review = true,
}: { review?: boolean } = {}): EditableWorkflow => {
  const nodes: CanvasDefinition['nodes'] = [
    { id: 'analyze', type: 'analyze', position: { x: 340, y: 320 }, options: {} },
    { id: 'extract', type: 'extract_audio', position: { x: 340, y: 40 }, options: {} },
    {
      id: 'preprocess',
      type: 'preprocess_audio',
      position: { x: 640, y: 40 },
      options: { vad_mode: 'off', audio_filter: 'off' },
    },
    {
      id: 'transcribe',
      type: 'transcribe',
      position: { x: 940, y: 40 },
      options: { batch_policy: 'bounded_60s_v1', max_model_calls: '128' },
    },
    {
      id: 'translate',
      type: 'translate',
      position: { x: 1240, y: 40 },
      options: { batch_policy: 'bounded_100x16k_v1', max_model_calls: '128' },
    },
    {
      id: 'original_subtitles',
      type: 'generate_subtitle',
      position: { x: 1240, y: 320 },
      options: { format: 'srt_smi' },
    },
    {
      id: 'translated_subtitles',
      type: 'generate_subtitle',
      position: { x: 1540, y: 40 },
      options: { format: 'srt_smi' },
    },
    {
      id: 'review_subtitles',
      type: 'review',
      position: { x: 1840, y: 40 },
      options: { data_type: 'subtitle' },
    },
    {
      id: 'encode',
      type: 'encode',
      position: { x: 2140, y: 40 },
      options: {
        subtitle_mode: 'burn',
        video_codec: 'h264',
        resolution: 'original',
        quality_profile: 'balanced',
      },
    },
    { id: 'validate', type: 'validate_video', position: { x: 2440, y: 40 }, options: {} },
  ];
  const edges: CanvasDefinition['edges'] = [];
  const link = (source: string, output: string, target: string, input: string) => {
    edges.push({
      id: identity(),
      source: { node: source, port: output },
      target: { node: target, port: input },
    });
  };
  link('$input', 'video', 'analyze', 'video');
  link('$input', 'video', 'extract', 'video');
  link('extract', 'audio', 'preprocess', 'audio');
  link('preprocess', 'audio', 'transcribe', 'audio');
  link('preprocess', 'timeline', 'transcribe', 'timeline');
  link('transcribe', 'transcript', 'original_subtitles', 'transcript');
  link('transcribe', 'transcript', 'translate', 'transcript');
  link('translate', 'transcript', 'translated_subtitles', 'transcript');
  if (review) {
    link('translated_subtitles', 'subtitles', 'review_subtitles', 'value');
    link('review_subtitles', 'value', 'encode', 'subtitles');
  } else {
    nodes.splice(
      nodes.findIndex((node) => node.id === 'review_subtitles'),
      1,
    );
    link('translated_subtitles', 'subtitles', 'encode', 'subtitles');
  }
  link('$input', 'video', 'encode', 'video');
  link('encode', 'video', 'validate', 'video');
  return {
    id: identity(),
    catalog_version: 1,
    revision: 0,
    name: '기존 전체 작업 · 얼굴합성 제외',
    inputs: { video: 'video' },
    nodes,
    edges,
  };
};
