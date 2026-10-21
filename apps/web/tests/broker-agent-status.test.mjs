import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';

const load = async () => {
  const url = new URL('../src/broker-agent-status.ts', import.meta.url);
  assert.ok(existsSync(url), 'AMQP status presentation missing');
  return import(url.href);
};

test('AMQP consumer connectivity is not presented as enabled or inference ready', async () => {
  const { brokerStatusView } = await load();
  const view = brokerStatusView({ state: 'connected', consumers: 2, messages_ready: 3 });
  assert.equal(view.title, 'consumer 연결됨');
  assert.equal(view.consumers, '2개');
  assert.equal(view.pending, '3개');
  assert.equal(view.canControl, false);
  assert.match(view.notice, /추론 준비.*별도/);
});

test('failed observations never reuse stale zero or positive consumer counts', async () => {
  const { brokerStatusView } = await load();
  for (const consumers of [null, 0, 2]) {
    const view = brokerStatusView({ state: 'unknown', consumers, messages_ready: 0 });
    assert.equal(view.title, '실제 연결 상태 확인 불가');
    assert.equal(view.consumers, '확인 불가');
    assert.equal(view.pending, '확인 불가');
  }
});

test('observed zero consumers is disconnected, not unsupported', async () => {
  const { brokerStatusView } = await load();
  const view = brokerStatusView({ state: 'disconnected', consumers: 0, messages_ready: 0 });
  assert.equal(view.title, '연결된 consumer 없음');
  assert.equal(view.consumers, '0개');
  assert.equal(brokerStatusView({ state: 'controller' }).title, '애플리케이션 제어 노드');
  assert.equal(brokerStatusView({ state: 'unsupported' }).title, '실행 경로 미지원');
});
