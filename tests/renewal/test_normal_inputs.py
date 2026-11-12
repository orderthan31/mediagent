"""Normal input unit specimens only; no product input, database or model calls."""
from copy import deepcopy
import io
import sys
from pathlib import Path
import wave
from tempfile import TemporaryDirectory

import pytest
from test_goal_corrections import source_execution
from test_goal_recovery_policy import recovery_runtime, historical_chain

ROOT = Path(__file__).resolve().parents[2]
for project in ("packages/shared", "agents", "apps/orchestrator", "apps/api"):
    sys.path.insert(0, str(ROOT / project))


@pytest.fixture
def tmp_path():
    # Owned temporary unit CAS only; never use a product storage root.
    with TemporaryDirectory(prefix="mediagent-normal-unit-") as folder:
        yield Path(folder)


def input_graph(kind="subtitle_file_agent", *, translated=False, audio=False):
    nodes = []
    if translated:
        nodes.append({"id": "mt", "type": "translation_agent", "options": {"target_language": "pt-BR", "llm_options": '{"temperature":0.2}'},
                      "model_ref": {"model_id": "1" * 32, "revision": 7}, "position": {"x": 0, "y": 0}})
    nodes.append({"id": "goal", "type": kind, "options": {"audio_source": "selected_audio"} if audio else {}, "position": {"x": 0, "y": 0}})
    if kind == "transcription_agent":
        nodes[-1]["model_ref"] = {"model_id": "2" * 32, "revision": 8}
    return {"catalog_version": 2, "revision": 1, "name": "unit selected inputs", "inputs": {"audio": "audio"} if audio else {"transcript": "transcript"},
            "nodes": nodes, "edges": [{"id": "flow", "source": {"node": "mt", "port": "media"}, "target": {"node": "goal", "port": "media"}}] if translated else []}


@pytest.mark.parametrize("kind,roles", [("subtitle_file_agent", ["generate_subtitle"]),
                                      ("subtitle_video_agent", ["generate_subtitle", "encode", "validate_video"])])
def test_public_timed_input_root_compiles_without_models_or_transcription(kind, roles):
    from mideagent_orchestrator.workflow import compile_definition
    graph = input_graph(kind)
    before = deepcopy(graph)
    compiled = compile_definition(graph)
    assert [n["type"] for n in compiled["definition"]["nodes"]] == roles
    assert compiled["definition"]["inputs"] == {"video": "video", "transcript": "transcript"}
    assert all("model_ref" not in n for n in compiled["definition"]["nodes"])
    assert graph == before


def test_selected_audio_scope_and_lifecycle_have_no_phantom_extraction():
    from mideagent_orchestrator.workflow import compile_definition, scope_snapshot, ready_tool_ids
    from mideagent_orchestrator.agent_view import project_agents
    from test_workflow_generality import accepted_unit_runs
    compiled = compile_definition(input_graph("transcription_agent", audio=True))
    assert [n["type"] for n in compiled["definition"]["nodes"]] == ["analyze", "preprocess_audio", "transcribe"]
    assert set(scope_snapshot(compiled)["bindings"]["goal"]) == {"analyze", "preprocess_audio", "transcribe"}
    edges = compiled["definition"]["edges"]
    assert any(e["source"] == {"node": "$input", "port": "audio"} and e["target"]["node"] == "goal__preprocess_audio" for e in edges)
    assert any(e["source"] == {"node": "goal__preprocess_audio", "port": "timeline"} and e["target"]["node"] == "goal__transcribe" for e in edges)
    runs = accepted_unit_runs(compiled)
    view = project_agents({"snapshot": compiled, "status": "completed"}, runs, [], [])
    assert view["nodes"][0]["state"] == "completed" and len(view["nodes"][0]["tools"]) == 3
    assert ready_tool_ids(compiled, {r["node_id"]: r for r in runs}) == set()
    from mideagent_agents.registry import registration
    selected = registration("transcription_agent", node=compiled["agent_definition"]["nodes"][0])
    assert selected["runtime_roles"] == ["analyze", "preprocess_audio", "transcription"]
    assert "media.extract_audio" not in selected["allowed_tools"]
    assert registration("transcription_agent")["runtime_roles"] == ["analyze", "extract_audio", "preprocess_audio", "transcription"]


