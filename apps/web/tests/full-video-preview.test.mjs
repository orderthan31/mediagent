import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = (name) => readFileSync(new URL('../src/' + name, import.meta.url), 'utf8');
test('full coverage is a separate durable preview control in original and accepted output screens', () => {
  const control = source('FullVideoPreview.tsx');
  assert.match(control, /전체길이 WebM/);
  assert.match(control, /not_requested/);
  assert.match(control, /cancel_requested/);
  assert.match(control, /자동 재실행/);
  assert.match(source('StorageVideo.tsx'), /<FullVideoPreview/);
  assert.match(source('RenewalJobDetail.tsx'), /<FullVideoPreview/);
});
