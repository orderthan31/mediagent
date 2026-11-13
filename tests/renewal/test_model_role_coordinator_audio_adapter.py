"""Offline SQL-adapter regression, NOT a PostgreSQL/product integration test."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
import test_input_derived_budget_execution as budget
from test_audio_original_input import audio_runtime, store, ACTOR
from test_saved_subtitle_translation import mt, state, connected, recovery_runtime, source_execution
from test_model_role_coordinator_fallbacks import EnrollmentBoundary
from mideagent_orchestrator.model_roles import ModelRoleCoordinator


@pytest.mark.parametrize('audio_runtime', [{'max_calls': 'auto'}, {'max_calls': 1}, {'max_calls': 128}], indirect=True)
def test_created_audio_snapshot_auto_enrolls_before_existing_budget_path(audio_runtime, tmp_path, monkeypatch):
    create = budget.create_audio

    def create_and_enroll(state):
        child = create(state)
        runtime = state.runtime
        boundary = EnrollmentBoundary(child)
        execute = runtime.database.execute

        def sql(query, params=()):
            if ('model_role_enrollments' in query
                    or query.startswith('SELECT count(*) n FROM node_runs')
                    or query.startswith('UPDATE jobs SET revision=revision+1')):
                return boundary.execute(query, params)
            return execute(query, params)

        monkeypatch.setattr(runtime.database, 'execute', sql)
        # The fixture's public get lacks runs; expose its actual stored runs.
        def get(owner, job_id):
            assert owner == ACTOR and job_id == child['id']
            return {**deepcopy(child), 'runs': deepcopy(runtime.database.runs[job_id])}

        monkeypatch.setattr(runtime, 'get', get)
        coordinator = ModelRoleCoordinator(runtime, SimpleNamespace(
            model_role_factory=lambda: pytest.fail('no transport/model call allowed')))
        before = deepcopy(child['snapshot'])
        result = coordinator.auto_enroll_new_job(ACTOR, child['id'], 'auto-configured-fallback')
        assert len(boundary.rows) == 1
        assert result['revision'] == 2 and result['runs'] == []
        assert child['snapshot'] == before
        return child

    monkeypatch.setattr(budget, 'create_audio', create_and_enroll)
    budget.test_actual_audio_preview_claim_freeze_enroll_and_snapshot_preservation(audio_runtime, tmp_path)
