import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('primary workflow start consumes server inspection instead of an executor-type selector', () => {
  const component = readFileSync(new URL('../src/WorkflowStart.tsx', import.meta.url), 'utf8');
  assert.ok(component.includes('/settings/work-entry/inspect'));
  assert.ok(component.includes('aria-label="원본"'));
  assert.ok(component.includes('aria-label="워크플로우"'));
  assert.ok(component.includes('처리 흐름'));
  assert.ok(component.includes('/settings/work-entry/preview'));
  const tickets = readFileSync(new URL('../src/WorkflowTickets.tsx', import.meta.url), 'utf8');
  assert.ok(tickets.includes('plan.model_bindings'));
  assert.ok(tickets.includes('plan.model_admission'));
  assert.ok(!component.includes('aria-label="실행기 유형"'));
});

test('product judgment keeps compact outcome separate from technical evidence', () => {
  const panel = readFileSync(new URL('../src/DecisionPanel.tsx', import.meta.url), 'utf8');
  assert.ok(panel.includes('입력/SHA·adapter·조건 상세'));
  assert.ok(panel.includes('open={!compact}'));
});
