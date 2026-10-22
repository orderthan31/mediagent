import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('recovery copy distinguishes no request from an unresolved request', async () => {
  const source = await readFile(
    new URL('../src/ControlRecoveryPanel.tsx', import.meta.url),
    'utf8',
  );
  assert.ok(source.includes('복구할 요청 없음'));
  assert.ok(!source.includes('현재 미확정 요청 없음'));
  assert.match(source, /status\.request_id\s*\?/);
  assert.ok(source.includes('<code>{status.request_id}</code>'));
});
