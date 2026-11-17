export type ModelCallBudget = {
  budget_mode?: 'input_derived' | 'explicit';
  max_calls?: number | null;
  planned_units?: number | null;
  candidate_count?: number | null;
};

const positiveCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;

export const modelCallBudgetLabel = (budget: ModelCallBudget): string => {
  if (budget.budget_mode === 'input_derived') {
    if (budget.planned_units === 0 && budget.max_calls === 0) {
      return '호출 없음';
    }
    return positiveCount(budget.max_calls) ? `자동 · 최대 ${budget.max_calls}회` : '자동';
  }
  return positiveCount(budget.max_calls) ? `최대 ${budget.max_calls}회` : '확인 불가';
};

export const modelCallOptionLabel = (value: string | undefined): string =>
  modelCallBudgetLabel(
    value === 'auto'
      ? { budget_mode: 'input_derived' }
      : { max_calls: value && /^[1-9]\d*$/.test(value) ? Number(value) : null },
  );
