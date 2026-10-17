export type ModelReference = { model_id: string; revision: number };
export type RegisteredVersion = ModelReference & {
  name: string;
  provider: string;
  connection_id?: string;
  model: string;
  uses: string[];
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
export const nodeModelRoles: Record<string, string> = {
  transcribe: 'transcription',
  translate: 'translation',
  decision: 'decision',
};
export const modelUseLabels: Record<string, string> = {
  transcription: '전사',
  translation: '번역',
  decision: '판단',
};
