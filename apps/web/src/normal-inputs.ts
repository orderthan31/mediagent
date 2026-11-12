import type { CanvasDefinition } from './WorkflowCanvas';

export type InputSelector = { job_id: string; run_id: string; port: string };
export type InputChoice = InputSelector & { label: string };
export const inputChoiceKey = (choice: InputSelector) =>
  `${choice.job_id}:${choice.run_id}:${choice.port}`;
export type NormalInputValue = {
  subtitle_srt?: string;
  input_language?: string;
  accepted_inputs?: Partial<Record<'transcript' | 'audio', InputSelector>>;
};
// Upload ceiling only. The server checks the selected native input/output
// contract (including normalized JSON size) before preview or creation.
export const maxSrtFileBytes = 16 * 1024 * 1024;

export const readSrtFile = async (file: Pick<File, 'name' | 'size' | 'arrayBuffer'>) => {
  if (!file.name.toLowerCase().endsWith('.srt') || file.size < 1 || file.size > maxSrtFileBytes) {
    throw new Error(
      'UTF-8 SRT 파일을 선택하세요. 파일 선택 한도는 16MiB이며 작업별 용량은 시작 전에 확인합니다.',
    );
  }
  const raw = await file.arrayBuffer();
  if (raw.byteLength < 1 || raw.byteLength > maxSrtFileBytes) {
    throw new Error('SRT 파일을 16MiB 이내로 나눈 뒤 다시 선택하세요.');
  }
  try {
    return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
  } catch {
    throw new Error('SRT 파일은 UTF-8이어야 합니다.');
  }
};

export const normalInputReady = (
  definition: Pick<CanvasDefinition, 'inputs' | 'catalog_version'> | null,
  value: NormalInputValue,
) => {
  if (definition?.catalog_version !== 2) {
    return true;
  }
  return (
    (!definition.inputs.transcript ||
      Number(!!value.subtitle_srt) + Number(!!value.accepted_inputs?.transcript) === 1) &&
    (!definition.inputs.audio || !!value.accepted_inputs?.audio) &&
    value.input_language !== ''
  );
};

export const setWorkflowInput = <T extends Pick<CanvasDefinition, 'inputs' | 'nodes'>>(
  definition: T,
  port: 'transcript' | 'audio',
  enabled: boolean,
): T => {
  const inputs = { ...definition.inputs };
  if (enabled) {
    inputs[port] = port;
  } else {
    delete inputs[port];
  }
  return {
    ...definition,
    inputs,
    nodes: definition.nodes.map((node) =>
      port === 'audio' && node.type === 'transcription_agent'
        ? {
            ...node,
            options: { ...node.options, audio_source: enabled ? 'selected_audio' : 'video' },
          }
        : node,
    ),
  };
};

export const selectAcceptedInput = (
  value: NormalInputValue,
  port: 'transcript' | 'audio',
  choice?: InputSelector,
): NormalInputValue => {
  const next = { ...value, accepted_inputs: { ...value.accepted_inputs } };
  if (choice) {
    next.accepted_inputs[port] = {
      job_id: choice.job_id,
      run_id: choice.run_id,
      port: choice.port,
    };
  } else {
    delete next.accepted_inputs[port];
  }
  if (port === 'transcript') {
    delete next.subtitle_srt;
    delete next.input_language;
  }
  return next;
};

export const withSrtInput = (value: NormalInputValue, text?: string): NormalInputValue => ({
  ...selectAcceptedInput(value, 'transcript'),
  ...(text !== undefined ? { subtitle_srt: text } : {}),
  input_language: value.input_language ?? 'auto',
});
