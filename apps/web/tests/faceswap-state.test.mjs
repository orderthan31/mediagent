import { test } from 'node:test';
import assert from 'node:assert/strict';
import { frameAtTime, sameSettings, nextAutomaticOperation } from '../src/faceswap-state.ts';

test('playhead maps to one-based frames, including the end of the video', () => {
  assert.equal(frameAtTime(0, 30, 300), 1);
  assert.equal(frameAtTime(1, 30000 / 1001, 300), 30);
  assert.equal(frameAtTime(10, 30, 300), 300);
  assert.equal(frameAtTime(-1, 30, 300), 1);
});

test('automatic queue waits for running work and only requests the next stage', () => {
  const state = {
    blocked: false,
    source: true,
    sourceAnalyzed: false,
    referenceAnalyzed: false,
    selected: false,
    previewReady: false,
  };
  assert.equal(nextAutomaticOperation({ ...state, blocked: true }), null);
  assert.equal(nextAutomaticOperation(state), 'analyze_source');
  assert.equal(nextAutomaticOperation({ ...state, source: false }), 'analyze_reference');
  assert.equal(nextAutomaticOperation({ ...state, sourceAnalyzed: true }), 'analyze_reference');
  assert.equal(
    nextAutomaticOperation({ ...state, sourceAnalyzed: true, referenceAnalyzed: true }),
    null,
  );
  const selected = { ...state, sourceAnalyzed: true, referenceAnalyzed: true, selected: true };
  assert.equal(nextAutomaticOperation(selected), 'preview');
  assert.equal(nextAutomaticOperation({ ...selected, previewReady: true }), null);
  // Seeking invalidates the cursor analysis, but not the selected identity.
  assert.equal(nextAutomaticOperation({ ...selected, referenceAnalyzed: false }), 'preview');
});

test('settings comparison ignores JSON field order but includes masks and identity', () => {
  assert.equal(
    sameSettings(
      { reference_frame: 1, mask_types: ['box'] },
      { mask_types: ['box'], reference_frame: 1 },
    ),
    true,
  );
  assert.equal(sameSettings({ mask_types: ['box'] }, { mask_types: ['area'] }), false);
  assert.equal(sameSettings(undefined, {}), false);
});
