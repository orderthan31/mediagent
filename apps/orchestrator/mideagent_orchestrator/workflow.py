"""Public agent workflow contracts and compilation into existing durable tool transport.

The saved workflow has business agents only. Tool plans are built and stepped by
those agents; this orchestrator orders only their public dependencies. Existing
native command/result schemas, queues, storage and ASR/MT LangGraphs are reused.
"""
from copy import deepcopy
import re
from mideagent_agents.catalog import CLASSES, catalog
from video_service.editor_contracts import resolve_editor_contracts
from video_service.model_reference import valid_reference
from video_service.renewal_contracts import validate as validate_native

_FIELDS={"catalog_version","revision","name","inputs","nodes","edges","id","executable"}

def default_definition(name="영상 전사·한국어 자막 번인"):
    nodes=[]
    for i,(identity,kind) in enumerate((("transcription","transcription_agent"),("translation","translation_agent"),("subtitle_video","subtitle_video_agent"))):
        options={"source_language":"auto"}if i==0 else {"target_language":"ko"}if i==1 else {}
        nodes.append({"id":identity,"type":kind,"options":options,"position":{"x":i*290,"y":80}})
    return {"catalog_version":2,"revision":0,"name":name,"inputs":{},"nodes":nodes,
            "edges":[{"id":"agent_flow_"+str(i),"source":{"node":nodes[i]["id"],"port":"media"},
                      "target":{"node":nodes[i+1]["id"],"port":"media"}}for i in range(2)]}

