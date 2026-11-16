import type { RegisteredVersion } from './registered-models';
import type { ServingConnection } from './serving-connection';

const providerNames: Record<string, string> = {
  gemini: 'Google AI Studio',
  vertex_ai: 'Vertex AI',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  xai: 'xAI',
  openai_compatible: 'OpenAI 호환',
};
export const modelProviderLabel = (provider: string) => providerNames[provider] || provider;
export const modelAccountKey = (version: RegisteredVersion) =>
  JSON.stringify([version.provider, version.connection_id || '']);
export const modelAccountLabel = (
  version: Pick<RegisteredVersion, 'provider' | 'connection_id'>,
  connections: ServingConnection[] = [],
) => {
  const connection = connections.find((row) => row.id === version.connection_id);
  return [
    modelProviderLabel(version.provider),
    connection?.name,
    version.connection_id ? `연결 ${version.connection_id}` : '연결 정보 없음',
  ]
    .filter(Boolean)
    .join(' · ');
};
export const modelChoiceLabel = (version: RegisteredVersion) =>
  `${version.name} · ${version.model} · ${modelAccountLabel(version)}`;
