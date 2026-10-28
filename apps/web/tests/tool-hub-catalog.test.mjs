import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
test('tool catalog uses the independent protected hub, not workflow node registration', () => {
  const text = fs.readFileSync(new URL('../src/ToolCatalog.tsx', import.meta.url), 'utf8');
  assert.ok(text.includes("'/tool-hub/tools'"));
  assert.ok(text.includes("'/agent-hub/agents'"));
  for (const word of ['node-catalog', 'WorkflowEditor', 'clock_policy', 'wire_version', 'fallback'])
    {assert.ok(!text.includes(word));}
});
