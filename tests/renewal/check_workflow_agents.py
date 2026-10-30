"""No provider/network/job creation: public workflow boundaries and agent-owned tool plans."""
from video_service.postgres.execution import Execution

def public_catalog_only_agents():
    runtime=object.__new__(Execution)
    runtime.engine_runtime_enabled=False
    runtime.vocalization_runtime=None
    value=runtime.catalog()
    assert {n["id"] for n in value["nodes"]} == {
        "transcription_agent", "translation_agent", "subtitle_video_agent"
    }, "public workflow catalog still exposes standalone tools/control steps"

def owned_goal_flow():
    from mideagent_orchestrator.workflow import compile_definition, default_definition
    from mideagent_agents.catalog import CLASSES
    public=default_definition()
    private=compile_definition(public)
    assert len(public["nodes"])==3 and all(n["type"] in CLASSES for n in public["nodes"])
    assert len(private["definition"]["nodes"])==8
    assert set(private["owners"])=={n["id"]for n in private["definition"]["nodes"]}
    assert private["definition"]["inputs"]=={"video":"video"}


def agent_controls_own_tools():
    from mideagent_orchestrator.workflow import compile_definition, default_definition
    from video_service.renewal_contracts import spec
    public=default_definition(); frozen=compile_definition(public)
    runtime=object.__new__(Execution)
    indexed={}
    assert runtime._ready_agent_tools(frozen,indexed)=={"transcription__analyze"}
    for role in ["analyze","extract_audio","preprocess_audio","transcribe","translate","generate_subtitle","encode","validate_video"]:
        node=next(n for n in frozen["definition"]["nodes"]if n["type"]==role)
        allowed=runtime._ready_agent_tools(frozen,indexed)
        assert allowed=={node["id"]}, (role,allowed)
        indexed[node["id"]]={"status":"running"}
        assert not runtime._ready_agent_tools(frozen,indexed), "a running tool must not trigger the next tool/agent"
        indexed[node["id"]]={"status":"completed","result":{"outputs":{p:{"type":t}for p,t in spec(role,node["options"])["outputs"].items()}}}
    assert not runtime._ready_agent_tools(frozen,indexed)
    indexed["transcription__transcribe"]={"status":"running","display_status":"held","display_reason":"응답 확인 실패"}
    assert not runtime._ready_agent_tools(frozen,indexed), "ambiguous model calls must never advance or replay"


def failed_request_is_not_normal_waiting():
    from video_service.postgres.task_logs import project_logs
    run={"id":"1"*32,"node_id":"speech","node_type":"transcribe","status":"running"}
    role={"phase":"held","held_reason":"model_reply_unknown","role":"transcription"}
    calls=[{"chunk_index":0,"status":"unknown","error_code":"outcome_unknown","created_at":None}]
    value=project_logs(run,role,calls)
    assert value["state"]=="held", "raw uncertainty must remain preserved"
    assert value.get("display_state")=="failed", "request error must be visibly failed, not ordinary waiting"
    assert role["phase"]=="held" and calls[0]["status"]=="unknown"
    role["phase"]="sent"
    assert project_logs(run,role,calls)["display_state"]=="failed", "a recorded unknown call must be an error even before the held receipt arrives"



def orchestration_has_its_own_source_layer():
    assert Execution.__module__=="mideagent_orchestrator.execution", "orchestrator implementation is still buried in shared"


def preparation_is_observation_driven():
    from mideagent_orchestrator.agent_view import project_agents
    from mideagent_orchestrator.workflow import default_definition,compile_definition
    from video_service.renewal_contracts import spec
    public=default_definition();compiled=compile_definition(public)
    snapshot={"definition":compiled["definition"],"agent_definition":public,"agent_tool_owners":compiled["owners"],"inputs":{}}
    job={"snapshot":snapshot,"generation":1,"status":"running"}
    runs=[]
    for n in compiled["definition"]["nodes"]:
        if compiled["owners"][n["id"]]!="transcription":continue
        runs.append({"id":n["id"],"node_id":n["id"],"node_type":n["type"],"status":"completed","result":{"outputs":{p:{"type":t}for p,t in spec(n["type"],n["options"])["outputs"].items()}}})
    plain=project_agents(job,runs,[],[])
    assert not plain["edges"], "no demand means no fabricated coldboot spinner"
    demand={"node_id":"translation__translate","role":"translation","node_run_id":None}
    observed=project_agents(job,runs,[demand],[{"role":"translation","phase":"starting","fresh":True,"error_code":None}])
    assert observed["nodes"][1]["state"]=="preparing"
    assert observed["edges"]["agent_flow_0"]["state"]=="preparing"
    native={"id":"b"*32,"node_id":"translation__translate","node_type":"translate","status":"running","dispatch":{"phase":"sent"},"result":None}
    started=project_agents(job,[*runs,native],[],[],{native["id"]:{"phase":"sent","started":True}})
    assert started["nodes"][1]["state"]=="running", "actual worker start must replace edge preparation with node execution"
    assert not started["edges"]

    failed=project_agents(job,runs,[demand],[{"role":"translation","phase":"error","fresh":True,"error_code":"start_failed"}])
    assert failed["nodes"][1]["state"]=="failed"
    assert not any(e["state"]=="preparing"for e in failed["edges"].values()), "startup error must stop the spinner"