def test_audio_profile_keeps_saved_inactive_extraction_settings_without_executing_them():
    from mideagent_orchestrator.workflow import compile_definition
    graph = input_graph("transcription_agent", audio=True)
    graph["nodes"][0]["tool_settings"] = {"extract_audio": {}}
    compiled = compile_definition(graph)
    assert "extract_audio" not in {n["type"] for n in compiled["definition"]["nodes"]}
    assert compiled["agent_definition"] == graph


SRT = "007\n00:00:00,250 --> 00:00:01,125\n literal text \nsecond line\n"
ROWS = [{"id": "007", "start": 0.25, "end": 1.125, "text": " literal text \nsecond line"}]


def test_srt_resolution_is_bounded_literal_read_only_and_token_sensitive():
    from mideagent_orchestrator.normal_inputs import NormalInputs
    from video_service.canonical import digest
    from types import SimpleNamespace
    writes = []
    runtime = SimpleNamespace(store=SimpleNamespace(put=lambda *args: writes.append(args)))
    resolver = NormalInputs(runtime)
    first = resolver.resolve(None, "c" * 32, {}, input_graph(), {"subtitle_srt": SRT, "input_language": "ja"})
    assert first["segments"] == ROWS and first["language"] == "ja" and writes == []
    assert first["bindings"]["transcript"]["content_sha256"] == digest(ROWS)
    other = resolver.resolve(None, "c" * 32, {}, input_graph(), {"subtitle_srt": SRT.replace("literal", "other"), "input_language": "ja"})
    assert digest(first["bindings"]) != digest(other["bindings"])


@pytest.mark.parametrize("value", ["plain untimed text", "1\n00:00:02,000 --> 00:00:01,000\nx", SRT + SRT,
                                  "1\n00:99:00,000 --> 01:00:00,000\nx", "x" * 17000])
def test_invalid_srt_is_refused_before_materialization(value):
    from mideagent_orchestrator.normal_inputs import NormalInputs
    from types import SimpleNamespace
    runtime = SimpleNamespace(store=SimpleNamespace(put=lambda *args: pytest.fail("preview must not write")))
    with pytest.raises(ValueError):
        NormalInputs(runtime).resolve(None, "c" * 32, {}, input_graph(), {"subtitle_srt": value})


