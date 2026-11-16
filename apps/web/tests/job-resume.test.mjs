import test from 'node:test';
import assert from 'node:assert/strict';
import {
  continuePreparedRecovery,
  resumeProof,
  resumeExistingJob,
  inspectResume,
} from '../src/job-resume.mjs';
const job = (id = 'job') => ({
  id,
  revision: 3,
  status: 'running',
  access: { can_manage: true },
  runs: [{ id: 'run', status: 'completed', result: { unit_recovery: { id: 'receipt' } } }],
  reviews: [],
});
test('strict eligibility: applied receipt, owner, completed runs, no cancellation/review', () => {
  assert.ok(resumeProof(job()));
  for (const patch of [
    { status: 'completed' },
    { status: 'cancelled' },
    { status: 'cancelling' },
    { cancel_requested: true },
    { access: { can_manage: false } },
    { access: undefined },
    { id: '../wrong' },
    { revision: NaN },
    { runs: [] },
    { runs: [{ id: 'run', status: 'completed', result: null }] },
    { reviews: [{ status: 'draft' }] },
  ])
    assert.equal(resumeProof({ ...job(), ...patch }), null);
  for (const status of ['running', 'waiting', 'failed', 'unknown', 'review_required', 'cancelled'])
    assert.equal(resumeProof({ ...job(), runs: [...job().runs, { id: 'other', status }] }), null);
});
test('fresh preflight then exactly one existing-job POST; double click and remount cannot replay', async () => {
  const snapshot = job('once'),
    calls = [];
  const request = async (path, init) => {
    calls.push({ path, init });
    return snapshot;
  };
  const results = await Promise.all([
    resumeExistingJob(snapshot, request),
    resumeExistingJob(snapshot, request),
  ]);
  assert.deepEqual(
    results.map((r) => r.state),
    ['sent', 'blocked'],
  );
  assert.equal((await resumeExistingJob(snapshot, request)).state, 'blocked');
  assert.deepEqual(calls, [
    { path: '/renewal/jobs/once', init: undefined },
    {
      path: '/renewal/jobs/once/run',
      init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
    },
  ]);
});
test('scope drift, revision drift, read-only, active, cancel and receipt drift never POST', async () => {
  for (const [index, patch] of [
    { id: 'other' },
    { revision: 4 },
    { access: { can_manage: false } },
    { status: 'cancelled' },
    { runs: [{ id: 'run', status: 'running' }] },
    { runs: [{ id: 'run', status: 'completed', result: { unit_recovery: { id: 'other' } } }] },
  ].entries()) {
    const snapshot = job(`stale-${index}`),
      calls = [];
    await resumeExistingJob(snapshot, async (path, init) => {
      calls.push(init);
      return { ...snapshot, ...patch };
    });
    assert.deepEqual(calls, [undefined]);
  }
  const snapshot = job('unmounted'),
    calls = [];
  await resumeExistingJob(
    snapshot,
    async (path, init) => {
      calls.push(init);
      return snapshot;
    },
    () => false,
  );
  assert.deepEqual(calls, [undefined]);
});
test('unknown POST response remains locked; status inspection is GET only', async () => {
  const snapshot = job('lost'),
    calls = [];
  const request = async (path, init) => {
    calls.push({ path, init });
    if (init) throw Error('lost');
    return snapshot;
  };
  assert.equal((await resumeExistingJob(snapshot, request)).state, 'uncertain');
  await inspectResume(snapshot.id, request);
  assert.equal((await resumeExistingJob({ ...snapshot, revision: 4 }, request)).state, 'blocked');
  assert.equal(
    (
      await resumeExistingJob(
        { ...snapshot, runs: [...snapshot.runs, { id: 'downstream', status: 'completed' }] },
        request,
      )
    ).state,
    'stale',
  );
  assert.equal(calls.filter((c) => c.init).length, 1);
});
test('GET failure is safe to retry explicitly; no automatic retry', async () => {
  const snapshot = job('read-failure');
  let calls = 0;
  assert.equal(
    (
      await resumeExistingJob(snapshot, async () => {
        calls++;
        throw Error('offline');
      })
    ).state,
    'read-error',
  );
  assert.equal(calls, 1);
  assert.equal((await resumeExistingJob(snapshot, async () => snapshot)).state, 'sent');
});

