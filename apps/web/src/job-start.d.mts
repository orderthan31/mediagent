export function startSavedJob(
  get: <T = any>(path: string) => Promise<T>,
  post: <T = any>(path: string, body: unknown) => Promise<T>,
  id: string,
  nonce: string,
): Promise<any>;
