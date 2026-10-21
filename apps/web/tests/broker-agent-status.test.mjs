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
  assert.equal(view.title, '연결됨');
  assert.equal(view.consumers, '2개');
  assert.equal(view.pending, '3개');
  assert.equal(view.canControl, false);
  assert.equal('notice' in view, false);
});

test('failed observations never reuse stale zero or positive consumer counts', async () => {
  const { brokerStatusView } = await load();
  for (const consumers of [null, 0, 2]) {
    const view = brokerStatusView({ state: 'unknown', consumers, messages_ready: 0 });
    assert.equal(view.title, '확인 불가');
    assert.equal(view.consumers, '확인 불가');
    assert.equal(view.pending, '확인 불가');
  }
});

test('worker telemetry has distinct readiness, busy and expired-heartbeat states', async () => {
  const { brokerStatusView } = await load();
  for (const [state, title] of [
    ['connected', '정상'],
    ['ready', '정상'],
    ['busy', '처리 중'],
    ['heartbeat_lost', '연결 끊김'],
    ['unknown', '확인 불가'],
  ]) {
    assert.equal(brokerStatusView({ state, telemetry: true }).title, title);
  }
});

test('observed zero consumers is disconnected, not unsupported', async () => {
  const { brokerStatusView } = await load();
  const view = brokerStatusView({ state: 'disconnected', consumers: 0, messages_ready: 0 });
  assert.equal(view.title, '연결 끊김');
  assert.equal(view.consumers, '0개');
  assert.equal(brokerStatusView({ state: 'controller' }).title, '확인 불가');
  assert.equal(brokerStatusView({ state: 'unsupported' }).title, '확인 불가');
});
