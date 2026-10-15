import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('face stage fallback is not mislabeled as encoding', async () => {
  const source = await readFile(new URL('../src/StageProgress.tsx', import.meta.url), 'utf8');
  assert.match(source, /job\.status === 'FACE_SWAPPING'\s*\? '얼굴 합성'/);
});
