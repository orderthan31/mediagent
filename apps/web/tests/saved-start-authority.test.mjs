// Execute production callbacks verbatim, before React can commit disabled DOM.
import test from 'node:test';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import esbuild from 'esbuild';
import { validReceiptId } from '../src/start-receipts.mjs';
import { requestTrackedStart } from '../src/job-start.mjs';
const source = fs.readFileSync(new URL('../src/RenewalJobDetail.tsx', import.meta.url), 'utf8');
const section = (a, b) => {
  const i = source.indexOf(a);
  assert.ok(i >= 0, a);
  const j = source.indexOf(b, i);
  assert.ok(j > i, b);
  return source.slice(i, j);
};
const refs = section('  const startFence = ', '\n\n  const [modelRolesEnabled');
const callbacks = section('  const reconcileJob = ', '\n  const faceDefinition = ');
const clickBody =
  section('                  onClick={() => {', '\n                  }}').replace(
    '                  onClick={() => {',
    'const click = () => {',
  ) + '\n};';
const id = '1'.repeat(32),
  rid = '9'.repeat(32),
  other = '7'.repeat(32);
const job = { id, status: 'draft', runs: [], revision: 9, start_request: null };
const queued = { ...job, start_request: { id: rid, state: 'queued' } };
const make = (request) => {
  const state = { known: false, receipt: null, posts: [], pending: null };
  const env = {
    id,
    base: '/renewal/jobs/' + id,
    job,
    busy: false,
    serverStart: null,
    startStatusKnown: true,
    validReceiptId,
    request,
    requestTrackedStart,
    crypto: webcrypto,
    useRef: (current) => ({ current }),
    readPendingStart: () => state.pending,
    rememberPendingStart: (scope, value) => (state.pending = value),
    setPendingNonce: (value) => {
      state.pending = value;
    },
    jsonPost: async (path, body) => {
      state.posts.push({ path, body });
      return { id, job_id: id, start_request: { id: rid, state: 'queued' } };
    },
    setJob: (value) => {
      state.job = value;
    },
    setServerStart: (value) => {
      state.receipt = value;
    },
    setStartStatusKnown: (value) => {
      state.known = value;
    },
    setStartStatusError: (value) => {
      state.statusError = value;
    },
    setLoadError: (value) => {
      state.loadError = value;
    },
    setBusy: (value) => {
      state.busy = value;
    },
    setError: (value) => {
      state.error = value;
    },
  };
  const code = esbuild.transformSync(refs + '\n' + callbacks + '\n' + clickBody, {
    loader: 'ts',
  }).code;
  const api = new Function(
    ...Object.keys(env),
    code +
      '\nreturn {reload,action,click,beginObservation,reconcileJob,observeStart,authorityKnown,observedReceipt};',
  )(...Object.values(env));
  return { state, ...api };
};
const flush = async () => {
  for (let i = 0; i < 12; i++) {
    await Promise.resolve();
  }
};
for (const wrapper of [false, true]) {
  test(`late ${wrapper ? 'wrapper' : 'inline'} presence fences actual Start after newer null`, async () => {
    let release,
      calls = 0;
    const f = make(async (path) => {
      if (wrapper && path.endsWith('/start-request')) {
        return new Promise((r) => {
          release = r;
        });
      }
      if (++calls !== 1) {
        return job;
      }
      return wrapper
        ? { id, status: 'draft', runs: [], revision: 8 }
        : new Promise((r) => {
            release = r;
          });
    });
    const old = f.reload();
    await Promise.resolve();
    await f.reload();
    const latestJob = f.state.job;
    release(
      wrapper
        ? { id, job_id: id, start_request: queued.start_request }
        : { ...queued, revision: 8 },
    );
    await old;
    f.click();
    await flush();
    assert.equal(f.state.posts.length, 0);
    assert.deepEqual(f.observedReceipt.current, queued.start_request);
    assert.deepEqual(f.state.receipt, queued.start_request);
    assert.equal(f.state.job, latestJob, 'late presence cannot replace current job');
  });
}
test('manual Refresh action fences synchronously, then valid null allows one explicit Start', async () => {
  let release;
  const f = make(
    async () =>
      new Promise((r) => {
        release = r;
      }),
  );
  f.observeStart(null);
  const refresh = f.action(async () => {});
  f.click(); // No await: intentionally bypass React event flushing.
  await flush();
  assert.equal(f.state.posts.length, 0);
  release(job);
  await refresh;
  f.click();
  f.click();
  await flush();
  assert.equal(f.state.posts.length, 1);
});
test('processed receipt remains sticky after explicit null', async () => {
  const f = make(async () => job);
  f.observeStart(queued.start_request);
  await f.reload();
  f.click();
  await flush();
  assert.equal(f.state.posts.length, 0);
});
test('direct reload fences before yielding', async () => {
  let release;
  const f = make(
    async () =>
      new Promise((r) => {
        release = r;
      }),
  );
  f.observeStart(null);
  const pending = f.reload();
  f.click();
  await flush();
  assert.equal(f.state.posts.length, 0);
  release(job);
  await pending;
});
for (const failure of ['network', 'foreign']) {
  test(`${failure} refresh cannot restore Start authority`, async () => {
    const f = make(async () => {
      if (failure === 'network') {
        throw Error('network lost');
      }
      return { ...job, id: other };
    });
    f.observeStart(null);
    await assert.rejects(f.reload());
    f.click();
    await flush();
    assert.equal(f.state.posts.length, 0);
  });
}
test('refresh queued fences Start', async () => {
  const f = make(async () => queued);
  f.observeStart(null);
  await f.reload();
  f.click();
  await flush();
  assert.equal(f.state.posts.length, 0);
});
for (const wrapper of [false, true]) {
  for (const fault of ['foreign id', 'foreign job_id', 'malformed', 'null', 'aborted']) {
    if (!wrapper && fault === 'foreign job_id') {
      continue;
    }
    test(`stale ${wrapper ? 'wrapper' : 'inline'} ${fault} cannot capture or replace authority`, async () => {
      let release;
      const controller = new AbortController();
      const f = make(
        async () =>
          new Promise((r) => {
            release = r;
          }),
      );
      const token = f.beginObservation();
      const payload = {
        ...(wrapper ? { id, job_id: id } : job),
        start_request:
          fault === 'null'
            ? null
            : fault === 'malformed'
              ? { id: 'invalid', state: 'queued' }
              : queued.start_request,
        ...(fault === 'foreign id' ? { id: other } : {}),
        ...(fault === 'foreign job_id' ? { job_id: other } : {}),
      };
      const pending = wrapper
        ? f.reconcileJob({ id, status: 'draft' }, token, controller.signal)
        : null;
      f.beginObservation(); // Newer observation is still unknown, not proof of absence.
      if (fault === 'aborted') {
        controller.abort();
      }
      if (wrapper) {
        release(payload);
      }
      const result = await Promise.allSettled([
        pending || f.reconcileJob(payload, token, controller.signal),
      ]);
      assert.ok(['fulfilled', 'rejected'].includes(result[0].status));
      assert.equal(f.observedReceipt.current, null);
      assert.equal(f.authorityKnown.current, false);
      f.click();
      await flush();
      assert.equal(f.state.posts.length, 0);
    });
  }
}
test('stale presence does not overwrite a newer receipt or establish current authority', async () => {
  const f = make(async () => job);
  const token = f.beginObservation();
  f.observeStart({ id: rid, state: 'running' });
  f.beginObservation();
  await f.reconcileJob(queued, token);
  assert.deepEqual(f.observedReceipt.current, { id: rid, state: 'running' });
  assert.equal(f.authorityKnown.current, false);
  f.click();
  await flush();
  assert.equal(f.state.posts.length, 0);
});
