export function taskLogForRun<T extends { run_id: string }>(
  logs: T | null,
  runId?: string,
): T | null;
