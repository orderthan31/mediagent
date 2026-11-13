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
      return '자동 · 실제 입력 0개 · 호출 없음 (상한 0회)';
    }
    const candidates = positiveCount(budget.candidate_count)
      ? `선택 후보 ${budget.candidate_count}개`
      : '선택 후보 수';
    const cap = positiveCount(budget.max_calls)
      ? `최대 ${budget.max_calls}회`
      : '입력 준비 후 유한한 호출 상한 확정';
    return `자동 · 실제 입력 단위 수 × ${candidates} · ${cap}`;
  }
  return positiveCount(budget.max_calls) ? `최대 ${budget.max_calls}회` : '호출 상한 확인 불가';
};

export const modelCallOptionLabel = (value: string | undefined): string =>
  modelCallBudgetLabel(
    value === 'auto'
      ? { budget_mode: 'input_derived' }
      : { max_calls: value && /^[1-9]\d*$/.test(value) ? Number(value) : null },
  );
