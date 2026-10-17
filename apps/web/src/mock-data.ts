import type { Job } from './api';
import { seedConnections } from './serving-connection';
import type { VideoAsset, VideoUpload, SubtitleInput } from './video-api';
import type { RegisteredModel } from './registered-models';
import catalog from './mock-node-catalog.json';

// Synthetic publishing fixtures, never an export of a user's DB, media or keys.
export const mockCatalog = catalog;
export const mockId = (n: number) => n.toString(16).padStart(32, '0');
export type MockDefinition = {
  id: string;
  name: string;
  revision: number;
  catalog_version: number;
  inputs: Record<string, string>;
  nodes: {
    id: string;
    type: string;
    position: { x: number; y: number };
    options: Record<string, string>;
    model_ref?: { model_id: string; revision: number };
  }[];
  edges: {
    id: string;
    source: { node: string; port: string };
    target: { node: string; port: string };
  }[];
};
export const providers = {
  gemini: 'Gemini',
  openai: 'OpenAI',
  xai: 'xAI (Grok)',
  openrouter: 'OpenRouter',
  anthropic: 'Anthropic',
};
export const sttModels = {
  gemini: ['sample-audio-model'],
  openai: ['sample-transcription-model'],
  xai: ['sample-audio-model'],
  openrouter: ['sample-audio-model'],
};
export const cueTracks = {
  original: [
    { start: 0, end: 3, text: 'Today we are looking at a simpler way to work with media.' },
    { start: 3, end: 6, text: 'Choose your source, then connect the steps you need.' },
    { start: 6, end: 9, text: 'Review the subtitles before moving to the next step.' },
    { start: 9, end: 12, text: 'This is a sample clip for the publishing preview.' },
  ],
  translated: [
    { start: 0, end: 3, text: '미디어 작업을 조금 더 간단하게 시작해 볼게요.' },
    { start: 3, end: 6, text: '원본을 고르고 필요한 처리 과정을 연결해요.' },
    { start: 6, end: 9, text: '다음 단계로 넘어가기 전에 자막을 확인해요.' },
    { start: 9, end: 12, text: '화면 확인용으로 만든 샘플 영상이에요.' },
  ],
};
const at = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const port = (node: string, name: string) => ({ node, port: name });
const edge = (i: number, from: string, output: string, to: string, input: string) => ({
  id: `edge-${i}`,
  source: port(from, output),
  target: port(to, input),
});
const node = (id: string, type: string, index: number, options: Record<string, string> = {}) => ({
  id,
  type,
  position: { x: 330 + (index % 3) * 290, y: 100 + Math.floor(index / 3) * 220 },
  options,
  ...(['transcribe', 'translate', 'decision'].includes(type)
    ? {
        model_ref: {
          model_id: mockId(type === 'transcribe' ? 301 : type === 'translate' ? 302 : 303),
          revision: 1,
        },
      }
    : {}),
});
export const seedDefinitions = (): MockDefinition[] => [
  {
    id: mockId(201),
    name: '영상 전사 · 번역 자막',
    revision: 3,
    catalog_version: 1,
    inputs: { video: 'video' },
    nodes: [
      node('audio', 'extract_audio', 0),
      node('prepare', 'preprocess_audio', 1, { vad_mode: 'off', audio_filter: 'conservative' }),
      node('stt', 'transcribe', 2, { source_language: 'auto', review_mode: 'none' }),
      node('translation', 'translate', 3, { target_language: 'ko', review_mode: 'after' }),
      node('subtitle', 'generate_subtitle', 4),
      node('render', 'encode', 5, {
        subtitle_mode: 'soft',
        video_codec: 'h264',
        resolution: 'original',
        quality_profile: 'balanced',
      }),
    ],
    edges: [
      edge(1, '$input', 'video', 'audio', 'video'),
      edge(2, 'audio', 'audio', 'prepare', 'audio'),
      edge(3, 'prepare', 'audio', 'stt', 'audio'),
      edge(4, 'prepare', 'timeline', 'stt', 'timeline'),
      edge(5, 'stt', 'transcript', 'translation', 'transcript'),
      edge(6, 'translation', 'transcript', 'subtitle', 'transcript'),
      edge(7, 'subtitle', 'subtitles', 'render', 'subtitles'),
      edge(8, '$input', 'video', 'render', 'video'),
    ],
  },
  {
    id: mockId(202),
    name: '오디오 추출 · 음성 정리',
    revision: 1,
    catalog_version: 1,
    inputs: { video: 'video' },
    nodes: [
      node('audio', 'extract_audio', 0),
      node('prepare', 'preprocess_audio', 1, { audio_filter: 'conservative', vad_mode: 'off' }),
    ],
    edges: [
      edge(1, '$input', 'video', 'audio', 'video'),
      edge(2, 'audio', 'audio', 'prepare', 'audio'),
    ],
  },
  {
    id: mockId(204),
    name: '얼굴 합성 · 결과 확인',
    revision: 1,
    catalog_version: 1,
    inputs: { video: 'video' },
    nodes: [
      node('swap', 'faceswap', 0, { quality: 'balanced', mask_blur: '0.3', review_mode: 'both' }),
    ],
    edges: [edge(1, '$input', 'video', 'swap', 'video')],
  },
  {
    id: mockId(203),
    name: '영상 분석 · AI 판단 · 사람 검수',
    revision: 2,
    catalog_version: 1,
    inputs: { video: 'video' },
    nodes: [
      node('analyze', 'analyze', 0),
      node('decision', 'decision', 1, { data_type: 'media_metadata' }),
      node('review', 'review', 2, { data_type: 'media_metadata' }),
    ],
    edges: [
      edge(1, '$input', 'video', 'analyze', 'video'),
      edge(2, 'analyze', 'metadata', 'decision', 'value'),
      edge(3, 'decision', 'a', 'review', 'value'),
    ],
  },
];
export const seedModels = (): RegisteredModel[] =>
  [
    [301, '음성 전사 · 샘플', 'openai', 'sample-transcription-model', ['transcription']],
    [302, '번역 · 샘플', 'gemini', 'sample-text-model', ['translation']],
    [303, '구조화 판단 · 샘플', 'openai', 'sample-decision-model', ['decision', 'translation']],
  ].map(([n, name, provider, model, uses]) => ({
    id: mockId(Number(n)),
    revision: 1,
    current_revision: 1,
    state_revision: 1,
    active: true,
    connection: '목업 · 실제 연결 미확인',
    versions: {
      '1': {
        model_id: mockId(Number(n)),
        revision: 1,
        name: String(name),
        provider: String(provider),
        connection_id: seedConnections().find((connection) => connection.provider === provider)?.id,
        model: String(model),
        uses: uses as string[],
        sha256: '0'.repeat(64),
      },
    },
  }));
