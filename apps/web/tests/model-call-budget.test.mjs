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

test('automatic budget uses concise copy without computing or mutating a cap', () => {
  const budget = {
    budget_mode: 'input_derived',
    max_calls: null,
    planned_units: null,
    candidate_count: 2,
    budget_source: 'literal source',
  };
  const before = structuredClone(budget);
  assert.equal(modelCallBudgetLabel(budget), '자동');
  assert.deepEqual(budget, before);
  assert.equal(modelCallBudgetLabel({ budget_mode: 'input_derived', max_calls: null }), '자동');
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
  assert.equal(modelCallOptionLabel('auto'), '자동');
});
test('only known zero actual work is rendered as no work; invalid caps never leak', () => {
  assert.equal(
    modelCallBudgetLabel({ budget_mode: 'input_derived', planned_units: 0, max_calls: 0 }),
    '호출 없음',
  );
  for (const max_calls of [undefined, null, NaN, Infinity, 0, -1]) {
    assert.equal(modelCallBudgetLabel({ max_calls }), '확인 불가');
  }
  assert.equal(modelCallBudgetLabel({ budget_mode: 'input_derived', max_calls: 0 }), '자동');
  assert.equal(
    modelCallBudgetLabel({
      budget_mode: 'input_derived',
      max_calls: 12,
      planned_units: 6,
      candidate_count: 2,
    }),
    '자동 · 최대 12회',
  );
});