def _shape(value):
    if not isinstance(value,dict) or set(value)-_FIELDS or value.get("catalog_version")!=2:
        raise ValueError("에이전트 워크플로우 형식을 확인하세요.")
    if type(value.get("revision"))is not int or value["revision"]<0:
        raise ValueError("워크플로우 버전을 확인하세요.")
    if not isinstance(value.get("name"),str)or not 1<=len(value["name"].strip())<=100:
        raise ValueError("워크플로우 이름과 입력 설정을 확인하세요.")
    inputs = value.get("inputs")
    if not isinstance(inputs, dict) or any(k not in {"video", "audio", "transcript"} or v != k for k, v in inputs.items()):
        raise ValueError("영상·시간 자막·동일 영상의 추출 음성 입력을 확인하세요.")
    nodes=value.get("nodes");edges=value.get("edges")
    if not isinstance(nodes,list)or not 1<=len(nodes)<=24 or not isinstance(edges,list)or len(edges)>48:
        raise ValueError("에이전트 연결을 확인하세요.")
    ids=set();specs={n["id"]:n for n in catalog()["nodes"]}
    for node in nodes:
        if not isinstance(node,dict)or set(node)-{"id","type","position","options","model_ref","fallback_refs","tool_settings"}:
            raise ValueError("에이전트 설정 형식을 확인하세요.")
        identity=node.get("id");kind=node.get("type")
        if not isinstance(identity,str)or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}",identity)or identity in ids or kind not in CLASSES:
            raise ValueError("워크플로우에는 업무 에이전트만 연결하세요.")
        ids.add(identity)
        if not isinstance(node.get("position"),dict)or set(node["position"])!={"x","y"}or any(type(v)not in(int,float)or not -100000<=v<=100000 for v in node["position"].values()):
            raise ValueError("에이전트 위치를 확인하세요.")
        options=node.get("options",{})
        if not isinstance(options,dict)or any(k not in specs[kind]["options"]or not isinstance(v,str)or k not in {"llm_options", "target_language"} and v not in specs[kind]["options"][k]for k,v in options.items()):
            raise ValueError("에이전트 처리 설정을 확인하세요.")
        if "target_language" in options:
            from video_service.subtitle_tracks import language
            language(options["target_language"])
        if "llm_options" in options:
            from video_service.llm_contract import parse_options
            parse_options(options["llm_options"])
        cls=CLASSES[kind];settings=node.get("tool_settings",{})
        if not isinstance(settings,dict)or set(settings)-set(cls.tool_order)or any(not isinstance(v,dict)or any(not isinstance(k,str)or not isinstance(x,str)for k,x in v.items())for v in settings.values()):
            raise ValueError("에이전트 내부 도구 설정을 확인하세요.")
        if node.get("model_ref"):
            valid_reference(node["model_ref"])
        if node.get("fallback_refs"):
            if kind not in {"transcription_agent","translation_agent"}or not isinstance(node["fallback_refs"],list)or len(node["fallback_refs"])>3:
                raise ValueError("대체 모델 설정을 확인하세요.")
            for pin in node["fallback_refs"]:valid_reference(pin)
        if kind not in {"transcription_agent","translation_agent"}and node.get("model_ref"):
            raise ValueError("이 업무에는 모델을 추가하지 않습니다.")
    seen=set();parents={n["id"]:[]for n in nodes}
    for edge in edges:
        if not isinstance(edge,dict)or set(edge)!={"id","source","target"}or not isinstance(edge["id"],str)or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",edge["id"])or edge["id"]in seen:
            raise ValueError("에이전트 연결 이름을 확인하세요.")
        seen.add(edge["id"])
        for port in (edge["source"],edge["target"]):
            if not isinstance(port,dict)or set(port)!={"node","port"}or port["node"]not in ids or port["port"]!="media":
                raise ValueError("에이전트 간 작업 자료를 연결하세요.")
        parents[edge["target"]["node"]].append(edge["source"]["node"])
    ordered=[];todo=list(nodes)
    while todo:
        ready=[n for n in todo if all(p in {x["id"]for x in ordered}for p in parents[n["id"]])]
        if not ready:raise ValueError("에이전트 흐름이 순환합니다.")
        for node in ready:
            required=1 if CLASSES[node["type"]].requires_parent else 0
            if required and not parents[node["id"]] and "transcript" in inputs:
                required = 0
            if len(parents[node["id"]])!=required:raise ValueError("에이전트 사이의 작업 자료 연결을 확인하세요.")
            if node["type"] == "transcription_agent" and (node.get("options", {}).get("audio_source") == "selected_audio") != ("audio" in inputs):
                raise ValueError("재사용 음성 입력과 전사 목표의 음성 출처를 맞추세요.")
            if any(next(n for n in nodes if n["id"]==p)["type"]=="subtitle_video_agent"for p in parents[node["id"]]):
                raise ValueError("완성 영상은 다음 번역 입력으로 연결할 수 없습니다.")
            ordered.append(node);todo.remove(node)
    if "audio" in inputs and not any(n["type"] == "transcription_agent" and "extract_audio" not in CLASSES[n["type"]].roles(n) for n in nodes):
        raise ValueError("재사용 음성을 사용하는 전사 목표를 연결하세요.")
    if "transcript" in inputs and not any(CLASSES[n["type"]].requires_parent and not parents[n["id"]] for n in nodes):
        raise ValueError("선택 자막을 사용하는 루트 번역·자막 목표를 연결하세요.")
    return ordered,parents

