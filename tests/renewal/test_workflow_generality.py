"""Cost-free business workflow contracts; no products/jobs/provider calls."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for project in ("packages/shared", "agents", "apps/orchestrator"):
    sys.path.insert(0, str(ROOT / project))


def subtitle_flow(*, translated=False, kind="subtitle_file_agent", **options):
    from mideagent_orchestrator.workflow import default_definition
    graph = default_definition()
    graph["nodes"][0]["options"]["source_language"] = "ja"
    graph["nodes"][0]["model_ref"] = {"model_id": "a" * 32, "revision": 7}
    graph["nodes"][0]["options"]["llm_options"] = '{"temperature":0.2}'
    if not translated:
        graph["nodes"].pop(1)
    else:
        graph["nodes"][1]["options"]["target_language"] = "pt-BR"
        graph["nodes"][1]["model_ref"] = {"model_id": "b" * 32, "revision": 3}
    graph["nodes"][-1].update(type=kind, options=options)
    graph["edges"] = [{"id": "flow" + str(i),
                       "source": {"node": a["id"], "port": "media"},
                       "target": {"node": b["id"], "port": "media"}}
                      for i, (a, b) in enumerate(zip(graph["nodes"], graph["nodes"][1:]))]
    return graph


def test_original_subtitle_file_without_translation_or_encoding_preserves_model():
    from mideagent_orchestrator.workflow import compile_definition
    graph = subtitle_flow(format="srt_smi", transcript_source="original")
    compiled = compile_definition(graph)
    tools = {n["type"]: n for n in compiled["definition"]["nodes"]}
    assert set(tools) == {"analyze", "extract_audio", "preprocess_audio", "transcribe", "generate_subtitle"}
    assert tools["transcribe"]["model_ref"] == graph["nodes"][0]["model_ref"]
    assert tools["transcribe"]["options"]["llm_options"] == '{"temperature":0.2}'
    assert tools["generate_subtitle"]["options"]["language"] == "ja"
    assert tools["generate_subtitle"]["options"]["format"] == "srt_smi"
    assert compiled["outputs"]["subtitle_video"] == {
        "subtitles": {"node": "subtitle_video__generate_subtitle", "port": "subtitles"},
        "sami": {"node": "subtitle_video__generate_subtitle", "port": "sami"}}
    assert compiled["agent_definition"] == graph


@pytest.mark.parametrize("mode", ["burn", "soft"])
@pytest.mark.parametrize("source,language,producer", [("translated", "pt", "translation__translate"),
                                                     ("original", "ja", "transcription__transcribe")])
@pytest.mark.parametrize("format", ["srt", "srt_smi"])
def test_translated_and_original_subtitle_video_choices(mode, source, language, producer, format):
    from mideagent_orchestrator.workflow import compile_definition
    from video_service.renewal_contracts import spec
    graph = subtitle_flow(translated=True, kind="subtitle_video_agent", subtitle_mode=mode,
                          transcript_source=source, format=format, video_codec="hevc")
    compiled = compile_definition(graph)
    tools = {n["type"]: n for n in compiled["definition"]["nodes"]}
    assert tools["translate"]["options"]["target_language"] == "pt-BR"
    assert tools["translate"]["model_ref"] == graph["nodes"][1]["model_ref"]
    assert tools["generate_subtitle"]["options"]["language"] == language
    assert tools["encode"]["options"]["subtitle_mode"] == mode
    assert tools["encode"]["options"]["video_codec"] == "hevc"
    assert next(e["source"]["node"] for e in compiled["definition"]["edges"]
                if e["target"] == {"node": tools["generate_subtitle"]["id"], "port": "transcript"}) == producer
    assert ("sami" in compiled["outputs"]["subtitle_video"]) == (format == "srt_smi")
    assert ("sami" in spec("generate_subtitle", tools["generate_subtitle"]["options"])["outputs"]) == (format == "srt_smi")
    assert compiled["agent_definition"] == graph


def test_direct_conversion_has_no_models_and_owns_validation():
    from mideagent_orchestrator.workflow import compile_definition, ready_tool_ids
    from mideagent_orchestrator.agent_view import project_agents
    graph = {"catalog_version": 2, "revision": 0, "name": "변환", "inputs": {}, "edges": [],
             "nodes": [{"id": "convert", "type": "video_conversion_agent", "position": {"x": 0, "y": 0},
                        "options": {"video_codec": "hevc", "resolution": "720p"}}]}
    compiled = compile_definition(graph)
    assert [n["type"] for n in compiled["definition"]["nodes"]] == ["encode", "validate_video"]
    assert all("model_ref" not in n for n in compiled["definition"]["nodes"])
    assert compiled["definition"]["nodes"][0]["options"]["subtitle_mode"] == "none"
    assert ready_tool_ids(compiled, {}) == {"convert__encode"}
    run = {"id": "encode-unit-run", "node_id": "convert__encode", "status": "completed",
           "result": {"outputs": {"video": {"type": "video"}}}}
    assert ready_tool_ids(compiled, {run["node_id"]: run}) == {"convert__validate_video"}
    view = project_agents({"snapshot": compiled, "status": "running"}, [run], [], [])
    assert view["nodes"][0]["state"] != "completed"
    check = {"id": "check-unit-run", "node_id": "convert__validate_video", "status": "completed",
             "result": {"outputs": {"report": {"type": "report"}}}}
    view = project_agents({"snapshot": compiled, "status": "completed"}, [run, check], [], [])
    assert view["nodes"][0]["state"] == "failed"
    check["result"]["outputs"]["report"]["type"] = "validation_report"
    view = project_agents({"snapshot": compiled, "status": "completed"}, [run, check], [], [])
    assert view["nodes"][0]["state"] == "completed"


def accepted_unit_runs(compiled):
    """Synthetic typed receipt data only; no media or real accepted jobs."""
    from video_service.renewal_contracts import spec
    runs = []
    for i, node in enumerate(compiled["definition"]["nodes"]):
        outputs = {port: {"type": kind, "sha256": "c" * 64, "bytes": 42,
                          "storage_key": "blobs/" + "c" * 64}
                   for port, kind in spec(node["type"], node["options"])["outputs"].items()}
        runs.append({"id": f"{i + 1:032x}", "node_id": node["id"], "status": "completed",
                     "attempt": 1, "generation": 1, "result": {"outputs": outputs}})
    return runs


def frozen_job(compiled):
    return {"id": "d" * 32, "owner_id": "e" * 32, "generation": 1, "status": "completed",
            "snapshot": {"definition": compiled["definition"], "agent_definition": compiled["agent_definition"],
                         "agent_output_policy": 1, "agent_output_bindings": compiled["outputs"]}}


def test_goal_outputs_resolve_frozen_exact_run_ports_without_private_reference_or_mutation():
    from copy import deepcopy
    from mideagent_orchestrator.workflow import compile_definition
    from mideagent_orchestrator.agent_view import project_agents
    compiled = compile_definition(subtitle_flow(translated=True, kind="subtitle_video_agent", format="srt_smi"))
    job, runs = frozen_job(compiled), accepted_unit_runs(compiled)
    before = deepcopy((job, runs))
    view = project_agents(job, runs, [], [])
    outputs = view["nodes"][-1]["outputs"]
    assert {v["port"] for v in outputs} == {"subtitles", "sami", "video", "report"}
    for output in outputs:
        assert set(output) == {"name", "run_id", "node_id", "port", "type"}
        binding = job["snapshot"]["agent_output_bindings"]["subtitle_video"][output["name"]]
        assert output["node_id"] == binding["node"] and output["port"] == binding["port"]
        assert any(r["id"] == output["run_id"] and r["node_id"] == output["node_id"] for r in runs)
    assert (job, runs) == before
    # Without frozen bindings, do not infer or invent historical published results.
    job["snapshot"].pop("agent_output_bindings")
    assert all(not n["outputs"] for n in project_agents(job, runs, [], [])["nodes"])


@pytest.mark.parametrize("bad", ["pending", "failed", "unknown", "missing", "type", "reference", "duplicate"])
def test_goal_outputs_hide_unaccepted_or_invalid_receipts(bad):
    from mideagent_orchestrator.workflow import compile_definition
    from mideagent_orchestrator.agent_view import project_agents
    compiled = compile_definition(subtitle_flow(format="srt"))
    job, runs = frozen_job(compiled), accepted_unit_runs(compiled)
    final = runs[-1]
    if bad in {"pending", "failed"}:
        final["status"] = bad
    elif bad == "unknown":
        final["display_status"] = "unknown"
    elif bad == "missing":
        final["result"]["outputs"] = {}
    elif bad == "type":
        final["result"]["outputs"]["subtitles"]["type"] = "video"
    elif bad == "reference":
        final["result"]["outputs"]["subtitles"]["storage_key"] = "private/credential"
    else:
        runs.append({**final, "id": "f" * 32})
    assert project_agents(job, runs, [], [])["nodes"][-1]["outputs"] == []


def test_published_subtitle_is_final_even_when_consumed_and_context_stays_intermediate():
    from copy import deepcopy
    from mideagent_orchestrator.workflow import compile_definition
    from video_service.goal_outputs import output_stage
    compiled = compile_definition(subtitle_flow(kind="subtitle_video_agent"))
    job, runs = frozen_job(compiled), accepted_unit_runs(compiled)
    subtitle = next(r for r in runs if r["node_id"].endswith("__generate_subtitle"))
    analyze = runs[0]
    assert output_stage(job["snapshot"], subtitle["node_id"], "subtitles") == "final"
    assert output_stage(job["snapshot"], analyze["node_id"], "metadata") == "intermediate"
    legacy = deepcopy(job)
    legacy["snapshot"].pop("agent_output_policy")
    assert output_stage(legacy["snapshot"], subtitle["node_id"], "subtitles") == "intermediate"
    assert output_stage(legacy["snapshot"], analyze["node_id"], "metadata") == "final"


def test_frozen_goal_languages_are_execution_authority_and_media_needs_no_language():
    from mideagent_orchestrator.workflow import compile_definition, goal_execution_options
    compiled = compile_definition(subtitle_flow(translated=True))
    assert goal_execution_options(compiled, {}) == {"source_language": "ja", "target_language": "pt-BR"}
    with pytest.raises(ValueError):
        goal_execution_options(compiled, {"target_language": "ko"})
    graph = {"catalog_version": 2, "revision": 0, "name": "WAV", "inputs": {}, "edges": [],
             "nodes": [{"id": "wav", "type": "audio_extraction_agent", "position": {"x": 0, "y": 0}, "options": {}}]}
    assert goal_execution_options(compile_definition(graph), {}) == {}
    assert goal_execution_options(compile_definition(graph), {"source_language": "auto", "target_language": "ko"}) == {}


def test_default_and_legacy_projection_keep_three_goal_native_plan_unchanged():
    from copy import deepcopy
    from mideagent_orchestrator.workflow import compile_definition, default_definition, scope_snapshot
    compiled = compile_definition(default_definition())
    native = compiled["definition"]
    assert [n["type"] for n in native["nodes"]] == ["analyze", "extract_audio", "preprocess_audio", "transcribe",
                                                        "translate", "generate_subtitle", "encode", "validate_video"]
    assert next(n for n in native["nodes"] if n["type"] == "encode")["options"]["subtitle_mode"] == "burn"
    legacy = {"definition": deepcopy(native)}
    before = deepcopy(legacy)
    view = scope_snapshot(legacy)
    assert view["legacy_projection"] is True
    assert [n["type"] for n in view["definition"]["nodes"]] == ["transcription_agent", "translation_agent", "subtitle_video_agent"]
    assert legacy == before


def test_every_goal_has_consistent_tool_hub_registration():
    from mideagent_agents.catalog import CLASSES
    from mideagent_agents.registry import registration
    for kind, cls in CLASSES.items():
        value = registration(kind)
        assert value is not None, kind
        assert value["entrypoint"] == cls.__module__ + ":" + cls.__name__ + ".advance"
        assert value["runtime_roles"] == [{"transcribe": "transcription", "translate": "translation"}.get(r, r)
                                           for r in cls.tool_order]


def test_unknown_source_language_is_und_and_saved_original_setting_is_preserved():
    from mideagent_orchestrator.workflow import compile_definition
    graph = subtitle_flow()
    graph["nodes"][0]["options"]["source_language"] = "auto"
    tool = compile_definition(graph)["definition"]["nodes"][-1]
    assert tool["options"]["language"] == "und"
    graph["nodes"][-1]["options"].update(language="de", format="srt_smi")
    tool = compile_definition(graph)["definition"]["nodes"][-1]
    assert tool["options"]["language"] == "de"
    assert tool["options"]["format"] == "srt_smi"


def test_old_ticket_manifest_entries_and_bytes_remain_unchanged():
    """Load the actual storage class without importing the unavailable SQL driver."""
    import ast
    import hashlib
    import json
    from copy import deepcopy
    from video_service.canonical import canonical
    from video_service.goal_outputs import output_stage
    from mideagent_orchestrator.workflow import compile_definition
    path = ROOT / "packages/shared/video_service/postgres/ticket_artifacts.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TicketArtifacts")
    namespace = dict(hashlib=hashlib, json=json, canonical=canonical, output_stage=output_stage,
                     Conflict=ValueError, Missing=LookupError)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    TicketArtifacts = namespace["TicketArtifacts"]
    compiled = compile_definition(subtitle_flow(kind="subtitle_video_agent"))
    job, runs = frozen_job(compiled), accepted_unit_runs(compiled)
    job["snapshot"].pop("agent_output_policy")
    job["snapshot"]["artifact_layout"] = 1
    job["ticket_number"] = 1
    for run in runs:
        recorded = []
        for port, reference in run["result"]["outputs"].items():
            entry = TicketArtifacts.entry(job, run, port, reference)
            entry["storage"] = {**reference, "storage_key": TicketArtifacts.key(job, run, port, reference)}
            recorded.append(entry)
        run["result"]["ticket_artifacts"] = {"entries": recorded}
    artifacts = TicketArtifacts(None)
    entries = artifacts.entries(job, runs)
    raw = canonical(artifacts.document(job, entries, 1, "ticket_v1"))
    manifest = {"type": "ticket_manifest", "sha256": "f" * 64, "bytes": len(raw),
                "storage_key": f'tickets/{job["id"]}/manifests/{"f" * 64}.json'}
    runs[-1]["result"]["ticket_artifacts"]["manifest"] = {"sequence": 1, "entry_count": len(entries), "reference": manifest}
    class ReadOnlyUnitStore:
        def read(self, owner, reference):
            assert owner == job["owner_id"] and reference == manifest
            return raw
    before = deepcopy((job, runs))
    artifacts.store = ReadOnlyUnitStore()
    assert artifacts.read(job, runs) == raw
    assert (job, runs) == before


def test_new_goal_stops_on_invalid_owned_reference_before_next_tool():
    from mideagent_orchestrator.workflow import compile_definition, ready_tool_ids
    from mideagent_orchestrator.agent_view import project_agents
    compiled = compile_definition(subtitle_flow())
    job, runs = frozen_job(compiled), accepted_unit_runs(compiled)
    runs = runs[:1]
    runs[0]["result"]["outputs"]["metadata"]["bytes"] = 0
    assert ready_tool_ids(job["snapshot"], {r["node_id"]: r for r in runs}) == set()
    assert project_agents(job, runs, [], [])["nodes"][0]["state"] == "failed"


def test_inspection_options_follow_compiled_tool_settings_and_public_overrides():
    from mideagent_agents.catalog import goal_options
    from mideagent_orchestrator.workflow import compile_definition
    graph = subtitle_flow(translated=True, kind="subtitle_video_agent")
    node = graph["nodes"][-1]
    node["tool_settings"] = {"generate_subtitle": {"format": "srt_smi", "language": "ja"},
                             "encode": {"subtitle_mode": "soft"}}
    options = goal_options(node)
    assert options["format"] == "srt_smi" and options["language"] == "ja" and options["subtitle_mode"] == "soft"
    node["options"]["format"] = "srt"
    assert goal_options(node)["format"] == "srt"
    compiled = compile_definition(graph)
    assert next(n for n in compiled["definition"]["nodes"] if n["type"] == "generate_subtitle")["options"]["format"] == "srt"


@pytest.mark.parametrize("target_language", ["en", "ja"])
def test_selected_translation_language_reaches_translation_and_subtitle_tools(target_language):
    from mideagent_orchestrator.workflow import default_definition, compile_definition

    graph = default_definition()
    graph["nodes"][0]["model_ref"] = {"model_id": "a" * 32, "revision": 1}
    graph["nodes"][1]["model_ref"] = {"model_id": "b" * 32, "revision": 2}
    graph["nodes"][1]["options"]["target_language"] = target_language
    result = compile_definition(graph)
    tools = {node["type"]: node for node in result["definition"]["nodes"]}
    assert tools["translate"]["options"]["target_language"] == target_language
    assert tools["generate_subtitle"]["options"]["language"] == target_language
    assert tools["translate"]["model_ref"] == graph["nodes"][1]["model_ref"]
    assert result["agent_definition"] == graph


def test_audio_extraction_goal_stands_alone_without_any_model_or_asr():
    from mideagent_orchestrator.workflow import compile_definition, scope_snapshot
    from mideagent_orchestrator.agent_view import project_agents
    from video_service.renewal_contracts import spec

    graph = {"catalog_version": 2, "revision": 0, "name": "음성 추출", "inputs": {},
             "nodes": [{"id": "audio", "type": "audio_extraction_agent", "position": {"x": 0, "y": 0}, "options": {}}], "edges": []}
    compiled = compile_definition(graph)
    assert [node["type"] for node in compiled["definition"]["nodes"]] == ["analyze", "extract_audio"]
    assert all("model_ref" not in node for node in compiled["definition"]["nodes"])
    scope = scope_snapshot(compiled)
    assert set(scope["bindings"]["audio"]) == {"analyze", "extract_audio"}
    runs = []
    for node in compiled["definition"]["nodes"]:
        outputs = {name: {"type": kind} for name, kind in spec(node["type"], node["options"])["outputs"].items()}
        runs.append({"node_id": node["id"], "id": node["id"] + "-run", "status": "completed", "result": {"outputs": outputs}})
    view = project_agents({"snapshot": compiled, "status": "completed"}, runs, [], [])
    assert len(view["nodes"]) == 1
    assert view["nodes"][0]["state"] == "completed"
