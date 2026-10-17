export type ServingConnection = {
  id: string;
  name: string;
  provider: string;
  endpoint: string;
  revision: number;
  credential: 'not_set';
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
