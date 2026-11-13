"""Execution defaults must not silently expand workflow-selected call budgets."""

from copy import deepcopy

import pytest

from video_service.editor_contracts import resolve_editor_contracts


@pytest.mark.parametrize("role", ["transcribe", "translate", "vocalize"])
@pytest.mark.parametrize("maximum", ["1", "7"])
def test_missing_batch_policy_preserves_explicit_call_budget(role, maximum):
    definition = {
        "nodes": [
            {"id": "selected", "type": role, "options": {"max_model_calls": maximum}}
        ]
    }
    original = deepcopy(definition)

    resolved = resolve_editor_contracts(definition)

    assert resolved["nodes"][0]["options"]["max_model_calls"] == maximum
    assert "batch_policy" in resolved["nodes"][0]["options"]
    assert definition == original


@pytest.mark.parametrize(
    ("role", "maximum"),
    [("transcribe", "128"), ("translate", "128"), ("vocalize", "4096")],
)
def test_unselected_call_budget_keeps_existing_execution_default(role, maximum):
    definition = {"nodes": [{"id": "selected", "type": role, "options": {}}]}

    resolved = resolve_editor_contracts(definition)

    assert resolved["nodes"][0]["options"]["max_model_calls"] == maximum
    assert definition["nodes"][0]["options"] == {}


@pytest.mark.parametrize("role", ["transcribe", "translate", "vocalize"])
def test_explicit_batch_contract_and_call_budget_remain_pinned(role):
    definition = {
        "nodes": [
            {
                "id": "selected",
                "type": role,
                "options": {"batch_policy": "existing_pinned_contract", "max_model_calls": "1"},
            }
        ]
    }

    resolved = resolve_editor_contracts(definition)

    assert resolved == definition


def test_public_control_graph_freezes_explicit_budgets_without_batch_presets():
    from test_agent_control_workflow import edge, graph, node
    from mideagent_orchestrator.workflow import compile_definition

    selected = {"model_id": "a" * 32, "revision": 1}
    speech = {
        **node("speech", "transcription_agent"),
        "model_ref": selected,
        "tool_settings": {"transcribe": {"max_model_calls": "1"}},
    }
    translation = {
        **node("translation", "translation_agent"),
        "model_ref": selected,
        "tool_settings": {"translate": {"max_model_calls": "1"}},
    }
    definition = graph(
        [speech, translation, node("approval", "review", data_type="transcript")],
        [
            edge("speech", "transcript", "translation", "transcript"),
            edge("translation", "transcript", "approval", "value"),
        ],
    )

    compiled = compile_definition(definition, input_language="en")

    budgets = {
        item["type"]: item["options"]["max_model_calls"]
        for item in compiled["definition"]["nodes"]
        if item["type"] in {"transcribe", "translate"}
    }
    assert budgets == {"transcribe": "1", "translate": "1"}
