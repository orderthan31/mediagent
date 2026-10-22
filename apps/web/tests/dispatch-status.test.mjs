import { test } from 'node:test';
import assert from 'node:assert/strict';

test('dispatch waiting and send confirmation are not actual processing', async () => {
  const { dispatchLabel } = await import('../src/dispatch-status.ts');
  assert.equal(dispatchLabel('waiting', 'pending'), '에이전트 시작 대기');
  assert.equal(dispatchLabel('waiting', 'sent'), '전송됨 · 수신 확인 대기');
  assert.equal(dispatchLabel('running', 'received'), '처리 중');
  assert.equal(dispatchLabel('waiting', 'unknown'), '전송 결과 확인 필요');
  assert.equal(dispatchLabel('completed', 'received'), null);
  assert.equal(dispatchLabel('cancelled', 'sent'), null);
});
