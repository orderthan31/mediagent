/** One explicit click authorizes the displayed immutable job, never a background start. */
export const startSavedJob = async (get, post, id, nonce, onStage = () => {}) => {
  const base = '/renewal/jobs/' + id;
  onStage('checking');
  const current = await get(base);
  if (current.status !== 'draft' || current.runs?.length) {
    throw new Error('이미 시작된 작업입니다. 현재 진행 상태를 확인해 주세요.');
  }
  onStage('prepare-start');
  await post(base + '/prepare-start', {
    revision: current.revision,
    request_id: nonce + '-prepare',
  });
  onStage('plan');
  const plan = await get(base + '/plan');
  if (!plan.ready) {
    throw new Error(plan.reasons?.join(' ') || '작업 설정을 확인해 주세요.');
  }
  onStage('confirm');
  const consent = await post(base + '/confirm', {
    token: plan.token,
    request_id: nonce + '-confirm',
  });
  onStage('admit');
  await post(base + '/admit', { consent_id: consent.id, request_id: nonce + '-admit' });
  onStage('run');
  return post(base + '/run', {});
};

// Document-local visibility only: no stored authorization and no reload replay.
const states = new Map();
const active = new Map();
const listeners = new Set();
export const getJobStartState = (id) => states.get(id) ?? null;
export const subscribeJobStarts = (listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const publish = (id, state) => {
  states.delete(id);
  states.set(id, Object.freeze(state));
  const settled = [...states].filter(([, value]) => !value.pending);
  for (const [key] of settled.slice(0, Math.max(0, settled.length - 32))) {
    states.delete(key);
  }
  for (const listener of listeners) {
    listener();
  }
};
export const startTrackedJob = (get, post, id, nonce) => {
  if (active.has(id)) {
    return active.get(id);
  }
  // Install the shared fence before notifying subscribers or issuing requests.
  const promise = Promise.resolve().then(async () => {
    try {
      const result = await startSavedJob(get, post, id, nonce, (stage) =>
        publish(id, { pending: true, stage, error: '' }),
      );
      publish(id, { pending: false, stage: 'completed', error: '' });
      return result;
    } catch (reason) {
      publish(id, {
        pending: false,
        stage: states.get(id)?.stage || 'checking',
        error: reason instanceof Error ? reason.message : '시작 요청 실패',
      });
      throw reason;
    } finally {
      active.delete(id);
    }
  });
  active.set(id, promise);
  publish(id, { pending: true, stage: 'checking', error: '' });
  return promise;
};