@pytest.fixture
def accepted_inputs(tmp_path):
    from types import SimpleNamespace
    from video_service.content_store import ContentStore
    from video_service.canonical import canonical, digest
    # Windows cannot unlink ContentStore.put's readonly staging hardlink. The
    # write boundary is synthetic; native path/read integrity checks stay real.
    class UnitStore(ContentStore):
        def put(self, owner, blocks, kind):
            import hashlib
            raw = b"".join(blocks)
            sha = hashlib.sha256(raw).hexdigest()
            root = self.owner_root(owner) / "blobs"
            root.mkdir(exist_ok=True)
            (root / sha).write_bytes(raw)
            return {"storage_key": "blobs/" + sha, "sha256": sha, "bytes": len(raw), "type": kind}
    store = UnitStore(tmp_path)
    owner, actor, asset_id = "b" * 32, "c" * 32, "a" * 32
    video = store.put(owner, [b"unit video descriptor only"], "video")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b"\0\0" * 32000)
    refs = {"audio": store.put(owner, [buffer.getvalue()], "audio"),
            "transcript": store.put(owner, [canonical(ROWS)], "transcript")}
    nodes = [{"id": "extract", "type": "extract_audio", "options": {}},
             {"id": "speech", "type": "transcribe", "options": {"source_language": "ja"}}]
    snapshot = {"definition": {"nodes": nodes, "edges": [{"source": {"node": "$input", "port": "video"}, "target": {"node": "extract", "port": "video"}}]}, "inputs": {"video": video}, "options": {"source_language": "ja"}}
    job = {"id": "d" * 32, "owner_id": owner, "asset_id": asset_id, "status": "completed", "library_removed_at": None,
           "snapshot": snapshot, "snapshot_sha256": digest(snapshot), "ticket_number": 1}
    runs = [{"id": "e" * 32, "node_id": "extract", "status": "completed", "inputs": {"video": video}, "result": {"outputs": {"audio": refs["audio"]}}},
            {"id": "f" * 32, "node_id": "speech", "status": "completed", "result": {"outputs": {"transcript": refs["transcript"]}}}]
    manifest_reads = []
    runtime = SimpleNamespace(store=store, _shared_job=lambda db, identity: job, _runs=lambda *args: runs,
                              asset_reference=lambda asset: video,
                              ticket_artifacts=SimpleNamespace(read=lambda *args: manifest_reads.append(args)))
    asset = {"id": asset_id, "asset_id": asset_id, "owner_id": owner}
    return SimpleNamespace(runtime=runtime, job=job, runs=runs, actor=actor, asset=asset, refs=refs, manifest_reads=manifest_reads)


@pytest.mark.parametrize("port", ["transcript", "audio"])
def test_accepted_inputs_pin_exact_producer_and_custodian(accepted_inputs, port):
    from mideagent_orchestrator.normal_inputs import NormalInputs
    state = accepted_inputs
    index = 1 if port == "transcript" else 0
    selector = {"job_id": state.job["id"], "run_id": state.runs[index]["id"], "port": port}
    graph = input_graph() if port == "transcript" else input_graph("transcription_agent", audio=True)
    result = NormalInputs(state.runtime).resolve(None, state.actor, state.asset, graph, {"accepted_inputs": {port: selector}})
    pin = result["bindings"][port]
    assert {key: pin[key] for key in selector} == selector
    assert pin["reference"] == state.refs[port] and state.manifest_reads
    assert result["references"][port]["source_owner_id"] == state.job["owner_id"]
    if port == "transcript":
        assert result["language"] == "ja"


@pytest.mark.parametrize("bad", ["wrong_video", "failed", "unknown", "removed", "preprocessed", "missing", "private_key", "manifest", "expired"])
def test_accepted_audio_rejects_invalid_or_unavailable_sources(accepted_inputs, bad):
    from mideagent_orchestrator.normal_inputs import NormalInputs
    state = accepted_inputs
    selector = {"job_id": state.job["id"], "run_id": state.runs[0]["id"], "port": "audio"}
    if bad == "wrong_video": state.job["asset_id"] = "9" * 32
    elif bad in {"failed", "unknown"}: state.runs[0]["status"] = bad
    elif bad == "removed": state.job["library_removed_at"] = "unit removal"
    elif bad == "preprocessed": state.job["snapshot"]["definition"]["nodes"][0]["type"] = "preprocess_audio"
    elif bad == "missing": state.runs[0]["result"]["outputs"] = {}
    elif bad == "private_key": selector["storage_key"] = "untrusted/client/path"
    elif bad == "manifest":
        def fail(*args): raise ValueError("unit invalid manifest")
        state.runtime.ticket_artifacts.read = fail
    else: state.runtime.store.path(state.job["owner_id"], state.refs["audio"]).unlink()
    with pytest.raises((ValueError, LookupError)):
        NormalInputs(state.runtime).resolve(None, state.actor, state.asset, input_graph("transcription_agent", audio=True), {"accepted_inputs": {"audio": selector}})


