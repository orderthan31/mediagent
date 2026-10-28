import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
test('fresh job explicitly selects available independent translation and labels each role', () => {
  const s = readFileSync(new URL('../src/ModelRolePanel.tsx', import.meta.url), 'utf8');
  assert.match(s, /available_roles/);
  assert.match(s, /roles:/);
  assert.match(s, /task.role/);
  assert.match(s, /독립 전사·번역/);
});
