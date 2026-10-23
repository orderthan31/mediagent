// Original admission only. Processing roles/results and HTTP body limits are unchanged.
export const MAX_ORIGINAL_UPLOAD_BYTES = 4 * 1024 ** 3;
export const assertOriginalUploadSize = (size: number) => {
  if (!Number.isSafeInteger(size) || size <= 0 || size > MAX_ORIGINAL_UPLOAD_BYTES) {
    throw new Error('원본 업로드는 파일당 최대 4 GiB (4,294,967,296 bytes)입니다.');
  }
};

type Registration = {
  asset_id?: string | null;
  finalization_state?: string;
  finalization_error?: string;
};
type Send = <T>(path: string, init?: RequestInit) => Promise<T>;
const wait = (signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    signal.throwIfAborted();
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', done);
      resolve();
    };
    const timer = setTimeout(done, 1000);
    signal.addEventListener('abort', done, { once: true });
  });
export const finishOriginalUpload = async (
  id: string,
  signal: AbortSignal,
  send: Send,
  delay: (signal: AbortSignal) => Promise<void> = wait,
) => {
  signal.throwIfAborted();
  let state = await send<Registration>(`/video-uploads/${id}/complete`, { method: 'POST', signal });
  const deadline = Date.now() + 30 * 60 * 1000;
  while (!state.asset_id) {
    signal.throwIfAborted();
    state = await send<Registration>(`/video-uploads/${id}`, { signal });
    if (state.asset_id) {
      return;
    }
    if (!['queued', 'running'].includes(state.finalization_state || '')) {
      throw new Error(
        state.finalization_error ||
          '원본 등록이 중단됐습니다. 청크는 보존됐으니 같은 업로드의 등록을 재시도하세요.',
      );
    }
    if (Date.now() > deadline) {
      throw new Error(
        '등록 상태 확인 시간이 지났습니다. 원본을 다시 전송하지 말고 같은 업로드 상태를 확인하세요.',
      );
    }
    await delay(signal);
  }
};
