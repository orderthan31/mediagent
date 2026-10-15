export const frameAtTime = (time: number, fps: number, count?: number) =>
  Math.min(count || Number.MAX_SAFE_INTEGER, Math.max(1, Math.floor(time * fps + 0.00001) + 1));

export const sameSettings = (a: object | undefined, b: object | null) => {
  const stable = (value: object) =>
    JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
  return !!a && !!b && stable(a) === stable(b);
};

// Only one automatic operation may be in flight. A new cursor replaces the pending
// intent, not the reference identity chosen by the user.
export const nextAutomaticOperation = (state: {
  blocked: boolean;
  source: boolean;
  sourceAnalyzed: boolean;
  referenceAnalyzed: boolean;
  selected: boolean;
  previewReady: boolean;
}) => {
  if (state.blocked) {
    return null;
  }
  if (state.source && !state.sourceAnalyzed) {
    return 'analyze_source';
  }
  if (state.source && state.selected && !state.previewReady) {
    return 'preview';
  }
  if (!state.referenceAnalyzed) {
    return 'analyze_reference';
  }
  return null;
};
