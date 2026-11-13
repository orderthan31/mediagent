import type { CanvasDefinition } from './WorkflowCanvas';

export type EditableWorkflow = CanvasDefinition & { catalog_version: number };
const identity = () => crypto.randomUUID().replaceAll('-', '');

/** Public workflow: goal agents only; tool plans belong to their implementations. */
export const createAgentWorkflow = (): EditableWorkflow => {
  const nodes: CanvasDefinition['nodes'] = [
    {
      id: 'transcription',
      type: 'transcription_agent',
      position: { x: 0, y: 80 },
      options: { source_language: 'auto' },
    },
    {
      id: 'translation',
      type: 'translation_agent',
      position: { x: 290, y: 80 },
      options: { target_language: 'ko' },
    },
    {
      id: 'subtitle_video',
      type: 'subtitle_video_agent',
      position: { x: 580, y: 80 },
      options: {},
    },
  ];
  return {
    id: identity(),
    catalog_version: 2,
    revision: 0,
    name: '영상 전사·한국어 자막 번인',
    inputs: {},
    nodes,
    edges: [0, 1].map((i) => ({
      id: identity(),
      source: { node: nodes[i].id, port: 'media' },
      target: { node: nodes[i + 1].id, port: 'media' },
    })),
  };
};

/** Real business goals with the existing human track-review contract. */
export const createReviewedAgentWorkflow = (): EditableWorkflow => {
  const doc = createAgentWorkflow();
  doc.name = '자막 검수·영상 제작';
  const render = doc.nodes.find((node) => node.id === 'subtitle_video')!;
  render.options = { subtitle_source: 'selected_subtitles' };
  doc.nodes.push(
    {
      id: 'tracks',
      type: 'subtitle_tracks',
      position: { x: 580, y: 80 },
      options: { original_language: 'auto', translated_language: 'ko' },
    },
    {
      id: 'review',
      type: 'review',
      position: { x: 870, y: 80 },
      options: { data_type: 'subtitle_tracks', review_kind: 'subtitle_tracks_v1' },
    },
    {
      id: 'files',
      type: 'subtitle_outputs',
      position: { x: 1160, y: 80 },
      options: { format: 'srt_smi' },
    },
  );
  render.position = { x: 1450, y: 80 };
  const link = (source: string, port: string, target: string, input: string) => ({
    id: identity(),
    source: { node: source, port },
    target: { node: target, port: input },
  });
  doc.edges = [
    link('transcription', 'media', 'translation', 'media'),
    link('transcription', 'transcript', 'tracks', 'original'),
    link('translation', 'transcript', 'tracks', 'translated'),
    link('tracks', 'tracks', 'review', 'value'),
    link('review', 'value', 'files', 'tracks'),
    link('files', 'subtitles', 'subtitle_video', 'subtitles'),
  ];
  return doc;
};

/** Timed subtitle input with optional translation; no video or implicit ASR. */
export const createSubtitleWorkflow = (translate = false): EditableWorkflow => {
  const nodes: CanvasDefinition['nodes'] = [
    ...(translate
      ? [
          {
            id: 'translation',
            type: 'translation_agent',
            position: { x: 280, y: 80 },
            options: { target_language: 'ko' },
          },
        ]
      : []),
    {
      id: 'subtitle_files',
      type: 'subtitle_file_agent',
      position: { x: translate ? 580 : 280, y: 80 },
      options: { format: 'srt_smi' },
    },
  ];
  const first = nodes[0].id;
  return {
    id: identity(),
    catalog_version: 2,
    revision: 0,
    name: translate ? '자막 번역' : '자막 파일 변환',
    input_profile: 'subtitle_file_v1',
    inputs: { transcript: 'transcript' },
    nodes,
    edges: [
      {
        id: identity(),
        source: { node: '$input', port: 'transcript' },
        target: { node: first, port: 'transcript' },
      },
      ...(translate
        ? [
            {
              id: identity(),
              source: { node: 'translation', port: 'transcript' },
              target: { node: 'subtitle_files', port: 'transcript' },
            },
          ]
        : []),
    ],
  };
};

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
  videoTracks = false,
  longInput = false,
}: {
  sourceLanguage: string;
  targetLanguage: string;
  additionalLanguages?: string[];
  videoTracks?: boolean;
  longInput?: boolean;
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
  if (longInput) {
    for (const stage of doc.nodes) {
      if (stage.type === 'extract_audio') {
        stage.options.media_budget = 'audio_long_v5';
      }
      if (stage.type === 'preprocess_audio') {
        Object.assign(stage.options, {
          media_budget: 'audio_long_v5',
          processing_profile: 'regions_long_v5',
          vad_mode: 'off',
        });
      }
      if (stage.type === 'transcribe') {
        Object.assign(stage.options, {
          media_budget: 'audio_long_v5',
          clock_policy: 'packed_projection_v5',
        });
      }
      if (stage.type === 'translate') {
        stage.options.media_budget = 'audio_long_v5';
      }
    }
  }
  if (videoTracks) {
    doc.nodes = doc.nodes.filter((stage) => !['encode', 'validate'].includes(stage.id));
    doc.edges = doc.edges.filter(
      (edge) =>
        !['encode', 'validate'].includes(edge.source.node) &&
        !['encode', 'validate'].includes(edge.target.node),
    );
    for (const [index, track] of [
      'original',
      'translated',
      ...additionalLanguages.map((code) => 'translated.' + code),
    ].entries()) {
      const pick = 'video_track_' + index,
        encode = 'video_encode_' + index,
        validate = 'video_validate_' + index;
      const y = 40 + index * 240;
      doc.nodes.push(
        { id: pick, type: 'subtitle_track', position: { x: 2440, y }, options: { track } },
        {
          id: encode,
          type: 'encode',
          position: { x: 2740, y },
          options: {
            subtitle_mode: 'burn',
            video_codec: 'h264',
            resolution: 'original',
            quality_profile: 'balanced',
          },
        },
        { id: validate, type: 'validate_video', position: { x: 3040, y }, options: {} },
      );
      link('subtitle_files', 'manifest', pick, 'manifest');
      link(pick, 'subtitles', encode, 'subtitles');
      link('$input', 'video', encode, 'video');
      link(encode, 'video', validate, 'video');
    }
  }
  return doc;
};

/** Explicit edit only: bypass human gates, retain all agents, pins and outputs. */
export const withoutHumanReview = (document: EditableWorkflow): EditableWorkflow => {
  let nodes = document.nodes.map((node) => ({ ...node, options: { ...node.options } }));
  let edges = document.edges.map((edge) => ({
    ...edge,
    source: { ...edge.source },
    target: { ...edge.target },
  }));
  for (const review of nodes.filter((node) => node.type === 'review')) {
    const incoming = edges.filter((edge) => edge.target.node === review.id);
    if (incoming.length !== 1 || incoming[0].target.port !== 'value') {
      throw new Error('검수 입력 연결을 먼저 확인하세요.');
    }
    edges = edges
      .filter((edge) => edge.target.node !== review.id)
      .map((edge) =>
        edge.source.node === review.id ? { ...edge, source: { ...incoming[0].source } } : edge,
      );
  }
  nodes = nodes
    .filter((node) => node.type !== 'review')
    .map((node) =>
      ['subtitle_outputs', 'subtitle_track'].includes(node.type)
        ? { ...node, options: { ...node.options, review_policy: 'off' } }
        : node,
    );
  return { ...document, nodes, edges };
};
