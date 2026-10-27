import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
test('role recovery UI is explicit artifact-only and does not dereference absent legacy attempts', async () => {
  const source = await readFile(new URL('../src/ModelRolePanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /결과 전달만 다시 확인/);
  assert.match(source, /retry_result_delivery/);
  assert.match(source, /request_id:/);
  assert.match(source, /delivery_revision/);
  assert.match(source, /reserved_calls/);
  assert.match(source, /sequence/);
  assert.doesNotMatch(source, /\/run['"`]/);
  const detail = await readFile(new URL('../src/RenewalJobDetail.tsx', import.meta.url), 'utf8');
  assert.match(detail, /<ModelRolePanel/);
  assert.match(detail, /\(translation.attempts \|\| \[\]\).map/);
});