@pytest.mark.parametrize("translated", [False, True])
def test_real_create_materializes_selected_srt_and_freezes_actual_command_language(recovery_runtime, translated):
    from video_service.canonical import canonical
    from mideagent_orchestrator.workflow import compile_definition
    from types import SimpleNamespace
    graph = input_graph(translated=translated)
    _, unit_parent = historical_chain()
    runtime = recovery_runtime(graph, unit_parent)
    writes = []
    def put(actor, blocks, kind):
        import hashlib
        raw = b"".join(blocks); sha = hashlib.sha256(raw).hexdigest()
        writes.append(raw)
        return {"storage_key": "blobs/" + sha, "sha256": sha, "bytes": len(raw), "type": kind}
    runtime.store = SimpleNamespace(path=lambda *args: None, put=put)
    pins = {"mt__translate": {"model_id": "1" * 32, "revision": 7, "fallbacks": []}} if translated else {}
    runtime._bindings = lambda *args, **kwargs: deepcopy(pins)
    child = runtime.create(unit_parent["owner_id"], unit_parent["asset_id"], unit_parent["workflow_id"], 1,
                           request_id="normal-srt-" + str(translated), options={"subtitle_srt": SRT, "input_language": "ja"})
    snapshot = child["snapshot"]
    assert writes == [canonical(ROWS)]
    assert snapshot["inputs"]["transcript"]["type"] == "transcript"
    assert snapshot["normal_input_bindings"]["transcript"]["language"] == "ja"
    assert all(n["type"] not in {"transcribe", "extract_audio"} for n in snapshot["definition"]["nodes"])
    assert snapshot["model_bindings"] == pins
    if translated:
        node = next(n for n in snapshot["definition"]["nodes"] if n["type"] == "translate")
        _, command = runtime._insert_run(runtime.database, child, node, {"transcript": snapshot["inputs"]["transcript"]}, "running")
        assert command["translation"]["source_language"] == "ja" and command["translation"]["target_language"] == "pt-BR"
        assert command["translation"]["candidates"] == [pins[node["id"]]]
        assert command["options"]["llm_options"] == '{"temperature":0.2}'


def mount_actual_input_handlers(runtime):
    """Load the real strict request models and real route closures without an app/server."""
    import ast
    from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
    from fastapi import HTTPException
    from video_service.canonical import digest
    body_tree = ast.parse((ROOT / "apps/api/app/renewal.py").read_text(encoding="utf-8"))
    body = next(n for n in body_tree.body if isinstance(n, ast.ClassDef) and n.name == "Body")
    tree = ast.parse((ROOT / "apps/api/app/renewal_routes.py").read_text(encoding="utf-8"))
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in {"Selection", "Create"}]
    mount = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "mount_runtime")
    functions = [deepcopy(n) for n in mount.body if isinstance(n, ast.FunctionDef) and n.name in {"selection_plan", "preview", "create", "input_choices"}]
    for function in functions:
        function.decorator_list = []
        function.args.defaults = []
    namespace = dict(__name__="normal_input_routes_unit", BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
                     StrictBool=StrictBool, StrictInt=StrictInt, HTTPException=HTTPException, Conflict=ValueError,
                     runtime=runtime, digest=digest, local_execution=True, broker_factory=None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[body, *classes, *functions], type_ignores=[])), "actual-normal-input-handlers", "exec"), namespace)
    return namespace


@pytest.fixture
def inline_runtime(recovery_runtime):
    from types import SimpleNamespace
    import hashlib
    graph = input_graph()
    _, unit_parent = historical_chain()
    runtime = recovery_runtime(graph, unit_parent)
    runtime._bindings = lambda *args, **kwargs: {}
    runtime._execution_reasons = lambda *args, **kwargs: []
    runtime.job_definition = lambda *args: deepcopy(graph)
    runtime.asset = lambda *args: {"size_bytes": 42, "content_verified": True, "media": {"duration": 2}, "asset_id": unit_parent["asset_id"]}
    runtime.asset_path = lambda *args: None
    runtime.transcription_runtime = runtime.translation_runtime = runtime.vocalization_runtime = None
    runtime._shared_view = lambda job, actor: job
    writes = []
    def put(actor, blocks, kind):
        raw = b"".join(blocks); sha = hashlib.sha256(raw).hexdigest(); writes.append(raw)
        return {"storage_key": "blobs/" + sha, "sha256": sha, "bytes": len(raw), "type": kind}
    runtime.store = SimpleNamespace(path=lambda *args: None, put=put)
    return runtime, unit_parent, graph, writes


