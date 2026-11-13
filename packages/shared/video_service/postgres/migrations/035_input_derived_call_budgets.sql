-- New automatic legacy-ledger rows carry a finite input-derived bound.
-- No existing cap, counter, snapshot, command, or audit row is rewritten.
ALTER TABLE model_call_budgets
    ADD COLUMN planned_units integer,
    ADD COLUMN candidate_count integer;
ALTER TABLE model_call_budgets DROP CONSTRAINT model_call_budgets_max_calls_check;
ALTER TABLE model_call_budgets ADD CONSTRAINT model_call_budgets_max_calls_check CHECK (
    (planned_units IS NULL AND candidate_count IS NULL AND max_calls BETWEEN 1 AND 4096)
    OR
    (planned_units IS NOT NULL AND candidate_count IS NOT NULL
     AND planned_units >= 0 AND candidate_count BETWEEN 1 AND 4
     AND max_calls = planned_units * candidate_count)
);
