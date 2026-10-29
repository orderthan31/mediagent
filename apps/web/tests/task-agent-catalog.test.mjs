import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
test('task-agent identities and progress are presented independently of tools', async () => {
  const path = new URL('../src/agent-hub.mjs', import.meta.url);
  assert.ok(fs.existsSync(path), 'goal-agent navigation and progress are missing');
  const { canonicalAgentIdentity, agentStateLabel } = await import(path.href);
  assert.equal(canonicalAgentIdentity('transcription'), 'transcribe');
  assert.equal(canonicalAgentIdentity('transcribe'), 'transcribe');
  assert.equal(canonicalAgentIdentity('translation'), 'translate');
  assert.equal(canonicalAgentIdentity('extract_audio'), 'extract_audio');
  assert.equal(agentStateLabel('processing'), '처리 중');
  assert.equal(agentStateLabel('unknown'), '확인 필요');
  assert.equal(agentStateLabel('completed'), '완료');
  const ui = fs.readFileSync(new URL('../src/ToolCatalog.tsx', import.meta.url), 'utf8');
  assert.ok(ui.includes('selected.executions'));
  assert.ok(ui.includes('completed_calls'));
  assert.ok(ui.includes('selected.goal'));
});
