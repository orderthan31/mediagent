"""Cycle 2: real recover/create/request methods with memory-only boundaries."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import sys

import pytest

from test_goal_corrections import (
    source_execution, execution_job, translation_graph, unit_reference,
)
from video_service.canonical import canonical, digest
from video_service.goal_outputs import output_stage
from video_service.renewal_contracts import spec


POLICY_FIELDS = (
    "agent_execution_policy", "agent_input_contexts", "agent_output_policy", "agent_output_bindings",
    "agent_plan_version", "agent_definition", "agent_tool_owners", "role_policy_version",
)


class RecoveryDatabase:
    """Captures child INSERTs and accepted reuse rows; no driver or real jobs."""
    def __init__(self, parent):
        self.jobs = {parent["id"]: parent}
        self.runs = {parent["id"]: parent["runs"]}
        self.children = []
        self.outbox = []

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params):
        value = None
        if sql.startswith("SELECT * FROM jobs WHERE owner_id=%s AND creation_request_id"):
            value = next((job for job in self.children if job["owner_id"] == params[0] and job["creation_request_id"] == params[1]), None)
        elif sql.startswith("SELECT pg_advisory_xact_lock"):
            pass
        elif sql.startswith("INSERT INTO jobs"):
            value = dict(owner_id=params[0], id=params[1], asset_id=params[2], workflow_id=params[3],
                         workflow_revision=params[4], snapshot=params[5], snapshot_sha256=params[6],
                         parent_id=params[7], creation_request_id=params[8], creation_sha256=params[9],
                         recovery_ready=params[10], workflow_owner_id=params[11], status="draft", generation=1,
                         active_claim_id=None, cancel_requested=False)
            self.jobs[value["id"]] = value
            self.runs[value["id"]] = []
            self.children.append(value)
        elif sql.startswith("INSERT INTO node_runs"):
            value = dict(owner_id=params[0], job_id=params[1], id=params[2], node_id=params[3],
                         generation=params[5], status=params[6], input_sha256=params[7], settings_sha256=params[8],
                         inputs=params[9], options=params[10], node_type=params[11], request=params[12],
                         request_sha256=params[13], result=None, attempt=1)
            self.runs[params[1]].append(value)
        elif sql.startswith("UPDATE node_runs SET result=%s"):
            value = next(row for row in self.runs[params[2]] if row["id"] == params[3])
            value["result"] = params[0]
        elif sql.startswith("UPDATE jobs SET recovery_ready=true"):
            value = self.jobs[params[1]]
            value["recovery_ready"] = True
        else:
            raise AssertionError("Unexpected SQL boundary: " + sql)
        return SimpleNamespace(fetchone=lambda: value)


def historical_chain():
    from mideagent_orchestrator.workflow import compile_definition
    graph = translation_graph("ko")
    graph["revision"] = 1
    second = deepcopy(graph["nodes"][-1])
    second.update(id="second", options={"target_language": "ko", "llm_options": '{"temperature":0.4}'})
    graph["nodes"].append(second)
    graph["edges"].append({"id": "second_edge", "source": {"node": "translation", "port": "media"},
                           "target": {"node": "second", "port": "media"}})
    compiled = compile_definition(graph)
    parent = execution_job(compiled)
    parent.update(status="failed", asset_id="e" * 32, workflow_id="f" * 32, workflow_revision=1)
    parent["snapshot"].update(agent_plan_version=1, agent_tool_owners=deepcopy(compiled["owners"]),
                              agent_output_bindings=deepcopy(compiled["outputs"]), role_policy_version=2,
                              artifact_layout=1, engine_bindings={}, custom_frozen_policy={"unit": ["preserve"]},
                              version=1, asset={"owner_id": parent["owner_id"], "asset_id": parent["asset_id"], "bytes": 42, "metadata": {}},
                              translation_paid_authorized=False, recovery=None, source_definition_sha256=digest(graph))
    # All accepted receipts are synthetic, linked by real native edges and digests.
    indexed = {}
    for i, node in enumerate(compiled["definition"]["nodes"]):
        inputs = {}
        for edge in compiled["definition"]["edges"]:
            if edge["target"]["node"] != node["id"]:
                continue
            source = edge["source"]
            inputs[edge["target"]["port"]] = (parent["snapshot"]["inputs"][source["port"]] if source["node"] == "$input"
                                                else indexed[source["node"]]["result"]["outputs"][source["port"]])
        request = {"unit": "historically accepted request", "node_id": node["id"], "inputs": deepcopy(inputs)}
        outputs = {}
        for port, kind in spec(node["type"], node["options"])["outputs"].items():
            sha = hashlib.sha256((node["id"] + port).encode()).hexdigest()
            outputs[port] = {**unit_reference(kind), "sha256": sha, "storage_key": "blobs/" + sha}
        row = dict(id=f"{i + 1:032x}", node_id=node["id"], status="completed", generation=1, attempt=1,
                   inputs=deepcopy(inputs), input_sha256=digest(inputs), settings_sha256=digest(node["options"]),
                   request=request, request_sha256=digest(request), result={"outputs": outputs, "unit_receipt": [node["id"]]})
        indexed[node["id"]] = row
    indexed["second__translate"].update(status="failed", result=None)
    parent["runs"] = list(indexed.values())
    return graph, parent


@pytest.fixture
def recovery_runtime(source_execution, monkeypatch):
    def build(graph, parent):
        runtime = source_execution(parent)
        db = RecoveryDatabase(parent)
        runtime.database = db
        runtime._job = lambda db, owner, identity, **kwargs: db.jobs[identity]
        runtime._runs = lambda db, owner, identity: db.runs[identity]
        runtime._view = lambda db, row: {**deepcopy(row), "runs": deepcopy(db.runs[row["id"]])}
        runtime.get = lambda owner, identity: runtime._view(db, db.jobs[identity])
        reference = unit_reference("video")
        asset = {"owner_id": parent["owner_id"], "asset_id": parent["asset_id"], "bytes": reference["bytes"], "metadata": {}}
        runtime._shared_asset = lambda *args: deepcopy(asset)
        runtime.asset_reference = lambda *args: deepcopy(reference)
        runtime._job_definition = lambda *args: (parent["owner_id"], deepcopy(graph))
        # Current registry is deliberately different. The real pinned-binding helper must preserve history.
        fresh = deepcopy(parent["snapshot"]["model_bindings"])
        for binding in fresh.values():
            binding["revision"] += 100
            binding["fallbacks"].reverse()
        runtime._bindings = lambda *args, **kwargs: deepcopy(fresh)
        runtime._engine_bindings = lambda *args: {}
        runtime.store = SimpleNamespace(path=lambda *args: None)
        runtime.reused_stages = []
        def capture(db, job, row, receipt):
            runtime.reused_stages.extend((row["node_id"], port, output_stage(job["snapshot"], row["node_id"], port))
                                         for port in receipt["outputs"])
            return deepcopy(receipt)
        runtime.ticket_artifacts = SimpleNamespace(capture=capture)
        monkeypatch.setattr(sys.modules["video_service.postgres.subtitle_tracks"], "selected", lambda snapshot: False, raising=False)
        review = sys.modules["video_service.postgres.job_processing_review"].JobProcessingReview
        monkeypatch.setattr(review, "blocked_in", lambda *args: False, raising=False)
        parent["snapshot_sha256"] = digest(parent["snapshot"])
        return runtime
    return build


def incomplete_command(runtime, job):
    node = next(n for n in job["snapshot"]["definition"]["nodes"] if n["id"] == "second__translate")
    old = runtime.database.jobs[next(iter(runtime.database.jobs))]["runs"][-1]
    _, command = runtime._insert_run(runtime.database, job, node, deepcopy(old["inputs"]), "running")
    return command


def test_real_historical_recover_create_preserves_absent_policy_and_incomplete_command(recovery_runtime):
    graph, parent = historical_chain()
    for field in POLICY_FIELDS:
        parent["snapshot"].pop(field, None)
    baseline_parent = deepcopy(parent)
    baseline = recovery_runtime(graph, baseline_parent)
    old_command = incomplete_command(baseline, baseline_parent)
    runtime = recovery_runtime(graph, parent)
    before = canonical(parent)
    child = runtime.recover(parent["owner_id"], parent["id"], "cycle2-historical", acknowledge_duplicate_risk=True)
    command = incomplete_command(runtime, child)
    assert command["translation"]["source_language"] == "ja", "recovery must not adopt regenerated ko input policy"
    old_command.update(run_id=command["run_id"], attempt_id=command["attempt_id"])
    assert command == old_command
    assert all(field not in child["snapshot"] for field in POLICY_FIELDS)
    assert child["snapshot"]["inputs"] == parent["snapshot"]["inputs"]
    for node_id, port, stage in runtime.reused_stages:
        assert stage == output_stage(parent["snapshot"], node_id, port)
    assert canonical(parent) == before


def test_new_non_recovery_create_freezes_v2_role_policy(recovery_runtime):
    graph, parent = historical_chain()
    runtime = recovery_runtime(graph, parent)
    child = runtime.create(parent["owner_id"], parent["asset_id"], parent["workflow_id"], 1,
                           request_id="cycle2-new", options=deepcopy(parent["snapshot"]["options"]))
    assert type(child["snapshot"].get("role_policy_version")) is int
    assert child["snapshot"]["role_policy_version"] == 2


@pytest.mark.parametrize("missing", [None, *POLICY_FIELDS])
def test_recover_preserves_each_policy_presence_value_and_parent_bytes(recovery_runtime, missing):
    graph, parent = historical_chain()
    if missing:
        parent["snapshot"].pop(missing)
    baseline_parent = deepcopy(parent)
    baseline = recovery_runtime(graph, baseline_parent)
    expected_error = None
    try:
        expected_command = incomplete_command(baseline, baseline_parent)
    except ValueError as exc:
        expected_error = str(exc)
    runtime = recovery_runtime(graph, parent)
    before = canonical(parent)
    child = runtime.recover(parent["owner_id"], parent["id"], "cycle2-field-" + str(missing), acknowledge_duplicate_risk=True)
    expected = deepcopy(parent["snapshot"])
    expected["recovery"] = {"parent_id": parent["id"], "snapshot_sha256": parent["snapshot_sha256"]}
    assert child["snapshot"] == expected, "field absence is part of the frozen contract"
    assert child["snapshot_sha256"] == digest(expected)
    assert canonical(parent) == before
    accepted = [run for run in parent["runs"] if run["status"] == "completed"]
    assert len(child["runs"]) == len(accepted)
    for reused, original in zip(child["runs"], accepted):
        assert {k: v for k, v in reused["result"].items() if k != "reused_from"} == original["result"]
    assert all(stage == output_stage(parent["snapshot"], node, port) for node, port, stage in runtime.reused_stages)
    if expected_error is not None:
        # An incomplete old policy is not silently repaired by a recovery.
        with pytest.raises(ValueError) as exc:
            incomplete_command(runtime, child)
        assert str(exc.value) == expected_error
    else:
        actual = incomplete_command(runtime, child)
        expected_command.update(run_id=actual["run_id"], attempt_id=actual["attempt_id"])
        assert actual == expected_command
    # Mutating a stored child must not alias the parent, including opaque policy metadata.
    runtime.database.children[0]["snapshot"]["custom_frozen_policy"]["unit"].append("child")
    assert canonical(parent) == before


@pytest.mark.parametrize("role_version", [None, 1, 2])
def test_real_recovery_retains_role_policy_version_and_model_candidate_order(recovery_runtime, role_version):
    graph, parent = historical_chain()
    if role_version is None:
        parent["snapshot"].pop("role_policy_version")
    else:
        parent["snapshot"]["role_policy_version"] = role_version
    node = parent["snapshot"]["definition"]["nodes"][-1]
    pin = parent["snapshot"]["model_bindings"][node["id"]]
    pin["fallbacks"].append({"model_id": "9" * 32, "revision": 8})
    runtime = recovery_runtime(graph, parent)
    before = canonical(parent)
    child = runtime.recover(parent["owner_id"], parent["id"], "cycle2-role-" + str(role_version), acknowledge_duplicate_risk=True)
    assert ("role_policy_version" in child["snapshot"]) == (role_version is not None)
    if role_version is not None:
        assert type(child["snapshot"]["role_policy_version"]) is int
        assert child["snapshot"]["role_policy_version"] == role_version
    command = incomplete_command(runtime, child)
    assert command["translation"]["source_language"] == "ko"
    assert command["translation"]["candidates"] == [pin, *pin["fallbacks"]]
    assert command["options"] == node["options"]
    assert command["options"]["llm_options"] == '{"temperature":0.4}'
    assert canonical(parent) == before


def test_recovery_recompile_difference_is_rejected_before_child_insert(recovery_runtime):
    graph, parent = historical_chain()
    graph["nodes"][1]["options"]["llm_options"] = '{"temperature":0.9}'
    runtime = recovery_runtime(graph, parent)
    runtime._bindings = lambda *args, **kwargs: deepcopy(parent["snapshot"]["model_bindings"])
    before = canonical(parent)
    with pytest.raises(ValueError, match="복구|recovery"):
        runtime.recover(parent["owner_id"], parent["id"], "cycle2-mismatch", acknowledge_duplicate_risk=True)
    assert runtime.database.children == [] and runtime.database.outbox == []
    assert canonical(parent) == before


@pytest.mark.parametrize("field,value", [
    ("agent_execution_policy", 0), ("agent_output_policy", 0), ("agent_plan_version", 2),
    ("agent_input_contexts", {"translation__translate": {"transcript": {"node": "transcription__transcribe", "port": "transcript", "language": "ja"}},
                              "second__translate": {"transcript": {"node": "translation__translate", "port": "transcript", "language": "en"}}}),
    ("agent_output_bindings", {"translation": {"transcript": {"node": "translation__translate", "port": "transcript"}}}),
])
def test_recovery_preserves_present_values_instead_of_compiler_defaults(recovery_runtime, field, value):
    graph, parent = historical_chain()
    parent["snapshot"][field] = deepcopy(value)
    baseline_parent = deepcopy(parent)
    baseline = recovery_runtime(graph, baseline_parent)
    expected_command = incomplete_command(baseline, baseline_parent)
    runtime = recovery_runtime(graph, parent)
    before = canonical(parent)
    child = runtime.recover(parent["owner_id"], parent["id"], "cycle2-value-" + field, acknowledge_duplicate_risk=True)
    assert child["snapshot"][field] == value
    actual = incomplete_command(runtime, child)
    expected_command.update(run_id=actual["run_id"], attempt_id=actual["attempt_id"])
    assert actual == expected_command
    assert all(stage == output_stage(parent["snapshot"], node, port) for node, port, stage in runtime.reused_stages)
    assert canonical(parent) == before


def test_recovery_preserves_pinned_input_origin_and_is_idempotent(recovery_runtime):
    graph, parent = historical_chain()
    parent["snapshot"]["inputs"]["video"]["source_owner_id"] = "e" * 32
    for run in parent["runs"]:
        if "video" in run["inputs"]:
            run["inputs"]["video"]["source_owner_id"] = "e" * 32
            run["input_sha256"] = digest(run["inputs"])
            run["request"]["inputs"] = deepcopy(run["inputs"])
            run["request_sha256"] = digest(run["request"])
    runtime = recovery_runtime(graph, parent)
    before = canonical(parent)
    child = runtime.recover(parent["owner_id"], parent["id"], "cycle2-input", acknowledge_duplicate_risk=True)
    assert child["snapshot"]["inputs"] == parent["snapshot"]["inputs"]
    assert child["snapshot"]["inputs"]["video"]["source_owner_id"] == "e" * 32
    second = runtime.recover(parent["owner_id"], parent["id"], "cycle2-input", acknowledge_duplicate_risk=True)
    assert second == child and len(runtime.database.children) == 1
    assert canonical(parent) == before


@pytest.mark.parametrize("change", ["native_bytes", "options"])
def test_recovery_requires_exact_canonical_definition_and_options(recovery_runtime, change):
    graph, parent = historical_chain()
    if change == "native_bytes":
        # Numerically equal positions must not hide a changed canonical native snapshot.
        parent["snapshot"]["definition"]["nodes"][0]["position"]["x"] = 0.0
    else:
        parent["snapshot"]["options"]["target_language"] = "en"
    runtime = recovery_runtime(graph, parent)
    before = canonical(parent)
    with pytest.raises(ValueError):
        runtime.recover(parent["owner_id"], parent["id"], "cycle2-exact-" + change, acknowledge_duplicate_risk=True)
    assert runtime.database.children == [] and canonical(parent) == before


@pytest.mark.parametrize("catalog_version", [1, 2])
def test_new_media_only_job_also_gets_internal_v2_policy(recovery_runtime, catalog_version):
    from test_goal_corrections import media_graph
    from mideagent_orchestrator.workflow import compile_definition
    _, parent = historical_chain()
    graph = media_graph("video_conversion_agent")
    graph["revision"] = 1
    if catalog_version == 1:
        graph = compile_definition(graph)["definition"]
    runtime = recovery_runtime(graph, parent)
    runtime._bindings = lambda *args, **kwargs: {}
    child = runtime.create(parent["owner_id"], parent["asset_id"], parent["workflow_id"], 1,
                           request_id="cycle2-media-" + str(catalog_version), options={})
    assert child["snapshot"]["role_policy_version"] == 2
    assert type(child["snapshot"]["role_policy_version"]) is int
    assert child["snapshot"]["model_bindings"] == {}
    assert child["status"] == "draft" and child["runs"] == [] and runtime.database.outbox == []
