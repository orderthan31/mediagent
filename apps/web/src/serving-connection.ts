import { renewalBackend } from './preview';
export const connectionsEndpoint = renewalBackend
  ? '/settings/serving-connections'
  : '/publishing/connections';
export type ServingConnection = {
  id: string;
  name: string;
  provider: string;
  endpoint: string;
  revision: number;
  current_revision?: number;
  protocol?: string;
  address_mode?: 'official' | 'legacy_preserved' | 'custom';
  active?: boolean;
  credential: 'not_set' | 'reference_set';
};
// Registration defaults only. Loading an existing revision must not apply them.
export const connectionDefaults: Record<string, { endpoint: string; protocol: string }> = {
  openai_compatible: { endpoint: '', protocol: 'openai_compatible' },
  openai: { endpoint: 'https://api.openai.com/v1', protocol: 'openai' },
  gemini: {
    endpoint: 'https://generativelanguage.googleapis.com/v1beta',
    protocol: 'gemini',
  },
  anthropic: { endpoint: 'https://api.anthropic.com', protocol: 'anthropic' },
  xai: { endpoint: 'https://api.x.ai/v1', protocol: 'openai' },
};
export const isFrontierProvider = (provider: string) =>
  ['openai', 'gemini', 'anthropic', 'xai'].includes(provider);
export const seedConnections = (): ServingConnection[] => [
  {
    id: '00000000000000000000000000000385',
    name: 'OpenAI',
    provider: 'openai',
    endpoint: '',
    revision: 1,
    credential: 'not_set',
  },
  {
    id: '00000000000000000000000000000386',
    name: 'Gemini',
    provider: 'gemini',
    endpoint: '',
    revision: 1,
    credential: 'not_set',
  },
];
