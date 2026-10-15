import { test } from 'node:test';
import assert from 'node:assert/strict';
import { moveQueuedJob, elapsedSeconds, timeLabel } from '../src/queue-state.ts';

test('priority moves preserve identity and clamp positions without mutating input', () => {
  const original = ['a', 'b', 'c'];
  assert.deepEqual(moveQueuedJob(original, 'c', 0), ['c', 'a', 'b']);
  assert.deepEqual(moveQueuedJob(original, 'a', 100), ['b', 'c', 'a']);
  assert.deepEqual(moveQueuedJob(original, 'missing', 0), original);
  assert.deepEqual(original, ['a', 'b', 'c']);
});

test('timing handles missing, invalid and future timestamps', () => {
  const now = Date.parse('2026-09-29T10:00:20Z');
  assert.equal(elapsedSeconds('2026-09-29T10:00:00Z', now), 20);
  assert.equal(elapsedSeconds('2026-09-29T10:01:00Z', now), 0);
  assert.equal(elapsedSeconds(undefined, now), null);
  assert.equal(elapsedSeconds('invalid', now), null);
  assert.equal(timeLabel(125), '2분 5초');
});
