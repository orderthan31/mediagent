import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const bundle = await build({
  entryPoints: ['src/job-execution-flow.ts'],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { executionProgress, executionTask, currentExecutionTask } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`
);
const agent = {
  id: 'speech',
  type: 'transcription_agent',
  label: 'Speech',
  state: 'running',
  selected_tool_id: 'asr',
  tools: [
    { node_id: 'asr', role: 'transcription', label: 'ASR', state: 'running', run_id: 'run-a' },
  ],
};

test('planned work is independent of requests/budgets and failures never become successes', () => {
  const value = executionProgress({
    run_id: 'run-a',
    progress: {
      planned_segments: 96,
      completed_segments: 95,
      failed_segments: 1,
      finished_segments: 96,
      total_calls: 200,
      max_model_calls: 999,
    },
  });
  assert.deepEqual(
    [value.processed, value.total, value.completed, value.failed, value.determinate],
    [96, 96, 95, 1, true],
  );
  assert.equal(
    executionProgress({ progress: { total_calls: 20, max_model_calls: 500 } }).total,
    null,
  );
});
test('unknown, zero, malformed and inconsistent counts are not percent completion', () => {
  assert.equal(executionProgress().determinate, false);
  assert.equal(
    executionProgress({
      progress: { planned_segments: null, completed_segments: 4, failed_segments: 1 },
    }).processed,
    5,
  );
  assert.equal(
    executionProgress({
      progress: { planned_segments: 0, completed_segments: 0, failed_segments: 0 },
    }).empty,
    true,
  );
  for (const progress of [
    { planned_segments: 0, completed_segments: 0, failed_segments: 0, active_segments: [1] },
    { planned_segments: 3, completed_segments: 4, failed_segments: 0 },
    { planned_segments: 10, completed_segments: 4, failed_segments: 1, finished_segments: 6 },
  ]) {
    assert.equal(executionProgress({ progress }).inconsistent, true);
    assert.equal(executionProgress({ progress }).determinate, false);
  }
  assert.equal(executionProgress({ progress: { planned_segments: -1 } }).total, null);
  assert.equal(executionProgress({ progress: { planned_segments: Infinity } }).total, null);
});
test('run identity and public terminal state fence stale internal tool updates', () => {
  const projection = { run_id: 'run-a', state: 'running', display_state: 'failed' };
  assert.equal(executionTask(agent, { 'run-a': projection }).state, 'failed');
  assert.equal(
    executionTask(agent, { 'run-a': { ...projection, run_id: 'old-run' } }).run,
    undefined,
  );
  for (const state of ['held', 'cancelled', 'completed', 'failed']) {
    assert.equal(
      executionTask({ ...agent, state }, { 'run-a': { ...projection, display_state: 'running' } })
        .state,
      state,
    );
  }
});
test('focus active work first, otherwise the failed/held blocker rather than future waiting', () => {
  const task = (id, state) => executionTask({ ...agent, id, state }, {});
  assert.equal(
    currentExecutionTask([task('future', 'waiting'), task('blocked', 'failed')]),
    'blocked',
  );
  assert.equal(
    currentExecutionTask([task('running', 'running'), task('blocked', 'held')]),
    'running',
  );
  assert.equal(
    currentExecutionTask([task('future', 'waiting'), task('prep', 'preparing')]),
    'prep',
  );
  assert.equal(currentExecutionTask([task('future', 'waiting')]), null);
  assert.equal(currentExecutionTask([task('done', 'completed')]), null);
});
