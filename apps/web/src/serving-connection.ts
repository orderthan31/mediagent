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
  active?: boolean;
  credential: 'not_set' | 'reference_set';
};
export const seedConnections = (): ServingConnection[] => [
  {
    id: '00000000000000000000000000000385',
    name: '전사용 OpenAI',
    provider: 'openai',
    endpoint: '',
    revision: 1,
    credential: 'not_set',
  },
  {
    id: '00000000000000000000000000000386',
    name: '번역용 Gemini',
    provider: 'gemini',
    endpoint: '',
    revision: 1,
    credential: 'not_set',
  },
];
