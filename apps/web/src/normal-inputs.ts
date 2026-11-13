import type { CanvasDefinition } from './WorkflowCanvas';

export type InputSelector = { job_id: string; run_id: string; port: string };
export type InputChoice = InputSelector & { label: string };
export const inputChoiceKey = (choice: InputSelector) =>
  `${choice.job_id}:${choice.run_id}:${choice.port}`;
export type FaceInput = {
  photo_asset_id: string;
  engine_revision: number | null;
  engine_sha256: string | null;
  settings_revision: 1;
  reference_frame: number;
};
export type NormalInputValue = {
  face_input?: FaceInput;
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
  definition: Pick<CanvasDefinition, 'inputs' | 'catalog_version' | 'input_profile'> | null,
  value: NormalInputValue,
  source?: { media_kind?: string },
) => {
  if (definition?.catalog_version !== 2) {
    return true;
  }
  if (definition.input_profile === 'subtitle_file_v1' && source?.media_kind === 'subtitle') {
    return !value.subtitle_srt && !value.accepted_inputs?.transcript && value.input_language !== '';
  }
  if (definition.input_profile === 'face_workflow_v1') {
    const selected = value.face_input;
    return (
      !!selected &&
      /^[a-f0-9]{32}$/.test(selected.photo_asset_id) &&
      Number.isInteger(selected.engine_revision) &&
      Number(selected.engine_revision) > 0 &&
      /^[a-f0-9]{64}$/.test(selected.engine_sha256 || '') &&
      selected.settings_revision === 1 &&
      Number.isInteger(selected.reference_frame) &&
      selected.reference_frame >= 1 &&
      selected.reference_frame <= 3600
    );
  }
  return (
    (!definition.inputs.transcript ||
      Number(!!value.subtitle_srt) + Number(!!value.accepted_inputs?.transcript) === 1) &&
    (definition.input_profile === 'audio_file_v1' ||
      !definition.inputs.audio ||
      !!value.accepted_inputs?.audio) &&
    value.input_language !== ''
  );
};

export const setWorkflowInput = <
  T extends Pick<CanvasDefinition, 'inputs' | 'nodes' | 'input_profile'>,
>(
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
    ...(port === 'audio' && definition.input_profile ? { input_profile: undefined } : {}),
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

/** The source choice and public input declaration are one edit. */
export const setAudioSource = <
  T extends Pick<CanvasDefinition, 'inputs' | 'nodes' | 'input_profile'>,
>(
  definition: T,
  nodeId: string,
  value: string,
): T => {
  const { input_profile: _profile, ...base } = definition;
  const inputs = { ...definition.inputs };
  if (value === 'video') {
    delete inputs.audio;
  } else {
    inputs.audio = 'audio';
  }
  return {
    ...base,
    ...(value === 'audio_file_v1' ? { input_profile: 'audio_file_v1' } : {}),
    inputs,
    nodes: definition.nodes.map((n) =>
      n.id === nodeId ? { ...n, options: { ...n.options, audio_source: value } } : n,
    ),
  } as T;
};
