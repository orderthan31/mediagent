import type { CanvasSpec } from './WorkflowCanvas';
import {
  formDefaults,
  type FieldSchema,
  type FormData,
  type NodeFormContract,
  type ReviewContract,
  type ReviewTask,
} from './form-contract';

const pick = (title: string, values: [string, string][], value: string): FieldSchema => ({
  type: 'string',
  title,
  default: value,
  choices: values.map(([value, label]) => ({ value, label })),
});
const text = (title: string, value = ''): FieldSchema => ({
  type: 'string',
  title,
  default: value,
  maxLength: 2000,
});
const object = (
  title: string,
  properties: Record<string, FieldSchema>,
  required: string[] = [],
): FieldSchema => ({ type: 'object', title, properties, required });
export const subtitleReview: ReviewContract = {
  version: 1,
  title: '자막 확인',
  phase: 'after',
  material_ports: ['input.video', 'output.transcript'],
  fields: object(
    '자막',
    {
      cues: {
        type: 'array',
        title: '자막 구간',
        minItems: 4,
        maxItems: 4,
        items: {
          ...object(
            '구간',
            {
              start: { type: 'number', title: '시작', format: 'seconds', minimum: 0, maximum: 12 },
              end: { type: 'number', title: '끝', format: 'seconds', minimum: 0, maximum: 12 },
              text: {
                type: 'string',
                title: '내용',
                format: 'multiline',
                minLength: 1,
                maxLength: 1000,
              },
            },
            ['start', 'end', 'text'],
          ),
          order: { from: 'start', to: 'end', message: '끝 시간은 시작 시간보다 뒤여야 합니다.' },
        },
      },
    },
    ['cues'],
  ),
};
export const mappingReview: ReviewContract = {
  version: 1,
  title: '대상 선택',
  phase: 'before',
  material_ports: ['input.video', 'input.images'],
  fields: object(
    '대상 지정',
    {
      pairs: {
        type: 'array',
        title: '바꿀 대상',
        minItems: 1,
        maxItems: 2,
        items: object(
          '대응 항목',
          {
            target: {
              type: 'string',
              title: '영상 속 대상',
              default: 'face-a',
              choices: [
                { value: 'face-a', label: '대상 1', image: '/mock/face-avatar-1.svg' },
                { value: 'face-b', label: '대상 2', image: '/mock/face-avatar-2.svg' },
              ],
            },
            replacement: {
              type: 'string',
              title: '바꿀 이미지',
              default: 'image-a',
              choices: [
                { value: 'image-a', label: '이미지 1', image: '/mock/face-avatar-3.svg' },
                { value: 'image-b', label: '이미지 2', image: '/mock/face-avatar-4.svg' },
              ],
            },
          },
          ['target', 'replacement'],
        ),
      },
    },
    ['pairs'],
  ),
};
export const resultReview: ReviewContract = {
  version: 1,
  title: '결과 확인',
  phase: 'after',
  material_ports: ['input.video', 'output.video'],
  fields: object(
    '확인할 내용',
    {
      accepted: { type: 'boolean', title: '결과를 확인했습니다', default: false, const: true },
      note: { type: 'string', title: '메모', format: 'multiline', maxLength: 2000, default: '' },
    },
    ['accepted'],
  ),
};
const language = [
  ['auto', '자동 감지'],
  ['ko', '한국어'],
  ['en', '영어'],
  ['ja', '일본어'],
] as [string, string][];
const annotations: Record<string, NodeFormContract> = {
  preprocess_audio: {
    settings_schema: object('음성 전처리', {
      audio_filter: pick(
        '음성 정리',
        [
          ['off', '사용 안 함'],
          ['conservative', '가볍게'],
          ['strong', '강하게'],
          ['silence3', '무음 정리'],
        ],
        'conservative',
      ),
      vad_mode: pick(
        '음성 구간 감지',
        [
          ['off', '사용 안 함'],
          ['nvidia', 'NVIDIA'],
        ],
        'off',
      ),
    }),
  },
  transcribe: {
    model_role: 'transcription',
    settings_schema: object('전사', {
      source_language: pick('음성 언어', language, 'auto'),
      segment_seconds: {
        type: 'integer',
        title: '구간 길이 · 초',
        default: 300,
        minimum: 30,
        maximum: 600,
      },
    }),
    review_contracts: [subtitleReview],
  },
  translate: {
    model_role: 'translation',
    settings_schema: object('번역', {
      target_language: pick(
        '번역할 언어',
        language.filter(([id]) => id !== 'auto'),
        'ko',
      ),
      instructions: { ...text('번역 지침'), format: 'multiline' },
    }),
    review_contracts: [subtitleReview],
  },
  generate_subtitle: {
    settings_schema: object('자막 생성', {
      output_format: pick(
        '파일 형식',
        [
          ['srt', 'SRT'],
          ['vtt', 'VTT'],
        ],
        'srt',
      ),
      max_line_length: {
        type: 'integer',
        title: '한 줄 최대 글자 수',
        default: 42,
        minimum: 10,
        maximum: 100,
      },
    }),
    review_contracts: [subtitleReview],
  },
  encode: {
    settings_schema: object('영상 출력', {
      subtitle_mode: pick(
        '자막',
        [
          ['soft', '별도 트랙'],
          ['burn', '영상에 입히기'],
          ['none', '넣지 않음'],
        ],
        'soft',
      ),
      video_codec: pick(
        '코덱',
        [
          ['h264', 'H.264'],
          ['hevc', 'HEVC'],
        ],
        'h264',
      ),
      resolution: pick(
        '해상도',
        [
          ['original', '원본 유지'],
          ['1080p', '1080p'],
          ['720p', '720p'],
        ],
        'original',
      ),
      quality_profile: pick(
        '화질',
        [
          ['balanced', '균형'],
          ['high', '고화질'],
          ['compact', '작은 용량'],
        ],
        'balanced',
      ),
    }),
    review_contracts: [resultReview],
  },
  faceswap: {
    settings_schema: object('얼굴 합성', {
      quality: pick(
        '합성 품질',
        [
          ['balanced', '균형'],
          ['high', '고품질'],
        ],
        'balanced',
      ),
      mask_blur: { type: 'number', title: '경계 부드러움', default: 0.3, minimum: 0, maximum: 1 },
    }),
    review_contracts: [mappingReview, resultReview],
  },
};
export const publishingCatalog = (nodes: CanvasSpec[]): CanvasSpec[] =>
  nodes.map((node) => {
    const contract = { ...node, ...annotations[node.id] };
    return {
      ...contract,
      review_contracts: contract.review_contracts?.map((review) => ({
        ...review,
        material_ports: [
          ...Object.keys(node.inputs).map((port) => `input.${port}`),
          ...(review.phase === 'after'
            ? Object.keys(node.outputs).map((port) => `output.${port}`)
            : []),
        ],
      })),
    };
  });
