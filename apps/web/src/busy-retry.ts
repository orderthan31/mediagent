const pause = (ms: number, signal?: AbortSignal | null) =>
  new Promise<void>((resolve, reject) => {
    const finish = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      resolve();
    };
    const cancel = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      reject(signal?.reason);
    };
    const timer = setTimeout(finish, ms);
    signal?.addEventListener('abort', cancel, { once: true });
    if (signal?.aborted) {
      cancel();
    }
  });

export const canRetryBusy = (path: string, init?: RequestInit) => {
  const method = (init?.method || 'GET').toUpperCase();
  if (method !== 'GET' && (new Headers(init?.headers).has('X-Execution-Approval') || /^\/(?:settings\/[^/]+-tickets\/[^/]+\/(?:start|continue)|videos\/[^/]+\/jobs|jobs\/[^/]+\/(?:start|retry))$/.test(path))) {
    return false;
  }
  if (method === 'GET' || method === 'HEAD') {
    return true;
  }
  if (/^\/(?:video-uploads|uploads)\/[a-f0-9]+\/(?:complete|verify|chunks)(?:\?|$)/.test(path)) {
    return true;
  }
  if (method === 'POST' && typeof init?.body === 'string') {
    try {
      return typeof JSON.parse(init.body).request_id === 'string';
    } catch {
      return false;
    }
  }
  return false;
};

export const retryBusy = async (
  send: () => Promise<Response>,
  signal?: AbortSignal | null,
  budgetMs = 60000,
) => {
  const deadline = Date.now() + budgetMs;
  for (let attempt = 0; ; attempt++) {
    signal?.throwIfAborted();
    const response = await send();
    if (response.status !== 409) {
      return response;
    }
    const body = await response
      .clone()
      .json()
      .catch(() => ({}));
    if (body.code !== 'job_busy' || Date.now() >= deadline || attempt >= 30) {
      return response;
    }
    const delay = Math.min(2000, 250 * 2 ** Math.min(attempt, 3)) + Math.random() * 150;
    await pause(Math.min(delay, Math.max(0, deadline - Date.now())), signal);
    if (Date.now() >= deadline) {
      return response;
    }
  }
};