def compile_definition(public, *, input_language=None, preserve_input_cues=True):
    ordered,parents=_shape(public)
    nodes=[];edges=[];owners={};contexts={};output_contexts={};input_contexts={}
    for node in ordered:
        agent=CLASSES[node["type"]](node)
        def add(tool,inputs,*,input_languages=None):
            nodes.append(tool);owners[tool["id"]]=node["id"]
            if input_languages:
                from video_service.subtitle_tracks import language
                input_contexts[tool["id"]] = {
                    port: {"node": inputs[port][0], "port": inputs[port][1],
                           "language": language(value, auto=True)}
                    for port, value in input_languages.items()}
            for port,source in inputs.items():
                edges.append({"id":"tool_edge_"+str(len(edges)),"source":{"node":source[0],"port":source[1]},"target":{"node":tool["id"],"port":port}})
        context=contexts[parents[node["id"]][0]]if parents[node["id"]]else {"video":("$input","video")}
        if not parents[node["id"]]:
            if "audio" in public["inputs"]:
                context["audio"] = ("$input", "audio")
            if "transcript" in public["inputs"] and agent.requires_parent:
                from video_service.subtitle_tracks import language
                selected_language = language(input_language or "auto", auto=True)
                context.update(transcript=("$input", "transcript"), original_transcript=("$input", "transcript"),
                               transcript_language=selected_language, original_language=selected_language)
                if preserve_input_cues:
                    context["cue_policy"] = "preserve_v1"
        contexts[node["id"]]=agent.plan(deepcopy(context),add)
        output_contexts[node["id"]]={k:{"node":v[0],"port":v[1]}for k,v in agent.outputs(contexts[node["id"]]).items()}
    definition=resolve_editor_contracts({"catalog_version":1,"revision":public["revision"],"name":public["name"],"inputs":{"video":"video", **public["inputs"]},"nodes":nodes,"edges":edges})
    validation=validate_native(definition)
    if not validation["valid"]:
        raise ValueError("에이전트 내부 도구 설정이 맞지 않습니다: "+"; ".join(i["message"]for i in validation["issues"])[:600])
    return {"definition":definition,"owners":owners,"outputs":output_contexts,
            "input_contexts": input_contexts, "agent_definition":deepcopy(public),
            **({"input_language": input_language or "auto"} if "transcript" in public["inputs"] else {})}


def translation_input_language(snapshot, node):
    """New-policy input language is bound to the actual frozen transcript edge."""
    from video_service.subtitle_tracks import language
    context = snapshot.get("agent_input_contexts", {}).get(node["id"], {}).get("transcript")
    if not isinstance(context, dict) or set(context) != {"node", "port", "language"}:
        raise ValueError("translation_input_context_missing")
    sources = [edge["source"] for edge in snapshot["definition"]["edges"]
               if edge["target"] == {"node": node["id"], "port": "transcript"}]
    if sources != [{"node": context["node"], "port": context["port"]}]:
        raise ValueError("translation_input_context_mismatch")
    return language(context["language"], auto=True)

def validate(value):
    try:compile_definition(value)
    except (ValueError,KeyError,TypeError)as exc:
        return {"valid":False,"executable":False,"issues":[{"node_id":None,"edge_id":None,"message":str(exc)}]}
    return {"valid":True,"executable":False,"issues":[]}


def goal_execution_options(plan, options):
    """New goal jobs execute saved language choices, with no media-only requirement."""
    result = deepcopy(options)
    tools = plan["definition"]["nodes"]
    for key, role, default in (("source_language", "transcribe", "auto"),
                               ("target_language", "translate", "ko")):
        selected = next((n for n in tools if n["type"] == role), None)
        if selected is None:
            if key == "source_language" and "input_language" in plan:
                result[key] = plan["input_language"]
                continue
            result.pop(key, None)
            continue
        value = selected["options"].get(key, default)
        if key in result and result[key] != value:
            raise ValueError("작업 언어는 저장된 워크플로우 버전과 같아야 합니다.")
        result[key] = value
    return result