export const seedVideos = (): VideoAsset[] =>
  [
    '제품 소개_인터뷰.mp4',
    '봄 산책_브이로그.mp4',
    '팀 회의_하이라이트.mp4',
    '쇼츠_오프닝.mp4',
    '제품 소개_번역본.mp4',
  ].map((name, i) => ({
    asset_id: mockId(i + 1),
    original_filename: name,
    size_bytes: (28 + i * 13) * 1024 ** 2,
    created_at: at(30 + i * 85),
    media: { duration: 12, width: 640, height: 360, has_audio: true, frame_rate: '12/1' },
    provenance:
      i === 4
        ? { kind: 'result', job_id: mockId(101), parent_asset_id: mockId(1) }
        : { kind: 'upload' },
  }));
export const seedJobs = (): Job[] =>
  [
    'COMPLETED',
    'TRANSCRIBING',
    'AWAITING_REVIEW',
    'QUEUED',
    'QUEUED',
    'FAILED',
    'READY',
    'AWAITING_REVIEW',
    'AWAITING_REVIEW',
  ].map((status, i) => ({
    job_id: mockId(101 + i),
    ticket_number: `T-${String(1001 + i).padStart(6, '0')}`,
    status,
    original_filename: [
      '제품 소개_인터뷰.mp4',
      '봄 산책_브이로그.mp4',
      '팀 회의_하이라이트.mp4',
      '쇼츠_오프닝.mp4',
      '제품 소개_인터뷰.mp4',
      '팀 회의_하이라이트.mp4',
      '봄 산책_브이로그.mp4',
      '인물 인터뷰_합성.mp4',
      '제품 소개_최종 확인.mp4',
    ][i],
    expected_size: (28 + i * 7) * 1024 ** 2,
    uploaded_bytes: (28 + i * 7) * 1024 ** 2,
    target_language: 'ko',
    quality_profile: 'balanced',
    source_language: 'en',
    created_at: at(15 + i * 17),
    completed_at: status === 'COMPLETED' ? at(5) : null,
    video_description: '화면 확인용 샘플',
    video_codec: 'h264',
    subtitle_mode: 'soft',
    resolution: 'original',
    review_subtitles: true,
    ...(status === 'AWAITING_REVIEW'
      ? {
          status_message:
            i === 2 ? '자막 확인 필요' : i === 7 ? '대상 선택 필요' : '결과 확인 필요',
        }
      : {}),
    error: status === 'FAILED' ? '샘플 오류 · 번역 응답 대기시간 초과' : null,
    metadata: {
      asset_id: mockId((i % 4) + 1),
      duration: 12,
      workflow: {
        definition_id: mockId(i === 7 ? 204 : 201),
        name: i === 7 ? '얼굴 합성 · 결과 확인' : '영상 전사 · 번역 자막',
        revision: i === 7 ? 1 : 3,
        template: 'full',
        stages: [
          'analyze',
          'extract_audio',
          'preprocess_audio',
          'transcribe',
          'translate',
          'generate_subtitle',
          'encode',
          'validate_video',
        ],
      },
      ...(status === 'TRANSCRIBING'
        ? {
            stage_progress: 0.58,
            stage_started_at: at(1),
            transcription_progress: {
              total: 12,
              completed: 7,
              in_flight: 2,
              retrying: 0,
              failed: 0,
              draining: false,
            },
          }
        : {}),
      ...(status === 'FAILED' ? { failed_stage: 'translate' } : {}),
      stage_durations_seconds: {
        analyze: 1,
        extract_audio: 3,
        preprocess_audio: 2,
        transcribe: 8,
        ...(status === 'COMPLETED'
          ? { translate: 6, generate_subtitle: 1, encode: 5, validate_video: 1 }
          : {}),
      },
      result_files:
        status === 'COMPLETED' ? ['final.mp4', 'original.srt', 'translated.srt', 'audio.wav'] : [],
      subtitle_revision: 1,
    },
  }));
