// Execute the production create/progress callbacks with real opaque persistence.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import esbuild from 'esbuild';
import * as helpers from '../src/start-receipts.mjs';

const section = (file, start, end) => {
  const source = fs.readFileSync(new URL(file, import.meta.url), 'utf8');
  const first = source.indexOf(start);
  assert.ok(first >= 0, start);
  const last = source.indexOf(end, first);
  assert.ok(last > first, end);
  return esbuild.transformSync(source.slice(first, last), { loader: 'tsx' }).code;
};
const createCode = section(
  '../src/WorkflowStart.tsx',
  '  const create = async () => {',
  '  useEffect(() => {',
);
const loadCode = section(
  '../src/StartRequestProgress.tsx',
  '    const load = async () => {',
  '    setReceipt(null);',
);
const a = 'a'.repeat(32),
  b = 'b'.repeat(32),
  job = 'c'.repeat(32);
const receipt = (id, job_id = null) => ({
  id,
  job_id,
  start_request: { id, state: job_id ? 'admitted' : 'queued' },
});
const noop = () => {};
const fixture = () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  const values = new Map();
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
  });
  helpers.forgetPendingStart('create');
  const location = { hash: '#/start' },
    posts = [],
    promises = [];
  const submit = (requestId) => {
    const env = {
      ...helpers,
      creating: { current: false },
      busy: false,
      plan: { token: 'd'.repeat(64), paid_roles: [] },
      translationContextValid: true,
      setBusy: noop,
      setError: noop,
      renewalBackend: true,
      location,
      selection: () => ({ asset_id: 'e'.repeat(32) }),
      requestId,
      entryPath: '/work-entry',
      jsonPost: (path, body) => new Promise((resolve) => posts.push({ path, body, resolve })),
      window: { dispatchEvent: noop },
      frontendOnly: false,
      setTicketId: noop,
    };
    const create = new Function(...Object.keys(env), createCode + '\nreturn create;')(
      ...Object.values(env),
    );
    const pending = create();
    promises.push(pending);
    return pending;
  };
  const observeA = async () => {
    const env = {
      ...helpers,
      controller: new AbortController(),
      request: async () => receipt(a, job),
      receiptId: undefined,
      requestId: 'nonce-A',
      setReceipt: noop,
      setError: noop,
      location,
      setTimeout: () => {
        throw Error('unexpected polling after actual job');
      },
      failures: 0,
      timer: undefined,
    };
    await new Function(...Object.keys(env), loadCode + '\nreturn load();')(...Object.values(env));
  };
  const close = async () => {
    posts.forEach((post) => post.resolve(receipt(post.body.request_id === 'nonce-A' ? a : b)));
    await Promise.allSettled(promises);
    helpers.forgetPendingStart('create');
    if (descriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', descriptor);
    } else {
      delete globalThis.sessionStorage;
    }
  };
  return { location, posts, submit, observeA, close };
};

test('late create ACK cannot replace a newer unresolved nonce or clear its recovery fence', async () => {
  const f = fixture();
  try {
    const old = f.submit('nonce-A');
    await f.observeA();
    assert.equal(helpers.readPendingStart(), null);
    f.location.hash = '#/start';
    f.submit('nonce-B');
    assert.equal(f.posts.length, 2);
    assert.equal(helpers.readPendingStart().request_id, 'nonce-B');
    f.posts[0].resolve(receipt(a));
    await old;
    assert.deepEqual(helpers.readPendingStart(), { request_id: 'nonce-B' });
    assert.equal(
      helpers.startReceiptRoute(helpers.readPendingStart()),
      '#/start-requests?request_id=nonce-B',
    );
    await f.observeA();
    assert.deepEqual(helpers.readPendingStart(), { request_id: 'nonce-B' });
    assert.equal(f.posts.length, 2);
  } finally {
    await f.close();
  }
});

test('late create ACK cannot resurrect an already reconciled and cleared nonce', async () => {
  const f = fixture();
  try {
    const pending = f.submit('nonce-A');
    await f.observeA();
    assert.equal(helpers.readPendingStart(), null);
    f.posts[0].resolve(receipt(a));
    await pending;
    assert.equal(helpers.readPendingStart(), null);
    assert.equal(f.posts.length, 1);
  } finally {
    await f.close();
  }
});

test('matching current create ACK enriches its own nonce exactly once', async () => {
  const f = fixture();
  try {
    const pending = f.submit('nonce-A');
    f.posts[0].resolve(receipt(a));
    await pending;
    assert.deepEqual(helpers.readPendingStart(), { request_id: 'nonce-A', receipt_id: a });
    assert.equal(f.posts.length, 1);
    assert.equal(f.location.hash, '#/start-requests/' + a);
  } finally {
    await f.close();
  }
});
