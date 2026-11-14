import test from 'node:test';
import assert from 'node:assert/strict';
import { startTrackedJob, getJobStartState, subscribeJobStarts } from '../src/job-start.mjs';

test('shared fence, stable snapshots, failure clearing and bounded settled retention', async () => {
  let release;
  let calls = 0;
  const get = async () => {
    calls++;
    return new Promise((resolve) => {
      release = resolve;
    });
  };
  const post = async () => {
    throw new Error('must not mutate non-draft');
  };
  let notifications = 0;
  const unsubscribe = subscribeJobStarts(() => {
    notifications++;
  });
  const first = startTrackedJob(get, post, 'pending', 'original');
  assert.equal(startTrackedJob(get, post, 'pending', 'duplicate'), first);
  assert.equal(getJobStartState('pending').pending, true);
  assert.equal(getJobStartState('pending'), getJobStartState('pending'));
  await Promise.resolve();
  assert.equal(calls, 1);
  for (let i = 0; i < 40; i++) {
    await assert.rejects(
      startTrackedJob(async () => ({ status: 'running' }), post, 'settled-' + i, 'nonce'),
      /이미 시작/,
    );
  }
  assert.equal(getJobStartState('settled-0'), null);
  assert.equal(getJobStartState('pending').pending, true);
  release({ status: 'draft', runs: [{}] });
  await assert.rejects(first, /이미 시작/);
  assert.match(getJobStartState('pending').error, /이미 시작/);
  const next = startTrackedJob(get, post, 'pending', 'new-explicit-click');
  assert.equal(getJobStartState('pending').error, '');
  assert.equal(getJobStartState('pending').pending, true);
  await Promise.resolve();
  release({ status: 'running' });
  await assert.rejects(next, /이미 시작/);
  assert.ok(notifications > 0);
  unsubscribe();
});
