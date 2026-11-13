import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const bundle = await build({
  entryPoints: ['src/model-call-budget.ts'],
  bundle: true,
  write: false,
  format: 'esm',
  platform: 'node',
});
const { modelCallBudgetLabel, modelCallOptionLabel } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`
);

test('automatic budget preserves uncertainty, candidates and source without computing a cap', () => {
  const budget = {
    budget_mode: 'input_derived',
    max_calls: null,
    planned_units: null,
    candidate_count: 2,
    budget_source: 'literal source',
  };
  const before = structuredClone(budget);
  assert.equal(
    modelCallBudgetLabel(budget),
    '자동 · 실제 입력 단위 수 × 선택 후보 2개 · 입력 준비 후 유한한 호출 상한 확정',
  );
  assert.deepEqual(budget, before);
  assert.equal(
    modelCallBudgetLabel({ budget_mode: 'input_derived', max_calls: null }),
    '자동 · 실제 입력 단위 수 × 선택 후보 수 · 입력 준비 후 유한한 호출 상한 확정',
  );
  assert.doesNotMatch(
    modelCallBudgetLabel({ budget_mode: 'input_derived', planned_units: 5, candidate_count: 2 }),
    /최대 10회/,
  );
});
test('explicit and historical numeric budgets retain exact caps', () => {
  for (const n of [1, 128]) {
    assert.equal(modelCallBudgetLabel({ max_calls: n }), `최대 ${n}회`);
    assert.equal(modelCallBudgetLabel({ budget_mode: 'explicit', max_calls: n }), `최대 ${n}회`);
    assert.equal(modelCallOptionLabel(String(n)), `최대 ${n}회`);
  }
  assert.match(modelCallOptionLabel('auto'), /^자동 · 실제 입력/);
});
test('only known zero actual work is rendered as no work; invalid caps never leak', () => {
  assert.equal(
    modelCallBudgetLabel({ budget_mode: 'input_derived', planned_units: 0, max_calls: 0 }),
    '자동 · 실제 입력 0개 · 호출 없음 (상한 0회)',
  );
  for (const max_calls of [undefined, null, NaN, Infinity, 0, -1]) {
    assert.equal(modelCallBudgetLabel({ max_calls }), '호출 상한 확인 불가');
  }
  assert.match(
    modelCallBudgetLabel({ budget_mode: 'input_derived', max_calls: 0 }),
    /입력 준비 후/,
  );
  assert.match(
    modelCallBudgetLabel({
      budget_mode: 'input_derived',
      max_calls: 12,
      planned_units: 6,
      candidate_count: 2,
    }),
    /최대 12회/,
  );
});
