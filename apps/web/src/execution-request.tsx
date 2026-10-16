import { createRoot } from 'react-dom/client';
import { request } from './api';
import { frontendOnly } from './preview';
import { ExecutionApproval } from './ExecutionApproval';
import { Button } from './hangyeol/primitives/button';

let activeDialog = false;
// Called only by an explicit UI execution action. Never auto-confirm on refresh or error.
export const executionRequest = <T,>(endpoint: string, payload: Record<string, unknown> = {}, method: 'POST' | 'PUT' = 'POST'): Promise<T> => {
  if (activeDialog) return Promise.reject(new Error('다른 실행 확인 창을 먼저 닫으세요.'));
  activeDialog = true;
  const requestId = typeof payload.request_id === 'string' ? payload.request_id : crypto.randomUUID();
  const dialog = document.createElement('dialog');
  dialog.className = 'execution-approval-dialog';
  dialog.setAttribute('aria-label', '별도 서버 실행 확인');
  document.body.append(dialog);
  const root = createRoot(dialog);
  let executing = false;
  return new Promise<T>((resolve, reject) => {
    const close = () => { dialog.close(); activeDialog = false; queueMicrotask(() => { root.unmount(); dialog.remove(); }); };
    const cancel = () => {
      if (executing) return;
      close();
      reject(new Error('확인 창을 닫았습니다. 저장된 미소비 승인은 실행되지 않으며 만료됩니다. 이미 요청했다면 작업 상태를 확인하세요. 자동 재호출하지 않습니다.'));
    };
    dialog.addEventListener('cancel', event => { event.preventDefault(); cancel(); });
    root.render(<>
      <p>{frontendOnly ? '목업 상태만 변경합니다. 서버·에이전트는 실행하지 않습니다.' : '새 명시 실행 입장입니다. 확인 저장과 실제 실행/큐 입장은 별도입니다. 에이전트를 자동 시작하지 않습니다.'}</p>
      <ExecutionApproval path={'/api' + endpoint} payload={payload} requestId={requestId} actionLabel="승인한 실행 큐 입장" onExecute={async headers => {
        executing = true;
        try {
          const value = await request<T>(endpoint, { method, headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(payload) });
          close(); resolve(value);
        } finally { executing = false; }
      }} />
      <Button variant="secondary" onClick={cancel}>확인 창 닫기</Button>
    </>);
    dialog.showModal();
  });
};