export const seedUploads = (): VideoUpload[] => [
  {
    upload_id: mockId(401),
    filename: '다음 인터뷰_원본.mp4',
    expected_size: 86 * 1024 ** 2,
    uploaded_bytes: 32 * 1024 ** 2,
    status: 'UPLOADING',
    created_at: at(3),
  },
];
export const seedSubtitleInputs = (): Record<string, SubtitleInput[]> =>
  Object.fromEntries(
    seedVideos().map((v) => [
      v.asset_id,
      [
        {
          artifact_id: mockId(501 + Number.parseInt(v.asset_id, 16)),
          filename: v.original_filename.replace('.mp4', '.ko.srt'),
          language: 'ko',
          cue_count: 4,
          created_at: at(12),
          provenance: { kind: 'external' },
        },
      ],
    ]),
  );
export const seedLlm = () => ({
  revision: 1,
  has_api_key: false,
  key_source: 'none',
  transcription_model: 'sample-transcription-model',
  translation_model: 'sample-text-model',
  transcription_fallback_model: '',
  translation_fallback_model: '',
  transcription_provider: 'openai',
  transcription_fallback_provider: 'openai',
  translation_provider: 'gemini',
  translation_fallback_provider: 'gemini',
  fallback_on_error: false,
  fallback_on_block: false,
  credentials: Object.fromEntries(
    Object.keys(providers).map((p) => [p, { has_api_key: false, key_source: 'none' }]),
  ),
});
export const seedServing = () => ({
  revision: 1,
  workers: Object.fromEntries(
    ['transcription', 'translation'].map((role) => [
      role,
      {
        provider: role === 'transcription' ? 'openai' : 'gemini',
        model: role === 'transcription' ? 'sample-transcription-model' : 'sample-text-model',
        fallback_provider: 'openai',
        fallback_model: '',
        credential_provider: role === 'transcription' ? 'openai' : 'gemini',
        fallback_credential_provider: 'openai',
        credential: { has_api_key: false, key_source: 'none' },
        fallback_credential: { has_api_key: false, key_source: 'none' },
      },
    ]),
  ),
  fallback_on_error: false,
  fallback_on_block: false,
  providers,
  stt_models: sttModels,
  runtime: { notice: '목업 · 실제 에이전트/API 미연결' },
  fixed_workers: [{ id: 'media', provider: 'local', reason: '로컬 처리 자원 · 샘플' }],
});
