export type QueueState = { revision: number; paused: boolean; order: string[]; jobs: string[] };

export const moveQueuedJob = (ids: string[], id: string, destination: number) => {
  const from = ids.indexOf(id);
  if (from < 0) {
    return [...ids];
  }
  const next = [...ids];
  next.splice(from, 1);
  next.splice(Math.max(0, Math.min(next.length, destination)), 0, id);
  return next;
};

export const elapsedSeconds = (started: string | undefined, now: number) => {
  const value = started ? Date.parse(started) : NaN;
  return Number.isFinite(value) ? Math.max(0, Math.floor((now - value) / 1000)) : null;
};

export const timeLabel = (seconds: number) => {
  const safe = Math.max(0, Math.round(seconds));
  return safe < 60 ? `${safe}초` : `${Math.floor(safe / 60)}분 ${safe % 60}초`;
};
