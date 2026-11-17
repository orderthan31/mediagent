// Only opaque request identifiers cross reloads. No selections or authorization are stored.
const memory = new Map();
const prefix = 'mideagent.pending-start.';
export const validReceiptId = (id) => typeof id === 'string' && /^[a-f0-9]{32}$/.test(id);
export const validNonce = (id) => typeof id === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(id);
const historyPending = (scope) => {
  try {
    const value = globalThis.history?.state?.[prefix + scope];
    return validNonce(value?.request_id) && (!value.receipt_id || validReceiptId(value.receipt_id))
      ? value
      : null;
  } catch {
    return null;
  }
};
export const readPendingStart = (scope = 'create', storage) => {
  try {
    const value = JSON.parse(
      (storage ?? globalThis.sessionStorage)?.getItem(prefix + scope) || 'null',
    );
    if (validNonce(value?.request_id) && (!value.receipt_id || validReceiptId(value.receipt_id))) {
      memory.set(scope, value);
      return value;
    }
  } catch {
    /* In-memory fence still works when storage is unavailable. */
  }
  return historyPending(scope) || memory.get(scope) || null;
};
export const rememberPendingStart = (scope, value, storage) => {
  if (!validNonce(value?.request_id) || (value.receipt_id && !validReceiptId(value.receipt_id))) {
    throw new Error('시작 요청 식별자를 확인하지 못했습니다.');
  }
  const opaque = Object.freeze({
    request_id: value.request_id,
    ...(value.receipt_id ? { receipt_id: value.receipt_id } : {}),
  });
  memory.set(scope, opaque);
  try {
    const target = storage ?? globalThis.sessionStorage;
    if (!target) {
      throw new Error('storage unavailable');
    }
    target.setItem(prefix + scope, JSON.stringify(opaque));
    if (target.getItem(prefix + scope) !== JSON.stringify(opaque)) {
      throw new Error('storage unavailable');
    }
  } catch {
    // Generic intake has a nonce URL. Saved jobs keep the opaque fence in history
    // when session storage is denied, so a reload cannot authorize another POST.
    if (scope.startsWith('job.')) {
      try {
        globalThis.history.replaceState(
          { ...globalThis.history.state, [prefix + scope]: opaque },
          '',
        );
        if (historyPending(scope)?.request_id !== opaque.request_id) {
          throw new Error('history unavailable');
        }
      } catch {
        memory.delete(scope);
        throw new Error('시작 요청 식별자를 저장하지 못했습니다.');
      }
    }
  }
  return opaque;
};
export const forgetPendingStart = (scope, storage) => {
  memory.delete(scope);
  try {
    if (historyPending(scope)) {
      const next = { ...globalThis.history.state };
      delete next[prefix + scope];
      globalThis.history.replaceState(next, '');
    }
  } catch {
    /* Nothing can authorize a replay. */
  }
  try {
    (storage ?? globalThis.sessionStorage)?.removeItem(prefix + scope);
  } catch {
    /* No stored payload to replay. */
  }
};
export const parseStartReceipt = (value) => {
  if (
    !validReceiptId(value?.id) ||
    value.start_request?.id !== value.id ||
    typeof value.start_request?.state !== 'string' ||
    (value.job_id !== null && !validReceiptId(value.job_id))
  ) {
    throw new Error('시작 접수 상태를 확인하지 못했습니다.');
  }
  const state = value.start_request.state;
  if (value.state !== undefined && value.state !== state) {
    throw new Error('시작 접수 상태가 일치하지 않습니다.');
  }
  return Object.freeze({
    id: value.id,
    job_id: value.job_id,
    state,
    code:
      typeof value.start_request.code === 'string'
        ? value.start_request.code
        : typeof value.code === 'string'
          ? value.code
          : '',
  });
};
const startLabels = {
  queued: '시작 대기',
  preparing: '시작 중…',
  admitted: '시작 접수됨',
  blocked: '확인 필요',
  failed: '시작 실패',
  expired: '요청 만료',
  cancelled: '요청 취소됨',
  uncertain: '접수 확인 불가',
};
export const isKnownStartRequestState = (state) => Object.hasOwn(startLabels, state);
export const startRequestLabel = (state) =>
  isKnownStartRequestState(state) ? startLabels[state] : '접수 확인 불가';
export const isStartRequestPending = (state) => ['queued', 'preparing', 'admitted'].includes(state);
export const startReceiptRoute = ({ receipt_id, request_id }) =>
  receipt_id
    ? '#/start-requests/' + receipt_id
    : '#/start-requests?request_id=' + encodeURIComponent(request_id);
export const parseStartRequestRoute = (route) => {
  const receipt = route.match(/^#\/start-requests\/([a-f0-9]{32})$/);
  if (receipt) {
    return { receipt_id: receipt[1] };
  }
  const match = route.match(/^#\/start-requests\?request_id=([^&#]+)$/);
  if (!match) {
    return null;
  }
  try {
    const request_id = decodeURIComponent(match[1]);
    return validNonce(request_id) ? { request_id } : null;
  } catch {
    return null;
  }
};
