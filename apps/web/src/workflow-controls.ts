import type { CanvasSpec } from './WorkflowCanvas';

// Publishing-only controls. These descriptors do not register an execution engine.
export const isControlNode = (type: string) =>
  type.startsWith('control_') || ['select', 'join'].includes(type);
const dataTypes = [
  'video',
  'audio',
  'transcript',
  'subtitle',
  'media_metadata',
  'artifact_manifest',
];
export const controlSpecs: CanvasSpec[] = [
  {
    id: 'control_if',
    label: 'IF',
    inputs: { value: 'video' },
    outputs: { true: 'video', false: 'video' },
    options: {
      data_type: dataTypes,
      operator: ['equals', 'not_equals', 'contains', 'greater_than', 'less_than', 'exists'],
      field: [''],
      compare_value: [''],
    },
    port_types_from_options: {
      inputs: { value: 'data_type' },
      outputs: { true: 'data_type', false: 'data_type' },
    },
  },
  {
    id: 'control_switch',
    label: 'Switch',
    inputs: { value: 'video' },
    outputs: { case_1: 'video', case_2: 'video', default: 'video' },
    options: { data_type: dataTypes, field: [''], cases: ['case_1\ncase_2'] },
    port_types_from_options: { inputs: { value: 'data_type' } },
  },
  {
    id: 'control_loop',
    label: 'Loop',
    inputs: { value: 'video', next: 'video' },
    outputs: { body: 'video', done: 'video' },
    options: {
      data_type: dataTypes,
      mode: ['each_item', 'repeat_count'],
      repeat_count: ['3'],
      max_iterations: ['10'],
    },
    port_types_from_options: {
      inputs: { value: 'data_type', next: 'data_type' },
      outputs: { body: 'data_type', done: 'data_type' },
    },
  },
  {
    id: 'control_fallback',
    label: '폴백',
    inputs: { value: 'video' },
    outputs: { primary: 'video', fallback: 'video' },
    options: {
      data_type: dataTypes,
      trigger: ['on_error', 'on_empty_result'],
      max_attempts: ['1'],
    },
    port_types_from_options: {
      inputs: { value: 'data_type' },
      outputs: { primary: 'data_type', fallback: 'data_type' },
    },
  },
];
export const controlFieldLabels: Record<string, string> = {
  data_type: '자료 유형',
  operator: '조건',
  field: '비교할 필드',
  compare_value: '비교값',
  cases: '분기값 · 줄마다 하나',
  mode: '반복 방식',
  repeat_count: '반복 횟수',
  max_iterations: '최대 반복 횟수',
  trigger: '폴백 조건',
  max_attempts: '최대 시도 횟수',
};
export const controlValueLabels: Record<string, string> = {
  video: '영상',
  audio: '오디오',
  transcript: '전사문',
  subtitle: '자막',
  media_metadata: '영상 정보',
  artifact_manifest: '결과 목록',
  equals: '같음',
  not_equals: '다름',
  contains: '포함',
  greater_than: '보다 큼',
  less_than: '보다 작음',
  exists: '값 있음',
  each_item: '항목별 반복',
  repeat_count: '지정 횟수',
  on_error: '오류 발생',
  on_empty_result: '빈 결과',
};
export const switchOutputs = (options: Record<string, string>) => {
  const cases = (options.cases || 'case_1\ncase_2')
    .split('\n')
    .map((value) => value.trim())
    .filter(Boolean)
    .slice(0, 20);
  return Object.fromEntries([
    ...cases.map((_, index) => [`case_${index + 1}`, options.data_type || 'video']),
    ['default', options.data_type || 'video'],
  ]);
};