def korean_goal_cannot_be_overridden_by_internal_tool_settings():
    from mideagent_orchestrator.workflow import default_definition,compile_definition
    public=default_definition()
    public["nodes"][1]["options"]={}
    public["nodes"][1]["tool_settings"]={"translate":{"target_language":"en"}}
    compiled=compile_definition(public)
    tool=next(n for n in compiled["definition"]["nodes"]if n["type"]=="translate")
    assert tool["options"]["target_language"]=="ko", "internal tool settings changed the public Korean translation goal"


def agent_drives_the_bound_tool_invoker():
    from mideagent_orchestrator.workflow import default_definition,compile_definition
    from mideagent_agents.catalog import CLASSES
    public=default_definition();compiled=compile_definition(public)
    agent=CLASSES[public["nodes"][0]["type"]](public["nodes"][0]);called=[]
    result=agent.advance({},compiled["definition"],lambda identity:called.append(identity)or "claimed")
    assert result=="claimed" and called==["transcription__analyze"]
    called.clear()
    assert agent.advance({"transcription__analyze":{"status":"failed"}},compiled["definition"],lambda identity:called.append(identity))is None
    assert not called,"a failed tool must not invoke/retry anything"


def native_valid_identifiers_are_preserved():
    from mideagent_orchestrator.workflow import default_definition,compile_definition
    public=default_definition();public["nodes"][0]["id"]="123abc"
    public["edges"][0]["source"]["node"]="123abc"
    public["edges"][0]["id"]="123abc_edge"
    try:compiled=compile_definition(public)
    except ValueError as exc:raise AssertionError("native-valid editor identifiers were rejected")from exc
    assert compiled["agent_definition"]["nodes"][0]["id"]=="123abc"


def command_delivery_failure_is_an_agent_error():
    from mideagent_orchestrator.agent_view import project_agents
    from mideagent_orchestrator.workflow import default_definition,compile_definition
    public=default_definition();compiled=compile_definition(public)
    job={"snapshot":{"definition":compiled["definition"],"agent_definition":public},"generation":1,"status":"running"}
    run={"id":"a"*32,"node_id":"transcription__analyze","node_type":"analyze","status":"running","dispatch":{"phase":"held"},"result":None}
    view=project_agents(job,[run],[],[])
    assert view["nodes"][0]["state"]=="failed", "unconfirmed command publication must not look running"
    from video_service.postgres.task_logs import project_logs
    assert project_logs(run,None,[])["display_state"]=="failed", "console panel must not override a failed command with running"



def transcription_only_does_not_add_translation_or_video_work():
    from mideagent_orchestrator.workflow import default_definition,compile_definition
    public=default_definition();public["nodes"]=public["nodes"][:1];public["edges"]=[]
    try:compiled=compile_definition(public)
    except ValueError as exc:raise AssertionError("a transcription-only agent flow should remain usable")from exc
    assert {n["type"]for n in compiled["definition"]["nodes"]}=={"analyze","extract_audio","preprocess_audio","transcribe"}


def legacy_conversion_requires_the_actual_matching_tool_wiring():
    from mideagent_orchestrator.workflow import default_definition,compile_definition,upgrade_legacy
    legacy=compile_definition(default_definition())["definition"]
    edge=next(e for e in legacy["edges"]if e["target"]["node"].endswith("__generate_subtitle"))
    edge["source"]["node"]="transcription__transcribe"
    try:upgrade_legacy(legacy)
    except ValueError:return
    raise AssertionError("a different historical data flow was silently reinterpreted")


def canonical_hashing_is_common_foundation_not_a_media_tool():
    from mideagent_media_tools.operations import canonical
    assert canonical.__module__=="video_service.canonical", "common contracts still depend on media-tool implementation for canonical hashing"

if __name__=="__main__":
    public_catalog_only_agents()
    owned_goal_flow()
    agent_controls_own_tools()
    failed_request_is_not_normal_waiting()
    orchestration_has_its_own_source_layer()
    preparation_is_observation_driven()
    korean_goal_cannot_be_overridden_by_internal_tool_settings()
    agent_drives_the_bound_tool_invoker()
    native_valid_identifiers_are_preserved()
    command_delivery_failure_is_an_agent_error()
    transcription_only_does_not_add_translation_or_video_work()
    legacy_conversion_requires_the_actual_matching_tool_wiring()
    canonical_hashing_is_common_foundation_not_a_media_tool()
    print("public catalog and goal-owned flow passed")
