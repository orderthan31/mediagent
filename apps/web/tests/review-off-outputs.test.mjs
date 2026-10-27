import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
test('review-OFF output is not displayed as a confirmed human review', () => {
  const source = readFileSync(new URL('../src/SubtitleTracksPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /output\.review\s*\?/);
  assert.match(source, /검수 OFF · 자동 생성/);
});
