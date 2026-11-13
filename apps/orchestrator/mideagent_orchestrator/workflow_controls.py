"""Typed public flow controls compiled into the existing durable native graph.

Business nodes still own their tools. Controller nodes pass verified artifacts;
no provider, database, execution admission or storage I/O occurs at compilation.
"""
from copy import deepcopy
import math
import re

from mideagent_agents.catalog import CLASSES, BUSINESS_INPUTS, PUBLIC_CONTROLS, catalog, goal_options
from video_service.canonical import canonical
from video_service.editor_contracts import resolve_editor_contracts
from video_service.renewal_contracts import spec, validate as validate_native

CONTROLS = PUBLIC_CONTROLS

def extended(public):
    if not isinstance(public, dict):
        return False
    nodes, edges = public.get("nodes"), public.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return False
    return (
        any(isinstance(n, dict) and n.get("type") not in CLASSES for n in nodes)
        or any(isinstance(e, dict) and any(isinstance(e.get(k), dict) and e[k].get("port") != "media" for k in ("source", "target")) for e in edges)
        or public.get("input_profile") == "audio_file_v1" and len(nodes) > 1
        or public.get("input_profile") == "subtitle_file_v1"
    )


def agent_inputs(kind):
    return {"media": "media_task", "gate": "control_signal", **BUSINESS_INPUTS.get(kind, {})}


def resolved_spec(node):
    if node["type"] in CLASSES:
        result = deepcopy(next(n for n in catalog()["nodes"] if n["id"] == node["type"]))
        result["inputs"] = agent_inputs(node["type"])
        effective = goal_options(node)
        for key, variants in result.get("conditional_outputs", {}).items():
            result["outputs"].update(variants.get(effective.get(key), {}))
        for key, variants in result.get("hidden_outputs", {}).items():
            for port in variants.get(effective.get(key), []):
                result["outputs"].pop(port, None)
        return result
    if node["type"] not in CONTROLS:
        raise ValueError("지원되는 업무 에이전트와 제어 노드만 연결하세요.")
    result = spec(node["type"], node.get("options", {}))
    if not result:
        raise ValueError("지원되는 제어 노드를 선택하세요.")
    return result


def _control_node(node):
    if set(node) - {"id", "type", "options", "position"}:
        raise ValueError("제어 노드에는 모델·내부 도구 설정을 추가하지 않습니다.")
    if not isinstance(node.get("options"), dict) or any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 2048 for k, v in node["options"].items()):
        raise ValueError("제어 노드 설정을 확인하세요.")
    selected = resolved_spec(node)
    identity = node["id"]
    native = {**deepcopy(node), "position": {"x": 0, "y": 0}}
    inputs = {"input_" + port: kind for port, kind in selected["inputs"].items()}
    sample = {
        "catalog_version": 1, "revision": 0, "name": "제어 계약 검증", "inputs": inputs,
        "nodes": [native],
        "edges": [{"id": "validate_" + str(i), "source": {"node": "$input", "port": "input_" + port}, "target": {"node": identity, "port": port}} for i, port in enumerate(selected["inputs"])],
    }
    result = validate_native(sample)
    if not result["valid"]:
        raise ValueError("제어 노드 설정을 확인하세요: " + "; ".join(i["message"] for i in result["issues"]))


