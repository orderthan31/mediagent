"""Business-agent workflows reuse controller data contracts and durable tool execution."""
from copy import deepcopy

import pytest

from mideagent_agents.catalog import catalog
from mideagent_orchestrator.workflow import compile_definition


def node(identity, kind, **options):
    return {"id": identity, "type": kind, "options": options, "position": {"x": 0, "y": 0}}


def edge(source, port, target, input_port):
    return {"id": f"{source.removeprefix(chr(36))}_{port}_{target}_{input_port}", "source": {"node": source, "port": port}, "target": {"node": target, "port": input_port}}


def graph(nodes, edges, **inputs):
    return {"catalog_version": 2, "revision": 0, "name": "업무와 제어 흐름", "inputs": inputs, "nodes": nodes, "edges": edges}


def test_transcript_review_connects_two_business_agents_without_exposing_tools():
    public = graph(
        [node("speech", "transcription_agent"), node("review", "review", data_type="transcript"), node("text", "translation_agent", target_language="ja")],
        [edge("speech", "transcript", "review", "value"), edge("review", "value", "text", "transcript")],
    )
    original = deepcopy(public)
    plan = compile_definition(public)
    assert public == original
    assert {n["type"] for n in plan["definition"]["nodes"]} >= {"transcribe", "translate", "review"}
    translated = next(n for n in plan["definition"]["nodes"] if n["type"] == "translate")
    assert {"source": {"node": "review", "port": "value"}, "target": {"node": translated["id"], "port": "transcript"}} in [{k: e[k] for k in ("source", "target")} for e in plan["definition"]["edges"]]
    assert plan["input_contexts"][translated["id"]]["transcript"]["node"] == "review"


def test_selected_video_branches_and_join_compile_into_existing_native_controls():
    public = graph(
        [node("choose", "select", data_type="video", selection="both"), node("left", "video_conversion_agent"), node("right", "video_conversion_agent"), node("joined", "join", left_type="video", right_type="video")],
        [edge("$input", "video", "choose", "value"), edge("choose", "a", "left", "video"), edge("choose", "b", "right", "video"), edge("left", "video", "joined", "left"), edge("right", "video", "joined", "right")],
        video="video",
    )
    plan = compile_definition(public)
    assert plan["definition"]["inputs"] == {"video": "video"}
    assert plan["outputs"]["joined"]["manifest"] == {"node": "joined", "port": "manifest"}
    assert plan["owners"]["joined"] == "joined"
    assert len([n for n in plan["definition"]["nodes"] if n["type"] == "encode"]) == 2


def test_catalog_exposes_supported_controls_but_not_disabled_loop_or_internal_tools():
    data = catalog()
    controls = {n["id"] for n in data["nodes"] if n.get("kind") == "control"}
    assert {"select", "join", "review", "control_if", "control_switch"} <= controls
    assert not {"analyze", "extract_audio", "encode", "control_loop", "control_fallback"} & {n["id"] for n in data["nodes"]}


@pytest.mark.parametrize("bad", ["wrong_type", "duplicate_input", "cycle", "internal_tool"])
def test_bad_control_wiring_is_rejected_before_native_execution(bad):
    public = graph([node("speech", "transcription_agent"), node("review", "review", data_type="transcript"), node("text", "translation_agent")], [edge("speech", "transcript", "review", "value"), edge("review", "value", "text", "transcript")])
    if bad == "wrong_type":
        public["nodes"][1]["options"]["data_type"] = "video"
    elif bad == "duplicate_input":
        public["edges"].append(edge("speech", "transcript", "text", "transcript"))
    elif bad == "cycle":
        public["edges"].append(edge("text", "transcript", "review", "value"))
    else:
        public["nodes"][1]["type"] = "encode"
    with pytest.raises(ValueError):
        compile_definition(public)


def test_explicit_transcript_and_video_inputs_do_not_overwrite_each_other_when_edges_reorder():
    public = graph(
        [node("text", "translation_agent", target_language="ko"), node("choose", "select", data_type="video", selection="a"), node("render", "subtitle_video_agent")],
        [edge("$input", "transcript", "text", "transcript"), edge("$input", "video", "choose", "value"), edge("text", "transcript", "render", "transcript"), edge("choose", "a", "render", "video")],
        video="video", transcript="transcript",
    )
    def bindings(plan):
        return {(e["target"]["node"], e["target"]["port"]): e["source"] for e in plan["definition"]["edges"]}
    first = compile_definition(public, input_language="en")
    public["edges"].reverse()
    second = compile_definition(public, input_language="en")
    assert bindings(first) == bindings(second)
    assert bindings(first)[("render__generate_subtitle", "transcript")] == {"node": "text__translate", "port": "transcript"}
    assert next(n for n in first["definition"]["nodes"] if n["id"] == "render__generate_subtitle")["options"]["language"] == "ko"


def test_video_goal_consumes_the_reviewed_subtitle_without_generating_or_republishing_it():
    public = graph([node("files", "subtitle_file_agent"), node("approval", "review", data_type="subtitle"), node("render", "subtitle_video_agent", subtitle_source="selected_subtitles")],
        [edge("$input", "transcript", "files", "transcript"), edge("files", "subtitles", "approval", "value"), edge("approval", "value", "render", "subtitles")], transcript="transcript")
    plan = compile_definition(public, input_language="en")
    assert not any(n["id"] == "render__generate_subtitle" for n in plan["definition"]["nodes"])
    assert set(plan["outputs"]["render"]) == {"video", "report"}
    assert next(e["source"] for e in plan["definition"]["edges"] if e["target"] == {"node": "render__encode", "port": "subtitles"}) == {"node": "approval", "port": "value"}

