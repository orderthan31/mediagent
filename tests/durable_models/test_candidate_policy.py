import pytest

from video_service.role_policy import snapshot_version


@pytest.mark.parametrize("value", [None, 1, 3, True, False, "2", 2.0, [], {}])
def test_only_exact_frozen_integer_two_selects_v2(value):
    assert snapshot_version({"role_policy_version": value}) == 1
    assert snapshot_version({}) == 1
    assert snapshot_version({"role_policy_version": 2}) == 2


def test_ordered_candidate_chain_accepts_only_definitive_matching_predecessors():
    from video_service.role_policy import attempt_index, validate_predecessors

    assert attempt_index(7, 1, 3) == 22
    models = [{"model_id": "A"}, {"model_id": "B"}, {"model_id": "C"}]
    first = {"chunk_index": 6, "input_sha256": "source", "model": models[0], "status": "failed", "error_code": "unavailable"}
    validate_predecessors([first], 2, 1, models, "source")
    second = {**first, "chunk_index": 7, "model": models[1], "error_code": "invalid_response"}
    validate_predecessors([first, second], 2, 2, models, "source")
    for code in ["rate_limited", "upstream_failure", "invalid_response", "unavailable"]:
        validate_predecessors([{**first, "error_code": code}], 2, 1, models, "source")
    validate_predecessors([], 2, 0, models, "source")
    for status in ["started", "unknown", "completed"]:
        with pytest.raises(ValueError):
            validate_predecessors([{**first, "status": status}], 2, 1, models, "source")
    for code in ["auth", "rejected", "cancelled", "outcome_unknown"]:
        with pytest.raises(ValueError):
            validate_predecessors([{**first, "error_code": code}], 2, 1, models, "source")
    for history in [[], [first], [{**first, "input_sha256": "tamper"}], [{**first, "model": models[1]}]]:
        with pytest.raises(ValueError):
            validate_predecessors(history, 2, 2, models, "source")
    with pytest.raises(ValueError):
        validate_predecessors([{**first, "status": "completed"}], 2, 0, models, "source")