def test_actual_preview_then_create_pins_srt_and_pure_export_needs_no_model(inline_runtime):
    from video_service.canonical import digest
    runtime, parent, graph, writes = inline_runtime
    handlers = mount_actual_input_handlers(runtime)
    selection = handlers["Selection"](asset_id=parent["asset_id"], definition_id=parent["workflow_id"], definition_revision=1,
                                      options={"subtitle_srt": SRT, "input_language": "ja"})
    plan = handlers["preview"](selection, parent["owner_id"])
    assert plan["paid_roles"] == [] and plan["selected_inputs"][0]["segments"] == 1
    assert writes == [] and runtime.database.children == []
    assert "storage_key" not in repr(plan) and "custodian_id" not in repr(plan)
    child = handlers["create"](handlers["Create"](**selection.model_dump(), token=plan["token"], request_id="normal-handler"), parent["owner_id"])
    assert len(writes) == 1 and child["snapshot"]["normal_input_policy"] == 1
    assert digest(child["snapshot"]["definition"]) == plan["execution_definition_sha256"]
    assert child["snapshot"]["model_bindings"] == {}
    assert [n["type"] for n in child["snapshot"]["definition"]["nodes"]] == ["generate_subtitle"]
    assert runtime.database.outbox == []
    public = runtime.__class__._shared_view(child, parent["owner_id"])
    assert public["selected_inputs"] == [{"input": "transcript", "kind": "subtitle_srt", "language": "ja", "segments": 1}]
    assert "reference" not in repr(public["selected_inputs"]) and "custodian" not in repr(public["selected_inputs"])


def test_actual_handler_refuses_changed_srt_before_create(inline_runtime):
    runtime, parent, graph, writes = inline_runtime
    handlers = mount_actual_input_handlers(runtime)
    args = dict(asset_id=parent["asset_id"], definition_id=parent["workflow_id"], definition_revision=1)
    plan = handlers["preview"](handlers["Selection"](**args, options={"subtitle_srt": SRT}), parent["owner_id"])
    with pytest.raises(ValueError, match="변경"):
        handlers["create"](handlers["Create"](**args, options={"subtitle_srt": SRT.replace("literal", "changed")},
                           token=plan["token"], request_id="normal-stale"), parent["owner_id"])
    assert not writes and not runtime.database.children and not runtime.database.outbox


def connect_accepted_runtime(runtime, parent, graph, state):
    asset = {**state.asset, "bytes": state.refs["audio"]["bytes"], "metadata": {}}
    runtime.store = state.runtime.store
    runtime._shared_asset = lambda *args: asset
    runtime.asset_reference = state.runtime.asset_reference
    runtime._shared_job = state.runtime._shared_job
    child_runs = runtime._runs
    runtime._runs = lambda db, owner, identity: state.runs if identity == state.job["id"] else child_runs(db, owner, identity)
    runtime.ticket_artifacts = state.runtime.ticket_artifacts
    runtime._bindings = lambda *args, **kwargs: {}


