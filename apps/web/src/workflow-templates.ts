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

/** New explicit profile; never upgrades saved legacy definitions/tickets. */
export const createSubtitleReviewWorkflow = ({
  sourceLanguage,
  targetLanguage,
  additionalLanguages = [],
}: {
  sourceLanguage: string;
  targetLanguage: string;
  additionalLanguages?: string[];
}): EditableWorkflow => {
  const pattern = /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
  if (
    !(sourceLanguage === 'auto' || (sourceLanguage.length <= 64 && pattern.test(sourceLanguage))) ||
    ![targetLanguage, ...additionalLanguages].every(
      (value) => value.length <= 64 && pattern.test(value),
    ) ||
    targetLanguage === 'auto' ||
    additionalLanguages.includes('auto') ||
    additionalLanguages.length > 4 ||
    new Set([targetLanguage, ...additionalLanguages].map((value) => value.toLowerCase())).size !==
      additionalLanguages.length + 1
  ) {
    throw new Error('언어 코드를 확인하세요. 추가 언어는 중복 없이 최대 4개입니다.');
  }
  const doc = createLegacyWorkflow({ review: false });
  doc.name = '자막 검수·다국어 · 명시 프로필';
  const removed = new Set(['original_subtitles', 'translated_subtitles']);
  doc.nodes = doc.nodes.filter((node) => !removed.has(node.id));
  doc.edges = doc.edges.filter(
    (edge) => !removed.has(edge.source.node) && !removed.has(edge.target.node),
  );
  const translation = (code: string) => ({
    translation_profile: 'language_target_v1',
    target_language: code,
    batch_policy: 'bounded_100x16k_v1',
    max_model_calls: '128',
  });
  doc.nodes.find((node) => node.id === 'translate')!.options = translation(targetLanguage);
  const options: Record<string, string> = {
    original_language: sourceLanguage,
    translated_language: targetLanguage,
  };
  const link = (source: string, output: string, target: string, input: string) =>
    doc.edges.push({
      id: identity(),
      source: { node: source, port: output },
      target: { node: target, port: input },
    });
  for (const [index, language] of additionalLanguages.entries()) {
    const id = 'translate_extra_' + (index + 1);
    doc.nodes.push({
      id,
      type: 'translate',
      position: { x: 1240, y: 240 + index * 190 },
      options: translation(language),
    });
    options['additional_' + (index + 1) + '_language'] = language;
    link('transcribe', 'transcript', id, 'transcript');
    link(id, 'transcript', 'subtitle_tracks', 'additional_' + (index + 1));
  }
  doc.nodes.push(
    { id: 'subtitle_tracks', type: 'subtitle_tracks', position: { x: 1540, y: 40 }, options },
    {
      id: 'review_subtitles',
      type: 'review',
      position: { x: 1840, y: 40 },
      options: { data_type: 'subtitle_tracks', review_kind: 'subtitle_tracks_v1' },
    },
    {
      id: 'subtitle_files',
      type: 'subtitle_outputs',
      position: { x: 2140, y: 40 },
      options: { format: 'srt_smi' },
    },
  );
  doc.nodes.find((node) => node.id === 'encode')!.position.x = 2440;
  doc.nodes.find((node) => node.id === 'validate')!.position.x = 2740;
  link('transcribe', 'transcript', 'subtitle_tracks', 'original');
  link('translate', 'transcript', 'subtitle_tracks', 'translated');
  link('subtitle_tracks', 'tracks', 'review_subtitles', 'value');
  link('review_subtitles', 'value', 'subtitle_files', 'tracks');
  link('subtitle_files', 'subtitles', 'encode', 'subtitles');
  return doc;
};
