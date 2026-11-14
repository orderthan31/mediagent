export function startSavedJob(
  get: <T = any>(path: string) => Promise<T>,
  post: <T = any>(path: string, body: unknown) => Promise<T>,
  id: string,
  nonce: string,
  onStage?: (stage: string) => void,
): Promise<any>;
export const startTrackedJob: typeof startSavedJob;
export type JobStartState = Readonly<{ pending: boolean; stage: string; error: string }>;
export function getJobStartState(id: string): JobStartState | null;
export function subscribeJobStarts(listener: () => void): () => void;