def test_accepted_input_is_rechecked_at_create_and_frozen_without_copy(accepted_inputs, inline_runtime):
    from video_service.canonical import digest
    state = accepted_inputs
    runtime, parent, graph, writes = inline_runtime
    connect_accepted_runtime(runtime, parent, graph, state)
    selector = {"job_id": state.job["id"], "run_id": state.runs[1]["id"], "port": "transcript"}
    options = {"accepted_inputs": {"transcript": selector}}
    plan = runtime.normal_input_plan(state.actor, state.asset["asset_id"], graph, options)
    expected = digest(plan["bindings"])
    # A different committed producer result after preview changes the pin.
    replacement = state.runtime.store.put(state.job["owner_id"], [b'[{"id":"new","start":0,"end":1,"text":"unit other"}]'], "transcript")
    state.runs[1]["result"]["outputs"]["transcript"] = replacement
    with pytest.raises(ValueError, match="미리보기"):
        runtime.create(state.actor, state.asset["asset_id"], parent["workflow_id"], 1, request_id="normal-race", options=options, input_plan_sha256=expected)
    assert runtime.database.children == [] and runtime.database.outbox == []
    fresh = runtime.normal_input_plan(state.actor, state.asset["asset_id"], graph, options)
    child = runtime.create(state.actor, state.asset["asset_id"], parent["workflow_id"], 1, request_id="normal-accepted", options=options,
                           input_plan_sha256=digest(fresh["bindings"]))
    assert child["snapshot"]["inputs"]["transcript"] == {**replacement, "source_owner_id": state.job["owner_id"]}
    assert child["snapshot"]["normal_input_bindings"]["transcript"]["run_id"] == selector["run_id"]
    assert writes == []


def test_real_create_reuses_same_video_raw_audio_with_exact_scoped_lifecycle(accepted_inputs, recovery_runtime):
    from video_service.canonical import digest
    from mideagent_orchestrator.workflow import scope_snapshot, ready_tool_ids
    from mideagent_orchestrator.agent_view import project_agents
    from test_workflow_generality import accepted_unit_runs
    state = accepted_inputs
    graph = input_graph("transcription_agent", audio=True)
    _, parent = historical_chain()
    parent["owner_id"] = state.actor
    runtime = recovery_runtime(graph, parent)
    connect_accepted_runtime(runtime, parent, graph, state)
    pins = {"goal__transcribe": {"model_id": "2" * 32, "revision": 8}}
    runtime._bindings = lambda *args, **kwargs: deepcopy(pins)
    options = {"accepted_inputs": {"audio": {"job_id": state.job["id"], "run_id": state.runs[0]["id"], "port": "audio"}}}
    plan = runtime.normal_input_plan(state.actor, state.asset["asset_id"], graph, options)
    before = deepcopy((state.job, state.runs, state.asset))
    child = runtime.create(state.actor, state.asset["asset_id"], parent["workflow_id"], 1, request_id="normal-audio", options=options,
                           input_plan_sha256=digest(plan["bindings"]))
    snapshot = child["snapshot"]
    assert set(scope_snapshot(snapshot)["bindings"]["goal"]) == {"analyze", "preprocess_audio", "transcribe"}
    assert [n["type"] for n in snapshot["definition"]["nodes"]] == ["analyze", "preprocess_audio", "transcribe"]
    assert snapshot["inputs"]["audio"] == {**state.refs["audio"], "source_owner_id": state.job["owner_id"]}
    assert snapshot["inputs"]["video"]["source_owner_id"] == state.job["owner_id"]
    assert snapshot["model_bindings"] == pins
    runs = accepted_unit_runs({"definition": snapshot["definition"]})
    child["status"] = "completed"
    assert project_agents(child, runs, [], [])["nodes"][0]["state"] == "completed"
    assert ready_tool_ids(snapshot, {r["node_id"]: r for r in runs}) == set()
    assert (state.job, state.runs, state.asset) == before


