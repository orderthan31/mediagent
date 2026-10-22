"""Renewal graph contract; editor support and execution admission are separate."""

import json
import math
import re
from copy import deepcopy

from .cpu_agents import CPU_AGENTS
from .node_contracts import NODES, VALUE_TYPES, node_spec, validate_node

CONTROL_TYPES = ("control_if", "control_switch", "control_loop", "control_fallback")


def catalog():
    nodes = deepcopy(NODES)
    for kind, label, ports, options in [
        (
            "control_if",
            "IF",
            ["true", "false"],
            {
                "operator": [
                    "equals",
                    "not_equals",
                    "contains",
                    "greater_than",
                    "less_than",
                    "exists",
                ],
                "field": [""],
                "compare_value": [""],
            },
        ),
        (
            "control_switch",
            "Switch",
            ["case_1", "case_2", "default"],
            {"field": [""], "cases": ["case_1\ncase_2"]},
        ),
        (
            "control_loop",
            "Loop",
            ["body", "done"],
            {
                "mode": ["each_item", "repeat_count"],
                "repeat_count": ["3"],
                "max_iterations": ["10"],
            },
        ),
        (
            "control_fallback",
            "폴백",
            ["primary", "fallback"],
            {"trigger": ["on_error", "on_empty_result"], "max_attempts": ["1"]},
        ),
    ]:
        nodes.append(
            {
                "id": kind,
                "label": label,
                "inputs": {
                    "value": "video",
                    **({"next": "video"} if kind == "control_loop" else {}),
                },
                "outputs": {p: "video" for p in ports},
                "options": {"data_type": VALUE_TYPES, **options},
                "optional_inputs": ["next"] if kind == "control_loop" else [],
                "port_types_from_options": {
                    "inputs": {
                        p: "data_type"
                        for p in (
                            ["value", "next"] if kind == "control_loop" else ["value"]
                        )
                    },
                    "outputs": {p: "data_type" for p in ports},
                },
                "kind": "control",
            }
        )
    for node in nodes:
        node["kind"] = (
            "control"
            if node["id"] in (*CONTROL_TYPES, "select", "join", "review", "decision")
            else "agent"
        )
        node["execution"] = (
            "cpu_subprocess"
            if node["id"] in CPU_AGENTS
            else "application_control"
            if node["id"]
            in ("select", "join", "review", "control_if", "control_switch")
            else "unavailable"
        )
        if node["id"] in CPU_AGENTS:
            node["entrypoint"] = (
                "python -m video_service.cpu_agents --agent " + node["id"]
            )
    return {
        "version": 1,
        "nodes": nodes,
        "standalone_execution": True,
        "model_network_enabled": False,
    }


def spec(kind, options):
    if kind not in CONTROL_TYPES:
        selected = node_spec(kind, options)
        if selected is not None and kind == "encode":
            selected["optional_inputs"] = []
            if options.get("subtitle_mode", "burn") == "none":
                selected["inputs"].pop("subtitles", None)
        return selected
    base = next(deepcopy(n) for n in catalog()["nodes"] if n["id"] == kind)
    data_type = options.get("data_type", "video")
    base["inputs"] = {k: data_type for k in base["inputs"]}
    base["outputs"] = {k: data_type for k in base["outputs"]}
    if kind == "control_switch":
        cases = options.get("cases", "case_1\ncase_2").splitlines()
        base["outputs"] = {
            **{"case_" + str(i + 1): data_type for i in range(len(cases))},
            "default": data_type,
        }
    return base


