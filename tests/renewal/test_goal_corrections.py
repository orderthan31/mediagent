"""Correction-cycle unit data: actual source methods, no SQL/service/provider I/O."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
for project in ("packages/shared", "agents", "apps/orchestrator"):
    sys.path.insert(0, str(ROOT / project))


def translation_graph(target="pt-BR"):
    from mideagent_orchestrator.workflow import default_definition
    graph = default_definition()
    graph["nodes"] = graph["nodes"][:2]
    graph["edges"] = graph["edges"][:1]
    graph["nodes"][0]["options"]["source_language"] = "ja"
    for i, node in enumerate(graph["nodes"]):
        node["model_ref"] = {"model_id": str(i + 1) * 32, "revision": i + 3}
    graph["nodes"][1]["options"].update(target_language=target, llm_options='{"temperature":0.2}')
    return graph


@pytest.mark.parametrize("target", ["pt-BR", "pl", "en", "ja", "ko"])
def test_translation_without_subtitle_goal_preserves_full_native_language_contract(target):
    from mideagent_agents.catalog import catalog, goal_options
    from mideagent_orchestrator.workflow import compile_definition
    from video_service.renewal_contracts import spec
    from video_service.node_contracts import validate_node
    graph = translation_graph(target)
    saved = json.loads(json.dumps(graph))
    before = deepcopy(saved)
    compiled = compile_definition(saved)
    tool = compiled["definition"]["nodes"][-1]
    assert tool["type"] == "translate" and tool["options"]["target_language"] == target
    assert validate_node({"node": "translate", "inputs": {"transcript": "transcript"}, "options": tool["options"]})["valid"]
    descriptor = next(n for n in catalog()["nodes"] if n["id"] == "translation_agent")
    assert descriptor["options"]["target_language"] == spec("translate", {})["options"]["target_language"], "catalog must retain native open language input, not subtitle enums"
    assert descriptor["option_defaults"]["target_language"] == "ko"
    assert goal_options(saved["nodes"][-1])["target_language"] == target
    assert tool["model_ref"] == saved["nodes"][-1]["model_ref"]
    assert tool["options"]["llm_options"] == saved["nodes"][-1]["options"]["llm_options"]
    assert saved == before


@pytest.mark.parametrize("target", ["", "auto", "EN", "p_l", "en-!"])
def test_public_translation_reuses_native_language_rejection(target):
    from mideagent_orchestrator.workflow import compile_definition
    with pytest.raises(ValueError):
        compile_definition(translation_graph(target))


def test_sami_from_previous_goal_is_not_published_by_srt_only_goal():
    from mideagent_orchestrator.workflow import compile_definition
    graph = translation_graph("en")
    graph["nodes"] = graph["nodes"][:1]
    graph["edges"] = []
    for identity, format in (("both", "srt_smi"), ("srt", "srt")):
        parent = graph["nodes"][-1]["id"]
        graph["nodes"].append({"id": identity, "type": "subtitle_file_agent", "position": {"x": 0, "y": 0},
                               "options": {"format": format, "transcript_source": "original"}})
        graph["edges"].append({"id": identity + "_edge", "source": {"node": parent, "port": "media"},
                               "target": {"node": identity, "port": "media"}})
    compiled = compile_definition(graph)
    assert set(compiled["outputs"]["both"]) == {"subtitles", "sami"}
    assert compiled["outputs"]["srt"] == {"subtitles": {"node": "srt__generate_subtitle", "port": "subtitles"}}
    assert {e["source"]["node"] for e in compiled["definition"]["edges"] if e["target"]["port"] == "transcript"} == {"transcription__transcribe"}


class MemoryDatabase:
    """Only expected in-memory INSERT/UPDATE effects; no database driver exists."""
    def __init__(self, job, runs=()):
        self.job, self.runs, self.outbox = job, list(runs), []

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params):
        if sql.startswith("INSERT INTO node_runs"):
            row = {"id": params[2], "node_id": params[3], "generation": params[5], "status": params[6],
                   "options": params[10], "node_type": params[11], "request": params[12], "result": None}
            self.runs.append(row)
            return SimpleNamespace(fetchone=lambda: row)
        if sql.startswith("INSERT INTO message_outbox"):
            self.outbox.append(params)
        elif sql.startswith("UPDATE jobs SET status=CASE"):
            self.job["status"] = "running" if any(r["status"] == "running" for r in self.runs) else "waiting"
        elif sql.startswith("UPDATE jobs SET status=%s"):
            self.job["status"] = params[0]
        else:
            raise AssertionError("Unexpected SQL boundary: " + sql)
        return SimpleNamespace(fetchone=lambda: None)


@pytest.fixture
def source_execution(monkeypatch):
    """Compile untouched production methods; inject only storage/admission doubles.

    This exercises the complete command constructor and scheduler, rather than
    replacing either with a test implementation. No SQL package is imported.
    """
    from video_service.canonical import canonical, digest
    from video_service.renewal_contracts import spec
    from video_service.agent_protocol import CPU_AGENTS
    path = ROOT / "apps/orchestrator/mideagent_orchestrator/execution.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Execution")
    methods = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in {
        "_insert_run", "_ready_agent_tools", "_result_for", "_write_outbox", "claim_next",
        "create", "recover", "_creation_model_bindings", "normal_input_plan", "input_choices", "inspect", "_shared_view"}]
    cls = ast.ClassDef(name="SourceExecution", bases=[], keywords=[], body=methods, decorator_list=[])
    namespace = dict(__name__="mideagent_orchestrator.execution_unit", __package__="mideagent_orchestrator",
                     uuid4=uuid4, canonical=canonical, digest=digest, Jsonb=lambda x: deepcopy(x),
                     public_asset=lambda asset: deepcopy(asset), request_id=lambda value: None,
                     Conflict=ValueError, spec=spec, CPU_AGENTS=CPU_AGENTS, CONTROL=frozenset(),
                     TERMINAL=frozenset({"completed", "failed", "cancelled", "skipped", "blocked", "quarantined"}))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    pool = SimpleNamespace(enrolled_in=lambda *args: False, ready_in=lambda *args: True,
                           assigned_in=lambda *args: None)
    leaves = {
        "mideagent_orchestrator.agent_pool": {"AgentPool": pool},
        "mideagent_orchestrator.dispatch_queue": {"DispatchQueue": SimpleNamespace(managed_in=lambda *args: False)},
        "video_service.postgres.subtitle_tracks": {"SubtitleTracks": lambda runtime: SimpleNamespace(preflight=lambda *args: None)},
        "video_service.postgres.job_processing_review": {"JobProcessingReview": lambda runtime: SimpleNamespace(capture_in=lambda *args: runtime.review_block)},
    }
    for name, attributes in leaves.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)

    def build(job, runs=()):
        runtime = namespace["SourceExecution"]()
        runtime.database = MemoryDatabase(job, runs)
        runtime._job = lambda *args, **kwargs: job
        runtime._runs = lambda *args: runtime.database.runs
        runtime._preflight_cpu_inputs = lambda *args: None
        runtime._checked_input = lambda *args: None
        runtime._engine_role = lambda *args: False
        runtime.fleet = None
        runtime.review_block = False
        return runtime
    return build


def execution_job(compiled):
    from video_service.long_audio_budget import definition_policy
    from mideagent_orchestrator.workflow import goal_execution_options
    snapshot = {"definition": deepcopy(compiled["definition"]), "agent_definition": deepcopy(compiled["agent_definition"]),
                "agent_output_policy": 1, "agent_execution_policy": 1,
                "agent_input_contexts": deepcopy(compiled.get("input_contexts", {})),
                "options": goal_execution_options(compiled, {}),
                "inputs": {"video": unit_reference("video")}, "model_bindings": {}}
    audio = definition_policy(snapshot["definition"])
    if audio:
        snapshot["audio_pipeline_policy"] = audio
    for node in snapshot["definition"]["nodes"]:
        if node.get("model_ref"):
            snapshot["model_bindings"][node["id"]] = {**node["model_ref"], "fallbacks": [{"model_id": "f" * 32, "revision": 1}]}
    return {"id": "a" * 32, "owner_id": "b" * 32, "generation": 1, "status": "waiting",
            "active_claim_id": "c" * 32, "cancel_requested": False, "snapshot": snapshot}


def unit_reference(kind):
    return {"storage_key": "blobs/" + "d" * 64, "sha256": "d" * 64, "bytes": 42, "type": kind}


def test_chained_translation_command_uses_frozen_input_language_and_exact_pins(source_execution):
    from mideagent_orchestrator.workflow import compile_definition
    graph = translation_graph("en")
    second = deepcopy(graph["nodes"][-1])
    second.update(id="german", options={"target_language": "de", "llm_options": '{"temperature":0.4}'})
    graph["nodes"].append(second)
    graph["edges"].append({"id": "to_german", "source": {"node": "translation", "port": "media"}, "target": {"node": "german", "port": "media"}})
    compiled = compile_definition(graph)
    job = execution_job(compiled)
    before = deepcopy(job["snapshot"])
    runtime = source_execution(job)
    node = job["snapshot"]["definition"]["nodes"][-1]
    row, command = runtime._insert_run(runtime.database, job, node, {"transcript": unit_reference("transcript")}, "running")
    assert command["translation"]["source_language"] == "en"
    assert command["translation"]["target_language"] == "de"
    pin = job["snapshot"]["model_bindings"][node["id"]]
    assert command["translation"]["candidates"] == [pin, *pin["fallbacks"]]
    assert command["options"]["llm_options"] == '{"temperature":0.4}'
    assert row["request"] == command and job["snapshot"] == before
    # Old snapshots keep the former global fallback and command meaning.
    job["snapshot"].pop("agent_execution_policy")
    _, old = runtime._insert_run(runtime.database, job, node, {"transcript": unit_reference("transcript")}, "running")
    assert old["translation"]["source_language"] == "ja"
    expected_old = deepcopy(command)
    expected_old["attempt_id"] = old["attempt_id"]
    expected_old["translation"]["source_language"] = "ja"
    assert old == expected_old


def test_separate_asr_branches_bind_each_translation_command_to_its_input(source_execution):
    from mideagent_orchestrator.workflow import compile_definition
    graph = translation_graph("en")
    asr = deepcopy(graph["nodes"][0])
    asr.update(id="asr_de", options={"source_language": "de"})
    mt = deepcopy(graph["nodes"][1])
    mt.update(id="portuguese", options={"target_language": "pt-BR"})
    graph["nodes"].extend([asr, mt])
    graph["edges"].append({"id": "de_branch", "source": {"node": "asr_de", "port": "media"},
                           "target": {"node": "portuguese", "port": "media"}})
    compiled = compile_definition(graph)
    job = execution_job(compiled)
    runtime = source_execution(job)
    before = deepcopy(job["snapshot"])
    for node in job["snapshot"]["definition"]["nodes"]:
        if node["type"] != "translate":
            continue
        _, command = runtime._insert_run(runtime.database, job, node, {"transcript": unit_reference("transcript")}, "running")
        expected = ("de", "pt-BR") if node["id"] == "portuguese__translate" else ("ja", "en")
        assert (command["translation"]["source_language"], command["translation"]["target_language"]) == expected
        assert "source_language" not in command["options"], "no unsupported native options"
    assert job["snapshot"] == before


@pytest.mark.parametrize("bad", ["missing", "producer"])
def test_new_translation_command_rejects_missing_or_misbound_context(source_execution, bad):
    from mideagent_orchestrator.workflow import compile_definition
    job = execution_job(compile_definition(translation_graph()))
    node = job["snapshot"]["definition"]["nodes"][-1]
    if bad == "missing":
        job["snapshot"].pop("agent_input_contexts")
    else:
        job["snapshot"]["agent_input_contexts"][node["id"]]["transcript"]["node"] = "other_input"
    runtime = source_execution(job)
    with pytest.raises(ValueError, match="translation_input_context"):
        runtime._insert_run(runtime.database, job, node, {"transcript": unit_reference("transcript")}, "running")
    assert runtime.database.runs == []


@pytest.mark.parametrize("target", ["pt-BR", "pl", "en", "ja", "ko"])
def test_actual_translation_command_keeps_selected_target_verbatim(source_execution, target):
    from mideagent_orchestrator.workflow import compile_definition
    job = execution_job(compile_definition(translation_graph(target)))
    node = job["snapshot"]["definition"]["nodes"][-1]
    runtime = source_execution(job)
    _, command = runtime._insert_run(runtime.database, job, node, {"transcript": unit_reference("transcript")}, "running")
    assert command["translation"]["source_language"] == "ja"
    assert command["translation"]["target_language"] == target
    assert command["options"]["target_language"] == target


@pytest.mark.parametrize("target,serializer,expected", [("pt-BR", "from_transcript", "pt"), ("pl", "und", "und")])
def test_subtitle_serializer_language_does_not_replace_translation_target_or_provenance(target, serializer, expected):
    from mideagent_orchestrator.workflow import compile_definition
    graph = translation_graph(target)
    graph["nodes"].append({"id": "file", "type": "subtitle_file_agent", "position": {"x": 0, "y": 0},
                           "options": {"language": serializer, "format": "srt_smi"}})
    graph["edges"].append({"id": "to_file", "source": {"node": "translation", "port": "media"},
                           "target": {"node": "file", "port": "media"}})
    before = deepcopy(graph)
    compiled = compile_definition(graph)
    tools = {n["id"]: n for n in compiled["definition"]["nodes"]}
    assert tools["translation__translate"]["options"]["target_language"] == target
    assert tools["file__generate_subtitle"]["options"]["language"] == expected
    assert set(compiled["outputs"]["file"]) == {"subtitles", "sami"}
    assert compiled["input_contexts"]["translation__translate"]["transcript"] == {
        "node": "transcription__transcribe", "port": "transcript", "language": "ja"}
    assert graph == before


def media_graph(*kinds):
    return {"catalog_version": 2, "revision": 0, "name": "unit media goals", "inputs": {}, "edges": [],
            "nodes": [{"id": "goal" + str(i), "type": kind, "options": {}, "position": {"x": 0, "y": 0}}
                      for i, kind in enumerate(kinds)]}


def unit_run(node, status="completed"):
    from video_service.renewal_contracts import spec
    return {"id": uuid4().hex, "node_id": node["id"], "status": status,
            "result": {"status": status, "outputs": {port: unit_reference(kind)
                       for port, kind in spec(node["type"], node["options"])["outputs"].items()}} if status == "completed" else None}


@pytest.mark.parametrize("kind", ["audio_extraction_agent", "video_conversion_agent"])
def test_actual_scheduler_settles_failed_goal_with_unstarted_owned_tool(source_execution, kind):
    from mideagent_orchestrator.workflow import compile_definition
    compiled = compile_definition(media_graph(kind))
    job = execution_job(compiled)
    failed = unit_run(compiled["definition"]["nodes"][0], "failed")
    before = deepcopy(failed)
    runtime = source_execution(job, [failed])
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == "failed"
    assert runtime.database.runs == [before] and not runtime.database.outbox


def test_actual_scheduler_finishes_independent_branch_before_settling_failure(source_execution):
    from mideagent_orchestrator.workflow import compile_definition
    compiled = compile_definition(media_graph("audio_extraction_agent", "video_conversion_agent"))
    job = execution_job(compiled)
    nodes = compiled["definition"]["nodes"]
    failed = unit_run(nodes[0], "failed")
    runtime = source_execution(job, [failed])
    command = runtime.claim_next(job["owner_id"], job["id"])
    assert command["agent"]["id"] == "encode" and len(runtime.database.outbox) == 1
    assert job["status"] == "running"
    running = deepcopy(runtime.database.runs)
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == "running" and runtime.database.runs == running
    runtime.database.runs[-1].update({k: v for k, v in unit_run(nodes[2]).items() if k != "id"})
    command = runtime.claim_next(job["owner_id"], job["id"])
    assert command["agent"]["id"] == "validate_video" and len(runtime.database.outbox) == 2
    runtime.database.runs[-1].update({k: v for k, v in unit_run(nodes[3]).items() if k != "id"})
    before = deepcopy(runtime.database.runs)
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == "failed" and runtime.database.runs == before


def test_failed_goal_does_not_discard_independent_work_waiting_for_capacity(source_execution):
    from mideagent_orchestrator.workflow import compile_definition
    compiled = compile_definition(media_graph("audio_extraction_agent", "video_conversion_agent"))
    job = execution_job(compiled)
    runtime = source_execution(job, [unit_run(compiled["definition"]["nodes"][0], "failed")])
    sys.modules["mideagent_orchestrator.agent_pool"].AgentPool.ready_in = lambda *args: False
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == "waiting" and not runtime.database.outbox
    assert len(runtime.database.runs) == 1


def test_failed_ancestor_settles_without_fabricating_descendant_runs(source_execution):
    from mideagent_orchestrator.workflow import compile_definition, default_definition
    compiled = compile_definition(default_definition())
    job = execution_job(compiled)
    failed = unit_run(compiled["definition"]["nodes"][0], "failed")
    runtime = source_execution(job, [failed])
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == "failed" and runtime.database.runs == [failed]
    assert not runtime.database.outbox


@pytest.mark.parametrize("valid", [True, False])
def test_new_scheduler_settles_only_valid_completed_owned_results(source_execution, valid):
    from mideagent_orchestrator.workflow import compile_definition
    compiled = compile_definition(media_graph("video_conversion_agent"))
    job = execution_job(compiled)
    runs = [unit_run(node) for node in compiled["definition"]["nodes"]]
    if not valid:
        runs[-1]["result"]["outputs"]["report"]["type"] = "report"
    runtime = source_execution(job, runs)
    before = deepcopy(runs)
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == ("completed" if valid else "failed")
    assert runtime.database.runs == before and not runtime.database.outbox


@pytest.mark.parametrize("state", ["running", "waiting", "held", "unknown", "stale", "receipt_unknown"])
def test_failure_does_not_clear_uncertain_or_live_independent_attempt(source_execution, state):
    from mideagent_orchestrator.workflow import compile_definition
    compiled = compile_definition(media_graph("audio_extraction_agent", "video_conversion_agent"))
    job = execution_job(compiled)
    nodes = compiled["definition"]["nodes"]
    failed = unit_run(nodes[0], "failed")
    pending = unit_run(nodes[2], "running" if state == "stale" else "failed" if state == "receipt_unknown" else state)
    if state == "stale":
        pending["lease_valid"] = False
    if state == "receipt_unknown":
        pending["result"] = {"status": "unknown"}
    runtime = source_execution(job, [failed, pending])
    before = deepcopy(runtime.database.runs)
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == "waiting" and not runtime.database.outbox
    assert runtime.database.runs == before


@pytest.mark.parametrize("winner", ["review", "cancel", "review_run", "legacy"])
def test_goal_failure_preserves_review_cancel_and_historical_settlement(source_execution, winner):
    from mideagent_orchestrator.workflow import compile_definition
    compiled = compile_definition(media_graph("audio_extraction_agent"))
    job = execution_job(compiled)
    failed = unit_run(compiled["definition"]["nodes"][0], "review_required" if winner == "review_run" else "failed")
    if winner == "cancel":
        job["cancel_requested"] = True
    if winner == "legacy":
        job["snapshot"].pop("agent_execution_policy")
    runtime = source_execution(job, [failed])
    runtime.review_block = winner == "review"
    assert runtime.claim_next(job["owner_id"], job["id"]) is None
    assert job["status"] == ("review_required" if winner == "review_run" else "waiting")
    assert runtime.database.runs == [failed] and not runtime.database.outbox