def test_actual_prior_input_choices_handler_exposes_only_producer_identities(accepted_inputs, inline_runtime):
    from types import SimpleNamespace
    state = accepted_inputs
    runtime, parent, graph, writes = inline_runtime
    connect_accepted_runtime(runtime, parent, graph, state)
    execute = runtime.database.execute
    runtime.database.execute = lambda sql, params: SimpleNamespace(fetchall=lambda: [{"id": state.job["id"]}]) if sql.startswith("SELECT id FROM jobs WHERE status") else execute(sql, params)
    handlers = mount_actual_input_handlers(runtime)
    choices = handlers["input_choices"](state.asset["asset_id"], state.actor)["inputs"]
    assert {c["port"] for c in choices} == {"audio", "transcript"}
    assert all(set(c) == {"job_id", "run_id", "port", "label"} for c in choices)
    assert "storage_key" not in repr(choices) and not writes and not runtime.database.children
    state.job["asset_id"] = "8" * 32
    choices = handlers["input_choices"](state.asset["asset_id"], state.actor)["inputs"]
    assert [c["port"] for c in choices] == ["transcript"], "only audio requires same-video lineage"


@pytest.mark.parametrize("bad", ["receipt_unknown", "request_digest", "derived_video", "wrong_type"])
def test_accepted_input_requires_definitive_original_receipt(accepted_inputs, bad):
    from mideagent_orchestrator.normal_inputs import NormalInputs
    state = accepted_inputs
    selector = {"job_id": state.job["id"], "run_id": state.runs[0]["id"], "port": "audio"}
    if bad == "receipt_unknown": state.runs[0]["result"]["status"] = "unknown"
    elif bad == "request_digest": state.runs[0].update(request={"unit": "changed"}, request_sha256="0" * 64)
    elif bad == "derived_video": state.runs[0]["inputs"] = {"video": {**state.runtime.asset_reference(state.asset), "sha256": "1" * 64}}
    else: state.runs[0]["result"]["outputs"]["audio"]["type"] = "video"
    with pytest.raises(ValueError):
        NormalInputs(state.runtime).resolve(None, state.actor, state.asset, input_graph("transcription_agent", audio=True), {"accepted_inputs": {"audio": selector}})


def test_selected_prior_translation_language_uses_actual_frozen_request(accepted_inputs):
    from mideagent_orchestrator.normal_inputs import NormalInputs
    from video_service.canonical import digest
    state = accepted_inputs
    node = state.job["snapshot"]["definition"]["nodes"][1]
    node.update(type="translate", options={"translation_profile": "legacy", "target_language": ""})
    state.job["snapshot"]["options"]["target_language"] = "ko"
    state.runs[1].update(request={"translation": {"target_language": "pt-BR"}})
    state.runs[1]["request_sha256"] = digest(state.runs[1]["request"])
    selector = {"job_id": state.job["id"], "run_id": state.runs[1]["id"], "port": "transcript"}
    result = NormalInputs(state.runtime).resolve(None, state.actor, state.asset, input_graph(), {"accepted_inputs": {"transcript": selector}})
    assert result["language"] == "pt-BR" and result["segments"] == ROWS


def test_handler_preview_token_changes_on_a_different_accepted_receipt(accepted_inputs, inline_runtime):
    state = accepted_inputs
    runtime, parent, graph, writes = inline_runtime
    connect_accepted_runtime(runtime, parent, graph, state)
    handlers = mount_actual_input_handlers(runtime)
    args = dict(asset_id=state.asset["asset_id"], definition_id=parent["workflow_id"], definition_revision=1,
                options={"accepted_inputs": {"transcript": {"job_id": state.job["id"], "run_id": state.runs[1]["id"], "port": "transcript"}}})
    first = handlers["preview"](handlers["Selection"](**args), state.actor)
    state.runs[1]["result"]["outputs"]["transcript"] = state.runtime.store.put(state.job["owner_id"], [b'[{"id":4,"start":0,"end":1,"text":"unit replacement"}]'], "transcript")
    second = handlers["preview"](handlers["Selection"](**args), state.actor)
    assert first["token"] != second["token"]
    with pytest.raises(ValueError, match="변경"):
        handlers["create"](handlers["Create"](**args, request_id="normal-token-stale", token=first["token"]), state.actor)
    assert not writes and not runtime.database.children