export const settingsValues = (schema: FieldSchema, options: Record<string, string>): FormData => {
  const defaults = formDefaults(schema) as FormData;
  return Object.fromEntries(
    Object.entries(schema.properties || {}).map(([key, field]) => {
      const raw = options[key];
      const value =
        raw === undefined
          ? defaults[key]
          : field.type === 'boolean'
            ? raw === 'true'
            : field.type === 'number' || field.type === 'integer'
              ? Number(raw)
              : raw;
      return [key, value];
    }),
  );
};
export const seedReviewTasks = (): Record<string, ReviewTask> => {
  const id = (n: number) => n.toString(16).padStart(32, '0');
  const make = (
    name: string,
    job: number,
    node: string,
    contract: ReviewContract,
    data: FormData,
  ): ReviewTask => ({
    id: name,
    job_id: id(job),
    node_id: node,
    contract: structuredClone(contract),
    data,
    revision: 1,
    state: 'waiting',
    reason: '',
    materials: [
      {
        id: 'source',
        kind: 'video',
        label: contract.phase === 'before' ? '원본 영상' : '확인할 영상',
        url: '/mock/sample.mp4',
      },
    ],
  });
  const cues = [
    '미디어 작업을 조금 더 간단하게 시작해 볼게요.',
    '원본을 고르고 필요한 처리 과정을 연결해요.',
    '다음 단계로 넘어가기 전에 자막을 확인해요.',
    '화면 확인용으로 만든 샘플 영상이에요.',
  ].map((text, i) => ({ start: i * 3, end: (i + 1) * 3, text }));
  return Object.fromEntries(
    [
      make('review-text', 103, 'translation', subtitleReview, { cues }),
      make(
        'review-mapping',
        108,
        'mapping',
        mappingReview,
        formDefaults(mappingReview.fields) as FormData,
      ),
      make(
        'review-result',
        109,
        'render',
        resultReview,
        formDefaults(resultReview.fields) as FormData,
      ),
    ].map((task) => [task.id, task]),
  );
};
