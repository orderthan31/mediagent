import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseStartReceipt,
  startRequestLabel,
  isStartRequestPending,
  rememberPendingStart,
  readPendingStart,
  forgetPendingStart,
  startReceiptRoute,
  parseStartRequestRoute,
} from '../src/start-receipts.mjs';
const id = 'a'.repeat(32);
const receipt = (state, job_id = null) => ({ id, job_id, start_request: { id, state } });
test('a pre-job receipt never substitutes its id for a real job; parsing is immutable', () => {
  const source = receipt('queued');
  const parsed = parseStartReceipt(source);
  assert.equal(parsed.job_id, null);
  assert.equal(Object.isFrozen(parsed), true);
  assert.deepEqual(source, receipt('queued'));
  assert.throws(() => parseStartReceipt({ id, start_request: { id, state: 'queued' } }));
  assert.throws(() => parseStartReceipt(receipt('queued', 'not-a-job')));
  assert.throws(() => parseStartReceipt({ ...receipt('queued'), state: 'failed' }));
});
test('unknown and terminal states cannot look successful or pending', () => {
  for (const state of [
    'failed',
    'expired',
    'cancelled',
    'uncertain',
    'unrecognized',
    '__proto__',
    'constructor',
    'toString',
    '',
    0,
  ]) {
    assert.equal(isStartRequestPending(state), false);
    assert.doesNotMatch(startRequestLabel(state), /완료|처리 중|접수됨/);
  }
  assert.equal(startRequestLabel('unrecognized'), '접수 확인 불가');
});
test('only opaque original nonce and receipt survive storage; invalidation cannot mutate stored scope', () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key),
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const source = {
    request_id: 'original-nonce',
    receipt_id: id,
    transcript: 'private',
    options: { secret: 'no' },
  };
  rememberPendingStart('unit', source, storage);
  source.request_id = 'different-scope';
  assert.deepEqual(readPendingStart('unit', storage), {
    request_id: 'original-nonce',
    receipt_id: id,
  });
  assert.doesNotMatch([...values.values()].join(''), /private|secret|transcript|options/);
  forgetPendingStart('unit', storage);
  assert.equal(readPendingStart('unit', storage), null);
});
test('storage unavailable retains uncertainty in memory without inventing an acknowledgement', () => {
  const storage = {
    getItem() {
      throw Error('denied');
    },
    setItem() {
      throw Error('denied');
    },
    removeItem() {
      throw Error('denied');
    },
  };
  rememberPendingStart('denied', { request_id: 'original' }, storage);
  assert.deepEqual(readPendingStart('denied', storage), { request_id: 'original' });
  forgetPendingStart('denied', storage);
});
test('exact ordinary status routes include encoded nonce, not arbitrary paths or queries', () => {
  const route = startReceiptRoute({ request_id: 'original-nonce' });
  assert.deepEqual(parseStartRequestRoute(route), { request_id: 'original-nonce' });
  assert.deepEqual(parseStartRequestRoute('#/start-requests/' + id), { receipt_id: id });
  for (const value of [
    '#/start-requests',
    '#/start-requests?request_id=x&admin=1',
    '#/start-requests?request_id=%',
    '#/start-requests?request_id=%2Fsettings',
    '#/start-requests/' + id + '/edit',
    '#/settings',
  ]) {
    assert.equal(parseStartRequestRoute(value), null);
  }
});