test('a newly completed downstream frontier needs a new explicit action, not a permanent receipt lock', async () => {
  const first = job('next-frontier');
  const calls = [];
  const requestFirst = async (path, init) => {
    calls.push({ path, init });
    return first;
  };
  assert.equal((await resumeExistingJob(first, requestFirst)).state, 'sent');
  assert.equal((await resumeExistingJob({ ...first, revision: 4 }, requestFirst)).state, 'blocked');
  const next = {
    ...first,
    revision: 5,
    runs: [...first.runs, { id: 'new-review', status: 'completed' }],
    reviews: [{ status: 'confirmed' }],
  };
  assert.equal(
    (
      await resumeExistingJob(next, async (path, init) => {
        calls.push({ path, init });
        return next;
      })
    ).state,
    'sent',
  );
  assert.equal(calls.filter((c) => c.init).length, 2);
  assert.ok(calls.filter((c) => c.init).every((c) => c.path === '/renewal/jobs/next-frontier/run'));
});

test('prepared continuation shares its uncertain frontier with ordinary resume', async () => {
  const initial = job('prepared-link');
  initial.runs[0].status = 'running';
  initial.runs[0].result = null;
  const view = {
    job_id: initial.id,
    run_id: initial.runs[0].id,
    job_revision: initial.revision,
    recovery_revision: 1,
    context_sha256: 'a'.repeat(64),
    access: { can_manage: true },
    recovery: { id: 'prepared-receipt', request_id: 'r', can_continue: true },
  };
  const calls = [];
  const request = async (path, init) => {
    calls.push({ path, init });
    if (init) throw Error('lost-after-adoption');
    return path.endsWith('/unit-recovery') ? view : initial;
  };
  assert.equal((await continuePreparedRecovery(view, request)).state, 'uncertain');
  assert.equal((await continuePreparedRecovery(view, request)).state, 'blocked');
  const adopted = {
    ...initial,
    runs: initial.runs.map((r) => ({
      ...r,
      status: 'completed',
      result: { unit_recovery: { id: view.recovery.id } },
    })),
  };
  assert.equal((await resumeExistingJob(adopted, request)).state, 'blocked');
  assert.equal(calls.filter((c) => c.init).length, 1);
  assert.ok(calls.find((c) => c.init).path.endsWith('/unit-recovery/continue'));
});

test('prepared continuation fresh-scope, access, cancellation and UI fences prevent POST', async () => {
  for (const bad of ['revision', 'context', 'access', 'cancel', 'active-other', 'unmount']) {
    const initial = job('prepared-' + bad);
    initial.runs[0].status = 'running';
    initial.runs[0].result = null;
    const view = {
      job_id: initial.id,
      run_id: initial.runs[0].id,
      job_revision: initial.revision,
      recovery_revision: 1,
      context_sha256: 'a'.repeat(64),
      access: { can_manage: true },
      recovery: { id: 'rec-' + bad, request_id: 'r', can_continue: true },
    };
    const fresh = structuredClone(view);
    if (bad === 'context') fresh.context_sha256 = 'b'.repeat(64);
    if (bad === 'access') fresh.access.can_manage = false;
    if (bad === 'cancel') initial.cancel_requested = true;
    if (bad === 'revision') initial.revision++;
    if (bad === 'active-other') initial.runs.push({ id: 'another', status: 'running' });
    let posts = 0;
    await continuePreparedRecovery(
      view,
      async (path, init) => {
        if (init) posts++;
        return path.endsWith('/unit-recovery') ? fresh : initial;
      },
      () => bad !== 'unmount',
    );
    assert.equal(posts, 0, bad);
  }
});
