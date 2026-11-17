import test from 'node:test';
import assert from 'node:assert/strict';
import { requestTrackedStart, getJobStartState, subscribeJobStarts } from '../src/job-start.mjs';

const id = (n) => n.toString(16).padStart(32, '0');
const dto = (n) => ({ id: id(n), job_id: id(n), start_request: { id: id(9000), state: 'queued' } });

test('explicit saved-job Start submits one server-owned request and no browser workflow chain', async () => {
  const calls = [];
  const receipt = dto(2001);
  const post = async (path, body) => {
    calls.push({ path, body });
    return receipt;
  };
  assert.deepEqual(await requestTrackedStart(post, id(2001), 2, 'explicit-start-1'), receipt);
  assert.deepEqual(calls, [
    {
      path: '/renewal/jobs/' + id(2001) + '/start-request',
      body: { revision: 2, request_id: 'explicit-start-1' },
    },
  ]);
  assert.equal(getJobStartState(id(2001)).pending, false);
  assert.equal(getJobStartState(id(2001)).stage, 'accepted');
});

test('shared submission fence is installed before double clicks or notifications', async () => {
  let release;
  let calls = 0;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const post = async () => {
    calls++;
    return gate;
  };
  let notificationSawPending = false;
  const unsubscribe = subscribeJobStarts(() => {
    if (getJobStartState(id(2002))?.pending) {
      notificationSawPending = true;
    }
  });
  const first = requestTrackedStart(post, id(2002), 3, 'explicit-start-2');
  const second = requestTrackedStart(post, id(2002), 3, 'explicit-start-2');
  assert.equal(first, second);
  assert.equal(getJobStartState(id(2002)).pending, true);
  await Promise.resolve();
  assert.equal(calls, 1);
  release(dto(2002));
  await first;
  unsubscribe();
  assert.equal(notificationSawPending, true);
  assert.equal(calls, 1);
});

test('lost response is visible and never automatically followed by confirm, admit, run or another POST', async () => {
  let calls = 0;
  const post = async () => {
    calls++;
    throw new Error('response unavailable');
  };
  await assert.rejects(
    requestTrackedStart(post, id(2003), 4, 'explicit-start-3'),
    /response unavailable/,
  );
  await Promise.resolve();
  assert.equal(calls, 1);
  assert.equal(getJobStartState(id(2003)).pending, false);
  assert.equal(getJobStartState(id(2003)).error, 'response unavailable');
});

for (const [name, change] of [
  ['foreign job_id', (value) => ({ ...value, job_id: id(9999) })],
  ['foreign id', (value) => ({ ...value, id: id(9999) })],
  ['missing job_id', ({ job_id, ...value }) => value],
  ['missing receipt id', (value) => ({ ...value, start_request: { state: 'queued' } })],
  [
    'malformed receipt id',
    (value) => ({ ...value, start_request: { id: 'bad', state: 'queued' } }),
  ],
  [
    'unknown state',
    (value) => ({ ...value, start_request: { id: id(9000), state: 'constructor' } }),
  ],
]) {
  test('malformed acknowledgement remains uncertain: ' + name, async () => {
    let calls = 0;
    await assert.rejects(
      requestTrackedStart(
        async () => {
          calls++;
          return change(dto(2010));
        },
        id(2010),
        9,
        'original-nonce',
      ),
    );
    assert.equal(calls, 1);
    assert.notEqual(getJobStartState(id(2010)).stage, 'accepted');
    assert.ok(getJobStartState(id(2010)).error);
  });
}

test('reading or subscribing to request state cannot submit work', () => {
  assert.equal(getJobStartState(id(2004)), null);
  const unsubscribe = subscribeJobStarts(() => {});
  unsubscribe();
  assert.equal(getJobStartState(id(2004)), null);
});
