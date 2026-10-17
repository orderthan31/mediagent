export type ModelReference = { model_id: string; revision: number };
export type RegisteredVersion = ModelReference & {
  name: string;
  provider: string;
  connection_id?: string;
  connection_revision?: number;
  model: string;
  model_types?: string[];
  input_modalities?: string[];
  output_modalities?: string[];
  capabilities?: string[];
  // Historical job-role declarations are not model types or capability proof.
  uses?: string[];
  sha256: string;
};
export type RegisteredModel = {
  id: string;
  revision: number;
  current_revision: number;
  state_revision: number;
  active: boolean;
  connection: string;
  versions: Record<string, RegisteredVersion>;
};
export const modelTypeLabels: Record<string, string> = {
  text: '텍스트',
  tts: 'TTS',
  multimodal: '멀티모달',
  vision: '비전',
  speech_recognition: '음성 인식',
  decision: '디시전',
  embedding: '임베딩',
  image_generation: '이미지 생성',
  video_generation: '영상 생성',
};
export const modalityLabels: Record<string, string> = {
  text: '텍스트',
  audio: '오디오',
  image: '이미지',
  video: '영상',
  vector: '벡터',
};
export const capabilityLabels: Record<string, string> = {
  text_generation: '텍스트 생성',
  speech_recognition: '음성 인식',
  speech_synthesis: '음성 합성',
  image_understanding: '이미지 이해',
  structured_output: '구조화 출력',
  embedding: '임베딩',
  image_generation: '이미지 생성',
  video_generation: '영상 생성',
};
export const typeDefaults: Record<
  string,
  { inputs: string[]; outputs: string[]; capabilities: string[] }
> = {
  text: { inputs: ['text'], outputs: ['text'], capabilities: ['text_generation'] },
  tts: { inputs: ['text'], outputs: ['audio'], capabilities: ['speech_synthesis'] },
  multimodal: {
    inputs: ['text', 'image'],
    outputs: ['text'],
    capabilities: ['text_generation', 'image_understanding'],
  },
  vision: { inputs: ['image'], outputs: ['text'], capabilities: ['image_understanding'] },
  speech_recognition: {
    inputs: ['audio'],
    outputs: ['text'],
    capabilities: ['speech_recognition'],
  },
  decision: {
    inputs: ['text'],
    outputs: ['text'],
    capabilities: ['text_generation', 'structured_output'],
  },
  embedding: { inputs: ['text'], outputs: ['vector'], capabilities: ['embedding'] },
  image_generation: { inputs: ['text'], outputs: ['image'], capabilities: ['image_generation'] },
  video_generation: { inputs: ['text'], outputs: ['video'], capabilities: ['video_generation'] },
};
export const nodeModelRoles: Record<string, string> = {
  transcribe: 'transcription',
  translate: 'translation',
  decision: 'decision',
  tts: 'tts',
};
export const supportsModelRole = (model: RegisteredVersion, role: string) => {
  const inputs = model.input_modalities || [];
  const outputs = model.output_modalities || [];
  const features = model.capabilities || [];
  // Fail closed for old task-role-only revisions, without mutating frozen history.
  if (!model.model_types?.length) {
    return false;
  }
  switch (role) {
    case 'transcription':
      return (
        inputs.includes('audio') &&
        outputs.includes('text') &&
        features.includes('speech_recognition')
      );
    case 'translation':
      return (
        inputs.includes('text') && outputs.includes('text') && features.includes('text_generation')
      );
    case 'decision':
      return (
        inputs.includes('text') &&
        outputs.includes('text') &&
        features.includes('structured_output')
      );
    case 'tts':
      return (
        inputs.includes('text') &&
        outputs.includes('audio') &&
        features.includes('speech_synthesis')
      );
    default:
      return false;
  }
};