def upgrade_legacy(value):
    """Create a NEW public definition; never modify any old revision/job snapshot."""
    if value.get("catalog_version")==2:return deepcopy(value)
    by_type={n["type"]:n for n in value.get("nodes",[])}
    expected={role for kind in ("transcription_agent", "translation_agent", "subtitle_video_agent") for role in CLASSES[kind].tool_order}
    if len(by_type)!=len(value.get("nodes",[]))or set(by_type)!=expected:
        raise ValueError("이전 워크플로우의 에이전트 구성을 확인해야 합니다.")
    result=default_definition(value["name"]);result["revision"]=value["revision"]
    if "id"in value:result["id"]=value["id"]
    for node in result["nodes"]:
        cls=CLASSES[node["type"]];primary=by_type[cls.primary]
        node["tool_settings"]={role:deepcopy(by_type[role]["options"])for role in cls.tool_order}
        if cls.primary=="transcribe":node["options"]={"source_language":primary["options"].get("source_language","auto")}
        elif cls.primary=="translate":node["options"]={"target_language":primary["options"].get("target_language","ko")}
        else:node["options"]={k:v for k,v in primary["options"].items()if k in {"resolution","quality_profile","video_codec"}}
        for key in ("model_ref","fallback_refs"):
            if key in primary:node[key]=deepcopy(primary[key])
    compiled=compile_definition(result)["definition"]
    def wiring(definition):
        types={n["id"]:n["type"]for n in definition["nodes"]};types["$input"]="$input"
        return {(types[e["source"]["node"]],e["source"]["port"],types[e["target"]["node"]],e["target"]["port"])for e in definition["edges"]}
    if value.get("inputs")!={"video":"video"}or wiring(value)!=wiring(compiled):
        raise ValueError("이전 워크플로우의 다른 자료 연결은 직접 확인해야 합니다.")
    return result

def scope_snapshot(snapshot):
    public=snapshot.get("agent_definition")
    legacy=public is None
    if legacy:
        try:public=upgrade_legacy(snapshot["definition"])
        except (ValueError,KeyError,TypeError):return None
    bindings={};owners={}
    original={n["type"]:n["id"]for n in snapshot["definition"]["nodes"]}
    for node in public["nodes"]:
        cls=CLASSES[node["type"]]
        bindings[node["id"]]={role:original[role]if legacy else node["id"]+"__"+role for role in cls.roles(node)}
        owners.update({identity:node["id"]for identity in bindings[node["id"]].values()})
    if set(owners)!={n["id"]for n in snapshot["definition"]["nodes"]}:
        raise ValueError("에이전트 도구 소유권이 실행 정의와 다릅니다.")
    return {"definition":public,"owners":owners,"bindings":bindings,"legacy_projection":legacy}

def ready_tool_ids(snapshot,indexed):
    """Outer orchestrator chooses eligible agents; agents choose their own tools."""
    scope=scope_snapshot(snapshot)
    if scope is None:return None
    public=scope["definition"];ordered,parents=_shape(public);done=set();ready=set()
    for node in ordered:
        if not set(parents[node["id"]])<=done:continue
        decision=CLASSES[node["type"]](node,tool_bindings=scope["bindings"][node["id"]],
                                    verify_references=snapshot.get("agent_output_policy")==1).next_tool(indexed,snapshot["definition"])
        if decision["state"]=="completed":done.add(node["id"])
        elif decision["tool"] is not None:ready.add(decision["tool"])
    return ready


def goal_settlement(snapshot, indexed):
    """Settle new-policy goals without inventing runs for blocked owned tools.

    A missing dependent tool cannot make a failed goal wait forever. Independent
    ready work and any live/uncertain attempt still take precedence over failure.
    This is a decision only; claim_next owns the locked job update.
    """
    if snapshot.get("agent_execution_policy") != 1:
        return None
    for run in indexed.values():
        if run["status"] not in {"completed", "failed", "blocked", "quarantined", "skipped"}:
            return None
        receipt = run.get("result") or {}
        if isinstance(receipt, dict) and receipt.get("status") in {"unknown", "held"}:
            return None
        if run.get("display_status") in {"unknown", "held"} or (run.get("dispatch") or {}).get("phase") in {"unknown", "held"}:
            return None
    scope = scope_snapshot(snapshot)
    if scope is None or ready_tool_ids(snapshot, indexed):
        return None
    decisions = [CLASSES[node["type"]](node, tool_bindings=scope["bindings"][node["id"]],
                    verify_references=snapshot.get("agent_output_policy")==1).next_tool(indexed, snapshot["definition"])
                 for node in scope["definition"]["nodes"]]
    if any(decision["state"] == "failed" for decision in decisions):
        return "failed"
    if set(indexed) == set(scope["owners"]) and all(decision["state"] == "completed" for decision in decisions):
        return "completed"
    return None
