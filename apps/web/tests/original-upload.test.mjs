import { test } from 'node:test';
import assert from 'node:assert/strict';
const mod = await import('../src/original-upload.ts').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});
test('original-only4GiB policy reports its real limit', () => {
  assert.equal(typeof mod.assertOriginalUploadSize, 'function');
  mod.assertOriginalUploadSize(2 * 1024 ** 3 + 1);
  mod.assertOriginalUploadSize(4 * 1024 ** 3);
  assert.throws(() => mod.assertOriginalUploadSize(4 * 1024 ** 3 + 1), /4 GiB/);
});
test('202 is not completion: wait for the same original asset without resubmitting', async () => {
  assert.equal(typeof mod.finishOriginalUpload, 'function');
  const calls = [],
    rows = [{ finalization_state: 'running' }, { asset_id: 'same-asset' }];
  await mod.finishOriginalUpload(
    'same-upload',
    new AbortController().signal,
    async (path, init) => {
      calls.push([path, init?.method || 'GET']);
      return init?.method === 'POST' ? { finalization_state: 'queued' } : rows.shift();
    },
    async () => {},
  );
  assert.deepEqual(
    calls.map((x) => x[1]),
    ['POST', 'GET', 'GET'],
  );
  assert.ok(calls.every((x) => x[0].includes('same-upload')));
});
test('restart/interrupted registration requires explicit retry, never automatic newPOST', async () => {
  assert.equal(typeof mod.finishOriginalUpload, 'function');
  let posts = 0;
  await assert.rejects(
    mod.finishOriginalUpload(
      'same',
      new AbortController().signal,
      async (_path, init) => {
        if (init?.method === 'POST') {
          posts++;
          return { finalization_state: 'queued' };
        }
        return { finalization_state: 'pending' };
      },
      async () => {},
    ),
    /재시도/,
  );
  assert.equal(posts, 1);
});
test('pausing status checks makes no next request', async () => {
  assert.equal(typeof mod.finishOriginalUpload, 'function');
  const abort = new AbortController();
  let calls = 0;
  await assert.rejects(
    mod.finishOriginalUpload(
      'same',
      abort.signal,
      async (_path, init) => {
        calls++;
        return { finalization_state: init?.method ? 'queued' : 'running' };
      },
      async () => abort.abort(),
    ),
    { name: 'AbortError' },
  );
  assert.equal(calls, 2);
});
