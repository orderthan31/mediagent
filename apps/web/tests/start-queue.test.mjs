import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: ['src/start-queue-state.ts'],
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'esm',
}).outputFiles[0].text;
const { checkedStartQueue } = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
);
const id = 'a'.repeat(32);
const initial = { revision: 0, paused: false, order: [], jobs: [], details: [] };
const queued = {
  ...initial,
  revision: 3,
  jobs: [id],
  details: [
    {
      job_id: id,
      ticket_number: '140',
      original_filename: '원래 파일 name.mp4',
      workflow_name: '작업',
      status: 'QUEUED',
      access: { can_manage: true },
    },
  ],
};

test('confirmed empty and actual ordered new-member metadata remain distinct', () => {
  assert.deepEqual(checkedStartQueue(initial), initial);
  assert.deepEqual(checkedStartQueue({ ...queued, paused: true, order: [id] }).jobs, [id]);
  assert.equal(checkedStartQueue(queued).details[0].original_filename, '원래 파일 name.mp4');
});
test('malformed/missing queue never becomes false/zero/empty healthy state', () => {
  for (const value of [
    null,
    {},
    { ...initial, paused: 0 },
    { ...initial, progression: 'invalid' },
    { ...initial, revision: -1 },
    { ...initial, revision: Number.MAX_SAFE_INTEGER + 1 },
    { ...queued, details: [] },
    { ...queued, jobs: [id, id] },
    { ...queued, order: ['b'.repeat(32)] },
    { ...queued, details: [{ ...queued.details[0], status: 'RUNNING' }] },
  ]) {
    assert.throws(() => checkedStartQueue(value));
  }
});