def validate(payload):
    issues = []

    def fail(message, node=None, edge=None):
        issues.append({"message": message, "node_id": node, "edge_id": edge})

    fields = {"catalog_version", "revision", "name", "inputs", "nodes", "edges"}
    if not isinstance(payload, dict) or set(payload) != fields:
        return {
            "valid": False,
            "issues": [{"message": "정의 필드 오류", "node_id": None, "edge_id": None}],
        }
    if len(json.dumps(payload, allow_nan=False).encode()) > 65536:
        fail("정의 크기 초과")
    if (
        type(payload["catalog_version"]) is not int
        or payload["catalog_version"] != 1
        or type(payload["revision"]) is not int
        or payload["revision"] < 0
    ):
        fail("정의 버전 오류")
    if (
        not isinstance(payload["name"], str)
        or not 1 <= len(payload["name"].strip()) <= 80
    ):
        fail("이름은 1~80자입니다.")
    inputs, nodes, edges = payload["inputs"], payload["nodes"], payload["edges"]
    if (
        not isinstance(inputs, dict)
        or len(inputs) > 20
        or any(
            not re.fullmatch("[A-Za-z][A-Za-z0-9_-]{0,39}", k) or v not in VALUE_TYPES
            for k, v in inputs.items()
        )
    ):
        fail("외부 입력 형식 오류")
    if (
        not isinstance(nodes, list)
        or not 1 <= len(nodes) <= 100
        or not isinstance(edges, list)
        or len(edges) > 300
        or issues
    ):
        return {
            "valid": False,
            "issues": issues
            or [{"message": "노드/연결 개수 오류", "node_id": None, "edge_id": None}],
        }
    indexed, specs = {}, {}
    for n in nodes:
        if (not isinstance(n, dict)
                or not {"id", "type", "position", "options"} <= set(n)
                or set(n) - {"id", "type", "position", "options", "model_ref", "fallback_refs"}):
            fail("노드 필드 오류")
            continue
        identity = n["id"]
        if (
            not isinstance(identity, str)
            or not re.fullmatch("[A-Za-z0-9_-]{1,64}", identity)
            or identity in indexed
        ):
            fail("노드 ID 오류")
            continue
        options = n["options"]
        if not isinstance(options, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or len(v) > 2048
            for k, v in options.items()
        ):
            fail("노드 옵션 오류", identity)
            continue
        selected = spec(n["type"], options)
        if selected is None:
            fail("지원하지 않는 노드", identity)
            continue
        try:
            if n["type"] in CONTROL_TYPES:
                if (
                    set(options) - set(selected["options"])
                    or options.get("data_type", "video") not in VALUE_TYPES
                ):
                    raise ValueError("제어노드 옵션 오류")
                if (
                    n["type"] == "control_if"
                    and options.get("operator", "equals")
                    not in selected["options"]["operator"]
                ):
                    raise ValueError("조건 연산자 오류")
                if n["type"] == "control_switch":
                    cases = options.get("cases", "case_1\ncase_2").splitlines()
                    if (
                        not 1 <= len(cases) <= 20
                        or any(not c.strip() for c in cases)
                        or len(set(cases)) != len(cases)
                    ):
                        raise ValueError("분기값은 1~20개 고유값입니다.")
                if n["type"] == "control_loop":  # noqa: SIM102 -- keep per-node validation grouped
                    if (
                        options.get("mode", "repeat_count")
                        not in ("repeat_count", "each_item")
                        or not 1
                        <= int(options.get("repeat_count", "3"))
                        <= int(options.get("max_iterations", "10"))
                        <= 100
                    ):
                        raise ValueError("반복 상한 오류")
                if n["type"] == "control_fallback" and (
                    options.get("trigger", "on_error")
                    not in ("on_error", "on_empty_result")
                    or not 1 <= int(options.get("max_attempts", "1")) <= 3
                ):
                    raise ValueError("폴백 옵션 오류")
            else:
                validate_node(
                    {
                        "node": n["type"],
                        "inputs": {
                            k: v
                            for k, v in selected["inputs"].items()
                            if k not in selected["optional_inputs"]
                        },
                        "options": options,
                    }
                )
            if "model_ref" in n:
                from .model_reference import valid_reference

                valid_reference(n["model_ref"])
            if "fallback_refs" in n:
                from .model_reference import valid_reference

                refs = n["fallback_refs"]
                if n["type"] != "translate" or not n.get("model_ref") or not isinstance(refs, list) or len(refs) > 3:
                    raise ValueError("번역 폴백은 선택한 기본 모델 뒤 최대 3개입니다.")
                pins = [n["model_ref"], *[valid_reference(ref) for ref in refs]]
                if len({ref["model_id"] for ref in pins}) != len(pins):
                    raise ValueError("같은 모델은 한 번만 선택하세요.")
            pos = n["position"]
            if (
                not isinstance(pos, dict)
                or set(pos) != {"x", "y"}
                or any(
                    type(pos[k]) not in (int, float)
                    or not math.isfinite(pos[k])
                    or not 0 <= pos[k] <= bound
                    for k, bound in (("x", 4000), ("y", 3000))
                )
            ):
                raise ValueError("노드 위치 오류")
        except (ValueError, TypeError, KeyError):
            fail("노드 설정을 확인하세요.", identity)
        indexed[identity], specs[identity] = n, selected
    incoming, adjacency, edge_ids = {}, {k: [] for k in indexed}, set()
    for e in edges:
        try:
            if (
                not isinstance(e, dict)
                or set(e) != {"id", "source", "target"}
                or not re.fullmatch("[A-Za-z0-9_-]{1,64}", e["id"])
                or e["id"] in edge_ids
            ):
                raise ValueError()
            edge_ids.add(e["id"])
            a, b = e["source"], e["target"]
            if set(a) != {"node", "port"} or set(b) != {"node", "port"}:
                raise ValueError()
            source = inputs if a["node"] == "$input" else specs[a["node"]]["outputs"]
            target = specs[b["node"]]["inputs"]
            key = (b["node"], b["port"])
            if key in incoming or source[a["port"]] != target[b["port"]]:
                raise ValueError()
            incoming[key] = a["node"]
            # Only the explicit Loop.next back-edge may form a graph cycle.
            if a["node"] != "$input" and not (
                indexed[b["node"]]["type"] == "control_loop" and b["port"] == "next"
            ):
                adjacency[a["node"]].append(b["node"])
        except (ValueError, TypeError, KeyError):
            fail(
                "연결/자료 유형/중복 입력 오류",
                edge=e.get("id") if isinstance(e, dict) else None,
            )
    for identity, selected in specs.items():
        for p in set(selected["inputs"]) - set(selected["optional_inputs"]):
            if (identity, p) not in incoming:
                fail("필수 입력 연결 없음: " + p, identity)
        if selected["id"] == "transcribe":
            audio_source = incoming.get((identity, "audio"))
            clock_source = incoming.get((identity, "timeline"))
            if audio_source and clock_source and audio_source != clock_source:
                fail("전사 오디오와 타임라인은 같은 생산자여야 합니다.", identity)
    visited, active = set(), set()

    def visit(identity):
        if identity in active:
            fail("명시 Loop.next 외 순환은 지원하지 않습니다.", identity)
            return
        if identity in visited:
            return
        active.add(identity)
        for other in adjacency[identity]:
            visit(other)
        active.remove(identity)
        visited.add(identity)

    for identity in indexed:
        visit(identity)
    return {"valid": not issues, "issues": issues, "executable": False}
