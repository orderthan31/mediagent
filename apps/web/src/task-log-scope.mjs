/** Never show the previous tool's console while a new request is starting. */
export const taskLogForRun = (logs, runId) => (logs && logs.run_id === runId ? logs : null);