def shape(public):
    from .workflow import _FIELDS, validate_agent_node
    if (not isinstance(public, dict) or set(public) - _FIELDS or public.get("catalog_version") != 2
            or type(public.get("revision")) is not int or public["revision"] < 0
            or not isinstance(public.get("name"), str) or not 1 <= len(public["name"].strip()) <= 80
            or len(canonical(public)) > 65536):
        raise ValueError("에이전트 워크플로우 형식을 확인하세요.")
    inputs, nodes, edges = public.get("inputs"), public.get("nodes"), public.get("edges")
    if (not isinstance(inputs, dict) or any(k not in {"video", "audio", "transcript"} or v != k for k, v in inputs.items())
            or not isinstance(nodes, list) or not 1 <= len(nodes) <= 24
            or not isinstance(edges, list) or len(edges) > 96
            or public.get("input_profile") not in (None, "audio_file_v1", "subtitle_file_v1")):
        raise ValueError("입력과 업무·제어 연결을 확인하세요.")
    specs, indexed = {}, {}
    agent_specs = {n["id"]: n for n in catalog()["nodes"] if n["id"] in CLASSES}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("노드 설정 형식을 확인하세요.")
        identity = node.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identity) or identity in indexed:
            raise ValueError("노드 식별자를 확인하세요.")
        position = node.get("position")
        if (not isinstance(position, dict) or set(position) != {"x", "y"}
                or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000 for v in position.values())):
            raise ValueError("노드 위치를 확인하세요.")
        if node.get("type") in CLASSES:
            if node["type"] == "faceswap_agent":
                raise ValueError("얼굴 합성은 현재 연결 workflow 범위가 아닙니다.")
            validate_agent_node(node, agent_specs)
        else:
            _control_node(node)
        indexed[identity], specs[identity] = node, resolved_spec(node)
    incoming, edge_ids = {}, set()
    parents = {key: [] for key in indexed}
    for edge in edges:
        if (not isinstance(edge, dict) or set(edge) != {"id", "source", "target"}
                or not isinstance(edge["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", edge["id"]) or edge["id"] in edge_ids):
            raise ValueError("연결 식별자를 확인하세요.")
        edge_ids.add(edge["id"])
        source, target = edge["source"], edge["target"]
        if any(not isinstance(p, dict) or set(p) != {"node", "port"} for p in (source, target)):
            raise ValueError("연결 포트를 확인하세요.")
        try:
            source_ports = inputs if source["node"] == "$input" else specs[source["node"]]["outputs"]
            target_ports = specs[target["node"]]["inputs"]
            source_type, target_type = source_ports[source["port"]], target_ports[target["port"]]
            compatible = source_type == target_type or target_type == "control_signal"
        except (KeyError, TypeError):
            compatible = False
        key = (target["node"], target["port"])
        if not compatible or key in incoming:
            raise ValueError("연결 자료 유형 또는 중복 입력을 확인하세요.")
        incoming[key] = edge
        if source["node"] != "$input":
            parents[target["node"]].append(source["node"])
    for identity, node in indexed.items():
        connected = {p for n, p in incoming if n == identity}
        if node["type"] in CLASSES:
            required_sources = {"media", "transcript", "subtitles"} if node["type"] == "subtitle_video_agent" else {"media", "transcript"}
            if CLASSES[node["type"]].requires_parent and not connected & required_sources and "transcript" not in inputs:
                raise ValueError("업무에 사용할 전사·번역 결과를 연결하세요.")
            source = node.get("options", {}).get("audio_source", "video")
            if node["type"] == "transcription_agent" and (source == "audio_file_v1") != (public.get("input_profile") == "audio_file_v1"):
                raise ValueError("전사 입력 profile과 음성 출처가 다릅니다.")
        elif (set(specs[identity]["inputs"]) - set(specs[identity].get("optional_inputs", []))) - connected:
            raise ValueError("필수 제어 입력을 연결하세요.")
    ordered, pending = [], list(nodes)
    while pending:
        completed = {n["id"] for n in ordered}
        ready = [n for n in pending if set(parents[n["id"]]) <= completed]
        if not ready:
            raise ValueError("워크플로우 흐름이 순환합니다.")
        for node in ready:
            ordered.append(node)
            pending.remove(node)
    return ordered, parents


def compile_graph(public, *, input_language=None, preserve_input_cues=True):
    ordered, _ = shape(public)
    nodes, edges, owners, outputs, contexts, values, input_contexts = [], [], {}, {}, {}, {}, {}
    explicit = public["inputs"]
    base: dict = {} if public.get("input_profile") in {"audio_file_v1", "subtitle_file_v1"} else {"video": ("$input", "video")}
    if "transcript" in explicit:
        base.update(transcript=("$input", "transcript"), original_transcript=("$input", "transcript"), transcript_language=input_language or "auto", original_language=input_language or "auto")
        if preserve_input_cues:
            base["cue_policy"] = "preserve_v1"
    if "audio" in explicit:
        base["audio"] = ("$input", "audio")
    for port, kind in explicit.items():
        values[("$input", port)] = (("$input", port), kind)
        contexts[("$input", port)] = deepcopy(base)
    for node in ordered:
        identity, kind = node["id"], node["type"]
        incoming = [e for e in public["edges"] if e["target"]["node"] == identity]
        context = deepcopy(base)
        if kind in CLASSES:
            media = next((e for e in incoming if e["target"]["port"] == "media"), None)
            if media:
                key = (media["source"]["node"], media["source"]["port"])
                context.update(deepcopy(contexts[key]))
            explicit_ports = {e["target"]["port"] for e in incoming}
            for edge in sorted(incoming, key=lambda e: e["target"]["port"]):
                port = edge["target"]["port"]
                if port in {"media", "gate"}:
                    continue
                key = (edge["source"]["node"], edge["source"]["port"])
                source_context = contexts.get(key, {})
                reference, _ = values[key]
                if port == "transcript":
                    for field in ("original_transcript", "original_language", "transcript_language", "translated_language", "cue_policy"):
                        context.pop(field, None)
                        if field in source_context:
                            context[field] = deepcopy(source_context[field])
                    context.setdefault("original_transcript", reference)
                    context.setdefault("transcript_language", input_language or "auto")
                    context.setdefault("original_language", context["transcript_language"])
                elif port == "audio" and "video" not in explicit_ports and "video" in source_context:
                    context["video"] = deepcopy(source_context["video"])
                context[port] = reference
        if kind in CLASSES:
            agent = CLASSES[kind](node)
            def add(tool, inputs, *, input_languages=None):
                nodes.append(tool)
                owners[tool["id"]] = identity
                if input_languages:
                    input_contexts[tool["id"]] = {p: {"node": inputs[p][0], "port": inputs[p][1], "language": value} for p, value in input_languages.items()}
                for p, source in inputs.items():
                    edges.append({"id": "flow_" + str(len(edges)), "source": {"node": source[0], "port": source[1]}, "target": {"node": tool["id"], "port": p}})
            try:
                context = agent.plan(context, add)
            except KeyError as error:
                raise ValueError("업무에 필요한 입력을 연결하세요: " + str(error.args[0])) from None
            declared = agent.outputs(context)
            outputs[identity] = {p: {"node": r[0], "port": r[1]} for p, r in declared.items()}
            for port, reference in declared.items():
                value_type = spec(next(n["type"] for n in nodes if n["id"] == reference[0]), next(n["options"] for n in nodes if n["id"] == reference[0]))["outputs"][reference[1]]
                values[(identity, port)] = (reference, value_type)
                contexts[(identity, port)] = deepcopy(context)
            contexts[(identity, "media")] = deepcopy(context)
        else:
            selected = resolved_spec(node)
            native = {**deepcopy(node), "position": {"x": 0, "y": 0}}
            nodes.append(native)
            owners[identity] = identity
            outputs[identity] = {p: {"node": identity, "port": p} for p in selected["outputs"]}
            passed = next((e for e in incoming if e["target"]["port"] == "value"), None)
            if passed:
                source_key = (passed["source"]["node"], passed["source"]["port"])
                context.update(deepcopy(contexts.get(source_key, {})))
            for edge in incoming:
                reference, _ = values[(edge["source"]["node"], edge["source"]["port"])]
                edges.append({"id": "flow_" + str(len(edges)), "source": {"node": reference[0], "port": reference[1]}, "target": {"node": identity, "port": edge["target"]["port"]}})
            for port, value_type in selected["outputs"].items():
                reference = (identity, port)
                values[(identity, port)] = (reference, value_type)
                branch = deepcopy(context)
                mapped = {"transcript": "transcript", "video": "video", "audio": "audio", "subtitle": "subtitles", "artifact_manifest": "manifest"}.get(value_type)
                if mapped:
                    branch[mapped] = reference
                contexts[(identity, port)] = branch
    native_inputs = {e["source"]["port"]: explicit.get(e["source"]["port"], e["source"]["port"]) for e in edges if e["source"]["node"] == "$input"}
    if set(explicit) - set(native_inputs):
        raise ValueError("연결되지 않은 외부 입력을 제거하세요.")
    if public.get("input_profile") == "audio_file_v1":
        from video_service.long_audio_budget import ID as AUDIO_BUDGET
        for native in nodes:
            if native["type"] in {"preprocess_audio", "transcribe", "translate", "generate_subtitle"}:
                native["options"].setdefault("media_budget", AUDIO_BUDGET)
    definition = resolve_editor_contracts({"catalog_version": 1, "revision": public["revision"], "name": public["name"], "inputs": native_inputs, "nodes": nodes, "edges": edges})
    validation = validate_native(definition)
    if not validation["valid"]:
        raise ValueError("업무·제어 실행 연결을 확인하세요: " + "; ".join(i["message"] for i in validation["issues"]))
    return {"definition": definition, "owners": owners, "outputs": outputs, "input_contexts": input_contexts, "agent_definition": deepcopy(public), "control_policy": 1, **({"input_language": input_language or "auto"} if "transcript" in explicit else {})}


def public_input_state(snapshot, scope, node, indexed, memo=None):
    """Wait for complete business goals; an absent chosen port skips its consumers.

    Public gate edges carry readiness only. Internal tool artifacts never escape
    a business boundary before that goal has completed its own validation.
    """
    from .workflow import node_decision
    memo = {} if memo is None else memo
    if node["id"] in memo:
        return memo[node["id"]]
    public = {n["id"]: n for n in scope["definition"]["nodes"]}
    states = []
    for edge in scope["definition"]["edges"]:
        if edge["target"]["node"] != node["id"] or edge["source"]["node"] == "$input":
            continue
        parent = public[edge["source"]["node"]]
        inherited = public_input_state(snapshot, scope, parent, indexed, memo)
        state = node_decision(snapshot, scope, parent, indexed)["state"]
        if inherited == "waiting" or state not in {"completed", "failed", "skipped", "cancelled", "blocked"}:
            states.append("waiting")
            continue
        if inherited in {"blocked", "skipped"}:
            state = inherited
        if state in {"failed", "blocked", "cancelled"}:
            states.append("blocked")
        elif state == "skipped":
            states.append("skipped")
        elif edge["source"]["port"] == "media":
            states.append("completed")
        else:
            binding = snapshot.get("agent_output_bindings", {}).get(parent["id"], {}).get(edge["source"]["port"])
            run = indexed.get(binding["node"], {}) if binding else {}
            value = (run.get("result") or {}).get("outputs", {}).get(binding["port"]) if binding else None
            states.append("completed" if value is not None else "skipped")
    if "waiting" in states:
        result = "waiting"
    elif "blocked" in states:
        result = "blocked"
    elif node["type"] == "join" and "completed" in states:
        result = "completed"
    elif "skipped" in states:
        result = "skipped"
    else:
        result = "completed"
    memo[node["id"]] = result
    return result


def control_decision(node, indexed, definition):
    """Read accepted control receipts, including deliberately absent branch ports."""
    from video_service.object_store import validate_reference
    run = indexed.get(node["id"])
    if run is None:
        return {"state": "ready", "tool": node["id"]}
    state = run.get("display_status", run["status"])
    if state != "completed":
        return {"state": "failed" if state in {"failed", "blocked", "held", "unknown", "quarantined"} else state,
                "tool": None, "reason": run.get("display_reason") or run.get("error_code")}
    native = next(n for n in definition["nodes"] if n["id"] == node["id"])
    expected = spec(native["type"], native["options"])["outputs"]
    receipt = run.get("result") or {}
    outputs = receipt.get("outputs", {}) if isinstance(receipt, dict) else {}
    try:
        if not isinstance(outputs, dict) or set(outputs) - set(expected):
            raise ValueError("unexpected_control_output")
        if node["type"] == "select":
            selection = native["options"].get("selection", "a")
            required = {"a", "b"} if selection == "both" else {selection}
            if set(outputs) != required:
                raise ValueError("missing_selected_output")
        elif node["type"] in {"control_if", "control_switch"}:
            if len(outputs) != 1:
                raise ValueError("missing_branch_output")
        elif set(outputs) != set(expected):
            raise ValueError("missing_control_output")
        for name, reference in outputs.items():
            validate_reference(reference)
            if reference["type"] != expected[name]:
                raise ValueError("control_output_type_mismatch")
    except (ValueError, KeyError, TypeError):
        return {"state": "failed", "tool": None, "reason": "제어 결과를 확인할 수 없습니다."}
    return {"state": "completed", "tool": None}
