import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canRetryBusy, retryBusy } from '../src/busy-retry.ts';

test('busy retries preserve the original request and reach success', async () => {
  let calls = 0;
  const result = await retryBusy(async () => {
    calls++;
    return calls === 1
      ? Response.json({ code: 'job_busy' }, { status: 409 })
      : Response.json({ upload_id: 'same-id' });
  });
  assert.equal(calls, 2);
  assert.equal((await result.json()).upload_id, 'same-id');
});

test('offset/revision conflicts and network errors are not blindly replayed', async () => {
  let calls = 0;
  const response = await retryBusy(async () => {
    calls++;
    return Response.json({ detail: { expected_offset: 4 } }, { status: 409 });
  });
  assert.equal(calls, 1);
  assert.equal(response.status, 409);
  await assert.rejects(
    retryBusy(async () => {
      throw new TypeError('network');
    }),
    /network/,
  );
});

test('busy wait is cancellable and bounded', async () => {
  const controller = new AbortController();
  let calls = 0;
  const pending = retryBusy(async () => {
    calls++;
    return Response.json({ code: 'job_busy' }, { status: 409 });
  }, controller.signal);
  setTimeout(() => controller.abort(new Error('paused')), 10);
  await assert.rejects(pending, /paused/);
  assert.equal(calls, 1);
  const response = await retryBusy(
    async () => Response.json({ code: 'job_busy' }, { status: 409 }),
    null,
    0,
  );
  assert.equal(response.status, 409);
});

test('only reads, resumable upload operations and keyed creations retry automatically', () => {
  assert.equal(
    canRetryBusy('/video-uploads', {
      method: 'POST',
      body: JSON.stringify({ request_id: 'stable' }),
    }),
    true,
  );
  assert.equal(canRetryBusy('/video-uploads/abcdef/complete', { method: 'POST' }), true);
  assert.equal(
    canRetryBusy('/videos/abc/jobs', {
      method: 'POST',
      body: JSON.stringify({ request_id: 'stable' }),
    }),
    true,
  );
  assert.equal(canRetryBusy('/videos/abc/subtitles', { method: 'POST', body: '{}' }), false);
  assert.equal(canRetryBusy('/jobs/abc', { method: 'DELETE' }), false);
});
