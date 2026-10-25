"""Explicit registered-API workflows must never fall back to an unselected local engine."""

import pytest
from video_service.node_contracts import node_spec
from video_service.postgres.execution import Execution


@pytest.mark.parametrize("kind", ["transcribe", "translate"])
def test_api_source_is_typed_and_does_not_select_engine(kind):
    assert "registered_api" in node_spec(kind)["options"].get("model_source", []), (
        "explicit API-only binding contract missing"
    )
    assert (
        Execution._engine_role(
            {"type": kind, "options": {"model_source": "registered_api"}}
        )
        is None
    )
    assert Execution._engine_role({"type": kind, "options": {}}) == kind


@pytest.mark.parametrize("kind", ["transcribe", "translate"])
def test_unselected_api_model_is_blocked_without_local_resolution(kind):
    runtime = Execution.__new__(Execution)
    runtime.engine_runtime_enabled = True
    reasons = runtime._execution_reasons(
        None,
        {
            "nodes": [
                {
                    "id": "test",
                    "type": kind,
                    "options": {"model_source": "registered_api"},
                }
            ]
        },
        {},
        None,
    )
    assert any("등록 API 모델 선택이 필요" in reason for reason in reasons), reasons
