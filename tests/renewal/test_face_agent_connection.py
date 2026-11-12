"""Face v3 SOURCE contracts; synthetic CAS/SQL/child boundaries, no GPU or services."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[2]
for project in ("packages/shared", "packages/tool-hub", "agents", "apps/orchestrator", "tools/gpu"):
    sys.path.insert(0, str(ROOT / project))
from video_service.canonical import digest
from video_service.engine_protocol import make_command, envelope, decode
OWNER = "a" * 32

def ref(kind, value="b", size=100):
    return dict(storage_key="blobs/"+value*64, sha256=value*64, bytes=size, type=kind)

def runtime():
    return dict(role="faceswap", family="gpu", engine="facefusion-3.9.0",
                model_sha256="c"*64, source_language=None, target_language=None,
                face_protocol=3)

def context():
    return dict(version=1, job_id="3"*32, snapshot_sha256="e"*64, goal_id="face",
                generation=1, source_asset_id="f"*32, target_asset_id="1"*32,
                source_owner_id=OWNER, target_owner_id=OWNER, output_owner_id=OWNER, source=ref("image"),
                target=ref("video", "2"), settings_revision=1,
                settings=dict(preset="fast", video_codec="h264", reference_frame=1, distance=0.6),
                runtime_revision=2, runtime_sha256=digest(runtime()),
                policy="face_operations_v1")

def command(role="face_analyze_source", **changes):
    values=dict(run_id="3"*32, attempt_id="4"*32, generation=1,
                inputs={"source":ref("image"), "video":ref("video", "2")},
                options={"context":context()}, runtime=runtime())
    values.update(changes)
    return make_command(role, **values)

def test_v3_first_analysis_uses_existing_engine_wire_dispatch():
    value=command()
    assert value["protocol_version"]==3
    wire=envelope(OWNER,value)
    assert wire.message_type=="agent.engine.command.v3"
    assert decode(wire,role="faceswap")["command"]==value
    assert value["agent"]["id"]=="face_analyze_source"


def test_actual_gpu_adapter_stages_one_explicit_analysis_operation(tmp_path, monkeypatch):
    import importlib.util, json, struct, zlib
    from types import ModuleType
    package=ModuleType("mideagent_gpu");package.__path__=[str(ROOT/"tools/gpu")]
    monkeypatch.setitem(sys.modules,"mideagent_gpu",package)
    from video_service.content_store import ContentStore
    from video_service.canonical import canonical
    spec=importlib.util.spec_from_file_location("mideagent_gpu.adapters",ROOT/"tools/gpu/adapters.py")
    adapter=importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    def chunk(kind,raw):
        return struct.pack(">I",len(raw))+kind+raw+struct.pack(">I",zlib.crc32(kind+raw)&0xffffffff)
    image=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",2,2,8,2,0,0,0))+chunk(b"IDAT",zlib.compress((b"\0"+b"\x20\x80\xc0"*2)*2))+chunk(b"IEND",b"")
    import os
    if os.name=="nt":
        original_chmod=Path.chmod
        monkeypatch.setattr(Path,"chmod",lambda path,mode,*a,**k: None if mode==0o400 and path.is_relative_to(tmp_path) else original_chmod(path,mode,*a,**k))
    (tmp_path/"cas").mkdir()
    store=ContentStore(tmp_path/"cas")
    ctx=context();ctx["source"]=store.put(OWNER,[image],"image");ctx["target"]=store.put(OWNER,[b"offline video placeholder; probe boundary mocked"],"video")
    value=command(inputs={"source":ctx["source"],"video":ctx["target"]},options={"context":ctx})
    calls=[]
    def child(argv,work):
        request=json.loads(Path(argv[-1]).read_bytes());calls.append(request)
        output=Path(request["output"]);output.mkdir()
        (output/"original.png").write_bytes(image);(output/"face_0.png").write_bytes(image)
        (output/"result.json").write_bytes(canonical(dict(width=2,height=2,faces=[dict(position=0,bbox=[0,0,1,1],file="face_0.png")])))
    monkeypatch.setattr(adapter,"child",child)
    # Decoder/probe is a labelled external metadata boundary, never real user video.
    sys.path.insert(0,str(ROOT/"tools/media"))
    from mideagent_media_tools import operations
    monkeypatch.setattr(operations,"probe",lambda *a,**k:dict(duration=12,width=640,height=360))
    outputs=adapter.execute(store,OWNER,value,dict(python=sys.executable,model_dir=str(tmp_path),descriptor=runtime()))
    document=json.loads(outputs["analysis"][0])
    assert [c["operation"] for c in calls]==["analyze_source"]
    assert calls[0]["source"].endswith("source.media")
    assert document["version"]==1 and document["operation"]=="analyze_source"
    assert document["context_sha256"]==digest(ctx) and document["request_sha256"]==digest(value)
    assert document["faces"][0]["position"]==0 and document["faces"][0]["image"]["type"]=="image"
    assert "approved" not in document


def public_definition():
    return dict(catalog_version=2,revision=1,name="얼굴 합성",input_profile="face_workflow_v1",
                inputs={"photo":"image"},nodes=[dict(id="face",type="faceswap_agent",position=dict(x=0,y=0),options={})],edges=[])

def test_real_compiler_owns_seven_steps_and_only_final_publication():
    from mideagent_orchestrator.workflow import compile_definition
    from mideagent_agents.catalog import CLASSES
    plan=compile_definition(public_definition())
    native=plan["definition"]
    roles=[n["type"] for n in native["nodes"]]
    assert roles==["face_analyze_source","face_analyze_reference","face_select","face_preview","face_confirm_preview","face_render","validate_video"]
    assert native["inputs"]=={"video":"video","photo":"image"}
    assert set(plan["owners"].values())=={"face"}
    assert set(plan["outputs"]["face"])=={"video","report"}
    agent=CLASSES["faceswap_agent"](public_definition()["nodes"][0])
    assert agent.next_tool({},native)==dict(state="ready",tool="face__face_analyze_source")
    from mideagent_agents.registry import registration
    assert registration("faceswap",node=public_definition()["nodes"][0])["runtime_roles"]==roles


from test_goal_corrections import source_execution
from test_goal_recovery_policy import recovery_runtime, historical_chain
from test_saved_subtitle_render import connected
from types import SimpleNamespace, MethodType, ModuleType
from contextlib import contextmanager
import ast

@pytest.fixture
def state(tmp_path,monkeypatch):
    import os
    from video_service.content_store import ContentStore
    chmod=Path.chmod
    if os.name=="nt": monkeypatch.setattr(Path,"chmod",lambda path,mode,*a,**k: None if mode==0o400 and path.is_relative_to(tmp_path) else chmod(path,mode,*a,**k))
    return SimpleNamespace(store=ContentStore(tmp_path))

@pytest.fixture
def face_runtime(connected,monkeypatch):
    r,_,parent=connected
    from test_face_input_preparation import png
    from video_service.image_original import framing,policy
    image=png();pref=r.store.put(OWNER,[image],"image");vref=r.store.put("c"*32,[b"synthetic target, never decoded"],"video")
    assets={"f"*32:dict(id="f"*32,owner_id=OWNER,filename="source unchanged.png",sha256=pref["sha256"],bytes=pref["bytes"],metadata=dict(registration_state="verified",media_type="image/png",media=framing(image),image_original_policy=policy())),
            "1"*32:dict(id="1"*32,owner_id="c"*32,filename="target unchanged.mp4",sha256=vref["sha256"],bytes=vref["bytes"],metadata=dict(registration_state="verified",media=dict(duration=12,width=640,height=360)))}
    definition=public_definition()
    r._shared_asset=lambda db,identity:deepcopy(assets[identity])
    from datetime import datetime,timezone
    for asset in assets.values():
        asset.update(created_at=datetime.now(timezone.utc),storage_key='sha256:'+asset['sha256'])
    from test_audio_original_input import intake_methods
    intake=intake_methods({'asset_reference'})
    r.asset_reference=intake['asset_reference']
    r.create.__func__.__globals__['public_asset']=intake['public_asset']
    r._job_definition=lambda *a:(OWNER,deepcopy(definition));r.job_definition=lambda *a:deepcopy(definition)
    row=dict(role="faceswap",revision=2,sha256=digest(runtime()),descriptor=runtime(),enabled=True)
    module=ModuleType("video_service.postgres.engine_runtimes")
    module.EngineRuntimes=SimpleNamespace(resolve_in=lambda db,role,**kw:deepcopy(row) if role=="faceswap" and kw.get("sha256",row["sha256"])==row["sha256"] else (_ for _ in ()).throw(ValueError("engine_unavailable_or_pin_changed")))
    monkeypatch.setitem(sys.modules,module.__name__,module)
    tree=ast.parse((ROOT/"apps/orchestrator/mideagent_orchestrator/execution.py").read_text(encoding="utf8"))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="Execution")
    names={"_engine_bindings","_engine_role","_execution_reasons","_preflight_cpu_inputs","_checked_input","_plan","_review","_shared_job","review_save","review_confirm"}
    env=dict(r.create.__func__.__globals__);env.update(resource_id=lambda value:value,Missing=LookupError,public=deepcopy);env["CONTROL"]=frozenset({"face_select","face_confirm_preview"})
    for original in cls.body:
        if isinstance(original,ast.FunctionDef) and original.name in names:
            node=deepcopy(original);node.decorator_list=[]
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(ROOT/"apps/orchestrator/mideagent_orchestrator/execution.py"),"exec"),env)
            setattr(r,node.name,env[node.name] if node.name=="_engine_role" else MethodType(env[node.name],r))
    pg=ModuleType("video_service.postgres");pg.__path__=[str(ROOT/"packages/shared/video_service/postgres")];pg.Conflict=type("Conflict",(ValueError,),{});pg.Missing=type("Missing",(LookupError,),{});monkeypatch.setitem(sys.modules,pg.__name__,pg)
    from video_service.postgres.ticket_artifacts import TicketArtifacts
    # Exact pure registry ID function without importing unrelated model packages.
    import re
    registry_path=ROOT/'packages/shared/video_service/postgres/registry.py'
    registry_tree=ast.parse(registry_path.read_text(encoding='utf8'))
    resource=next(n for n in registry_tree.body if isinstance(n,ast.FunctionDef) and n.name=='resource_id')
    registry=ModuleType('video_service.postgres.registry');registry.__dict__['re']=re
    exec(compile(ast.Module(body=[resource],type_ignores=[]),str(registry_path),'exec'),registry.__dict__)
    monkeypatch.setitem(sys.modules,registry.__name__,registry)
    r.engine_runtime_enabled=True;r.ticket_artifacts=TicketArtifacts(r.store)
    previous=r.database.execute
    reviews=[]
    def sql(query,params=()):
        if query.startswith("SELECT * FROM jobs WHERE id=%s LIMIT 2 FOR UPDATE"):
            return SimpleNamespace(fetchall=lambda:[deepcopy(r.database.jobs[params[0]])] if params[0] in r.database.jobs else [])
        if query.startswith("SELECT * FROM review_tasks WHERE owner_id=%s AND id=%s"):
            return SimpleNamespace(fetchone=lambda:next((deepcopy(row) for row in reviews if row['owner_id']==params[0] and row['id']==params[1]),None))
        if query.startswith("SELECT * FROM review_tasks WHERE id=%s LIMIT 2"):
            return SimpleNamespace(fetchall=lambda:deepcopy([row for row in reviews if row['id']==params[0]][:2]))
        if query.startswith("SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s ORDER BY id"):
            return SimpleNamespace(fetchall=lambda:deepcopy(sorted(r.database.runs[params[1]],key=lambda row:row["id"])))
        if query.startswith("SELECT * FROM review_tasks") or query.startswith("SELECT id,revision,status,confirmed_sha256 FROM review_tasks"):
            return SimpleNamespace(fetchall=lambda:deepcopy(reviews))
        if query.startswith("SELECT extract(epoch"):
            import time
            return SimpleNamespace(fetchone=lambda:{"epoch":int(time.time())})
        if query.startswith("INSERT INTO review_tasks"):
            row=dict(owner_id=params[0],job_id=params[1],node_run_id=params[2],id=params[3],revision=1,contract=deepcopy(params[4]),draft=deepcopy(params[5]),status="draft",confirmed_sha256=None);reviews.append(row)
            return SimpleNamespace(fetchone=lambda:row)
        if query.startswith("INSERT INTO review_revisions"): return SimpleNamespace(fetchone=lambda:None)
        if query.startswith("UPDATE review_tasks SET revision"):
            row=next(row for row in reviews if row["id"]==params[3]);row.update(revision=params[0],draft=deepcopy(params[1]),status="draft")
            return SimpleNamespace(fetchone=lambda:deepcopy(row))
        if query.startswith("UPDATE review_tasks SET status='confirmed'"):
            next(row for row in reviews if row["id"]==params[2]).update(status="confirmed",confirmed_sha256=params[0]);return SimpleNamespace(fetchone=lambda:None)
        if query.startswith("UPDATE node_runs SET status='completed'"):
            from datetime import datetime,timezone
            next(row for row in r.database.runs[params[2]] if row["id"]==params[3]).update(status="completed",result=deepcopy(params[0]),completed_at=datetime.now(timezone.utc));return SimpleNamespace(fetchone=lambda:None)
        if query.startswith("UPDATE jobs SET active_claim_id=NULL"):
            r.database.jobs[params[1]]["active_claim_id"]=None;return SimpleNamespace(fetchone=lambda:None)
        if query.startswith("UPDATE jobs SET status=%s"):
            r.database.jobs[params[2]]["status"]=params[0];return SimpleNamespace(fetchone=lambda:None)
        if query.startswith("UPDATE jobs SET revision="): return SimpleNamespace(fetchone=lambda:None)
        if query.startswith("INSERT INTO message_outbox"):
            r.database.outbox.append(params);return SimpleNamespace(fetchone=lambda:None)
        if query.startswith("UPDATE jobs SET status=CASE"):
            r.database.jobs[params[1]]["status"]="running";return SimpleNamespace(fetchone=lambda:None)
        result=previous(query,params)
        if query.startswith("INSERT INTO jobs"):
            row=result.fetchone();row.update(ticket_number=100+len(r.database.children),asset_owner_id=row["snapshot"]["asset"]["uploaded_by"])
        return result
    r.database.execute=sql
    queue=ModuleType("mideagent_orchestrator.start_queue")
    queue.StartQueue=lambda _:SimpleNamespace(lock_in=lambda *a:None,requires_in=lambda *a:False,allowed_in=lambda *a,**k:True)
    monkeypatch.setitem(sys.modules,queue.__name__,queue)
    r.create.__func__.__globals__["CONTROL"]=env["CONTROL"]
    return SimpleNamespace(runtime=r,assets=assets,engine=row,definition=definition,parent=parent,reviews=reviews)

def test_actual_create_plan_checked_input_first_claim_face_only(face_runtime,monkeypatch):
    fixture=face_runtime;r=fixture.runtime
    options={"face_input":dict(photo_asset_id="f"*32,engine_revision=2,engine_sha256=fixture.engine["sha256"],settings_revision=1,reference_frame=1)}
    planned=r.normal_input_plan("b"*32,"1"*32,fixture.definition,options)
    child=r.create("b"*32,asset_id="1"*32,definition_id=fixture.parent["workflow_id"],definition_revision=1,options=options,request_id="offline-face-create",input_plan_sha256=digest(planned["bindings"]))
    child["revision"]=1;r.database.jobs[child["id"]]=child
    assert child["asset_id"]=="1"*32 and child["workflow_owner_id"]==OWNER
    assert child["snapshot"]["inputs"]["photo"]["source_owner_id"]==OWNER
    assert child["snapshot"]["inputs"]["video"]["source_owner_id"]=="c"*32
    monkeypatch.setattr(r.store,"put",lambda *a,**k:pytest.fail("planning/first analysis staged CAS"))
    verified=r._preflight_cpu_inputs("b"*32,child["id"])
    result=r._plan(r.database,child,verified)
    assert result["ready"],result["reasons"]
    assert result["paid_roles"]==[]
    child.update(status="waiting",active_claim_id="9"*32)
    value=r.claim_next("b"*32,child["id"])
    assert value["protocol_version"]==3 and value["agent"]["id"]=="face_analyze_source"
    assert value["options"]["context"]["snapshot_sha256"]==child["snapshot_sha256"]
    assert len(r.database.runs[child["id"]])==1
    assert set(value["options"])=={"context"}
    assert len(r.database.outbox)==1 and r.database.outbox[0][3]=="agent.engine.command.v3"


def create_draft(fixture):
    r=fixture.runtime
    options={"face_input":dict(photo_asset_id="f"*32,engine_revision=2,engine_sha256=fixture.engine["sha256"],settings_revision=1,reference_frame=1)}
    planned=r.normal_input_plan("b"*32,"1"*32,fixture.definition,options)
    child=r.create("b"*32,asset_id="1"*32,definition_id=fixture.parent["workflow_id"],definition_revision=1,options=options,request_id="offline-face-chain",input_plan_sha256=digest(planned["bindings"]))
    child["revision"]=1;r.database.jobs[child["id"]]=child
    return child


def attach_immutable_worker_store(store,monkeypatch):
    # Actual production read-only accessor, fake S3 immutable objects only.
    from video_service.object_store import S3ContentStore
    records={};reads=[]
    def claim(owner,command):
        key=(owner,command["attempt_id"])
        if key in records: raise ValueError("no automatic retry in fixture")
        records[key]={"claim.json":{"request_sha256":digest(command)}}
    def finish(owner,command,result):
        records[(owner,command["attempt_id"])]["result.json"]=deepcopy(result)
    def read(owner,attempt,name):
        reads.append((owner,attempt,name));return deepcopy(records[(owner,attempt)][name])
    monkeypatch.setattr(store,"claim_attempt",claim,raising=False)
    monkeypatch.setattr(store,"finish_attempt",finish,raising=False)
    monkeypatch.setattr(store,"_attempt_json",read,raising=False)
    monkeypatch.setattr(store,"read_attempt_result",MethodType(S3ContentStore.read_attempt_result,store),raising=False)
    return records,reads


def test_agent_chain_accepted_analysis_selection_preview_confirmation_render_only(face_runtime,tmp_path,monkeypatch):
    """Real source chain and TicketArtifacts; SQL acceptance/child are OFFLINE fixtures.

    No encoder, FFmpeg, native model, PG or S3 connection is invoked. The output
    video bytes and final CPU validator response are explicitly synthetic.
    """
    import json,importlib.util,time
    from datetime import datetime,timezone
    from test_face_input_preparation import png
    from video_service.canonical import canonical
    from video_service.engine_object_agent import EngineObjectExecutor
    from video_service.engine_service import EngineHandler
    from mideagent_orchestrator.face_workflow import FaceWorkflow
    from mideagent_agents.catalog import CLASSES
    from mideagent_tool_hub.registry import allowed_definitions
    r=face_runtime.runtime;child=create_draft(face_runtime);owner=child["owner_id"]
    monkeypatch.setattr(__import__('mideagent_orchestrator.face_workflow',fromlist=['sql_json']),'sql_json',deepcopy)
    records,reads=attach_immutable_worker_store(r.store,monkeypatch)
    package=ModuleType("mideagent_gpu");package.__path__=[str(ROOT/"tools/gpu")];monkeypatch.setitem(sys.modules,"mideagent_gpu",package)
    spec=importlib.util.spec_from_file_location("mideagent_gpu.adapters",ROOT/"tools/gpu/adapters.py")
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter);monkeypatch.setitem(sys.modules,spec.name,adapter)
    calls=[]
    def native_child(argv,work):
        request=json.loads(Path(argv[-1]).read_bytes());calls.append(request["operation"])
        assert Path(argv[1]).name=="facefusion.py" and "--request" in argv
        out=Path(request["output"]);out.mkdir()
        if request["operation"]=="render":
            (out/"final.mp4").write_bytes(b"offline synthetic video, never encoded")
            result={"file":"final.mp4"}
        else:
            for name in ("original.png","face_0.png","preview.png"): (out/name).write_bytes(png())
            result=dict(width=8,height=4,faces=[dict(position=0,bbox=[0,0,1,1],file="face_0.png")])
            if request["operation"]!="analyze_source": result.update(frame_number=1,frame_count=288,fps=24)
            if request["operation"]=="preview": result.update(matched_faces=1,timings_ms={"offline_fixture":1})
        (out/"result.json").write_bytes(canonical(result))
    monkeypatch.setattr(adapter,"child",native_child)
    from mideagent_media_tools import operations
    monkeypatch.setattr(operations,"probe",lambda *a,**k:dict(duration=12,width=640,height=360))
    handler=EngineHandler("faceswap",EngineObjectExecutor(r.store,dict(descriptor=runtime(),model_dir=str(tmp_path),python=sys.executable)))
    flow=FaceWorkflow(r)
    def start():
        child.update(status="draft" if not r.database.runs[child["id"]] else "review_required")
        stage=r._preflight_cpu_inputs(owner,child["id"])
        plan=r._plan(r.database,child,stage);assert plan["ready"],plan["reasons"]
        child.update(status="waiting",active_claim_id="9"*32)
    def execute_next():
        command=r.claim_next(owner,child["id"])
        assert command is not None
        schema=next(d for d in allowed_definitions("agent:faceswap") if d['executor']==command['agent']['id'])['args_schema']
        schema.model_validate(command['inputs'])
        result=decode(handler(envelope(owner,command)),result=True)["result"]
        assert result["status"]=="completed",result
        flow.result_preflight(owner,command,result)
        lookup=r._job
        def unlocked_job(*args,**kwargs):
            assert not kwargs.get('lock'), 'result materialization held the job lock'
            return lookup(*args,**kwargs)
        with monkeypatch.context() as unlocked:
            unlocked.setattr(r,'_job',unlocked_job)
            ticket_stage=flow.stage_result(owner,command,result)
        flow.check_stage(child,r.database.runs[child['id']],ticket_stage)
        assert ticket_stage['receipt']['outputs']==result['outputs']
        # Explicit accepted SQL fixture at the receiver boundary, never a real record.
        row=r.database.runs[child["id"]][-1];row.update(status="completed",result=deepcopy(ticket_stage["receipt"]),completed_at=datetime.now(timezone.utc))
        return command,result
    start();execute_next();execute_next()
    assert calls==["analyze_source","analyze_reference"]
    assert r.claim_next(owner,child["id"]) is None
    assert child["status"]=="review_required" and len(face_runtime.reviews)==1
    from mideagent_orchestrator.agent_view import project_agents
    projected=project_agents(child,r.database.runs[child["id"]],[],[])
    assert projected["nodes"][0]["state"]=="review_required"
    assert projected["nodes"][0]["selected_tool_id"]=="face__face_select"
    review=face_runtime.reviews[0]
    assert flow.image(owner,review["id"],"source",0).read_bytes()==png()
    viewer='8'*32
    assert flow.image(viewer,review['id'],'source',0).read_bytes()==png()
    assert flow.image(viewer,review['id'],'reference',0).read_bytes()==png()
    with pytest.raises(LookupError): flow.save_review(viewer,review['id'],1,{'source_position':0,'face_position':0})
    with pytest.raises(LookupError): flow.confirm_review(viewer,review['id'],1)
    assert_review_image_http(r,viewer,review['id'],['source','reference'])
    with pytest.raises(LookupError): flow.image(viewer,'7'*32,'source',0)
    for group,index in [('unknown',0),('source',127),('source',True)]:
        with pytest.raises(ValueError): flow.image(viewer,review['id'],group,index)
    original_review=deepcopy(review)
    review['node_run_id']='7'*32
    with pytest.raises(LookupError): flow.image(viewer,review['id'],'source',0)
    review.clear();review.update(deepcopy(original_review))
    review['contract']['source']['faces'][0]['image']['type']='video'
    with pytest.raises(ValueError): flow.image(viewer,review['id'],'source',0)
    review.clear();review.update(original_review)
    assert review["draft"]=={"source_position":None,"face_position":None}
    with pytest.raises(ValueError): flow.save_review(owner,review['id'],1,{"approved":True})
    with pytest.raises(ValueError): flow.save_review(owner,review['id'],1,{"source_position":0,"face_position":1})
    saved=flow.save_review(owner,review['id'],1,{"source_position":0,"face_position":0})
    flow.confirm_review(owner,review['id'],saved['revision'])
    assert child['active_claim_id'] is None and calls==["analyze_source","analyze_reference"]
    start();preview_command,preview_result=execute_next()
    assert calls[-1]=='preview'
    assert r.claim_next(owner,child['id']) is None and child['status']=='review_required'
    confirmation=face_runtime.reviews[-1]
    assert flow.image(viewer,confirmation['id'],'preview',0).read_bytes()==png()
    assert_review_image_http(r,viewer,confirmation['id'],['preview'])
    with pytest.raises(ValueError): flow.confirm_review(owner,confirmation['id'],1)
    with pytest.raises(ValueError): flow.save_review(owner,confirmation['id'],1,{'approved':True})
    saved=flow.save_review(owner,confirmation['id'],1,{'confirmed':True})
    flow.confirm_review(owner,confirmation['id'],saved['revision'])
    assert calls.count('render')==0
    with monkeypatch.context() as clock:
        clock.setattr(time,'time',lambda:10**10)
        expired_plan=r._plan(r.database,child,r._preflight_cpu_inputs(owner,child['id']))
        assert not expired_plan['ready'] and any('만료' in message for message in expired_plan['reasons'])
    start();render_command,render_result=execute_next()
    assert calls==['analyze_source','analyze_reference','preview','render']
    assert render_command['options']['approval']['preview_sha256']==preview_result['outputs']['preview']['sha256']
    assert render_command['options']['selection']['source_position']==0
    validation=r.claim_next(owner,child['id'])
    assert validation['agent']['id']=='validate_video' and validation['inputs']['video']==render_result['outputs']['video']
    report=r.store.put(owner,[canonical({'offline_fixture':True,'validation_not_executed':True})],'validation_report')
    validation_run=r.database.runs[child['id']][-1]
    validation_receipt=r.ticket_artifacts.capture(r.database,child,validation_run,{'outputs':{'report':report}})
    validation_run.update(status='completed',result=validation_receipt,completed_at=datetime.now(timezone.utc))
    assert r.claim_next(owner,child['id']) is None and child['status']=='completed'
    agent=CLASSES['faceswap_agent'](face_runtime.definition['nodes'][0])
    assert agent.next_tool({n['node_id']:n for n in r.database.runs[child['id']]},child['snapshot']['definition'])['state']=='completed'
    publication=project_agents(child,r.database.runs[child["id"]],[],[])
    assert {item["name"] for item in publication["nodes"][0]["outputs"]}=={"video","report"}
    assert all("storage_key" not in item for item in publication["nodes"][0]["outputs"])
    assert len(records)==4 and reads
    # CAS or a worker result alone never grants SQL acceptance.
    first=r.database.runs[child['id']][0];original=deepcopy(first)
    first['result']['outputs']['analysis']=ref('face_analysis','9')
    with pytest.raises(ValueError): flow.preflight(owner,child['id'])
    first.clear();first.update(original)
    for rejected in ('failed','quarantined','running'):
        first['status']=rejected
        with pytest.raises((ValueError,KeyError)): flow.preflight(owner,child['id'])
    first.clear();first.update(original)
    with pytest.raises(ValueError): flow.save_review(owner,review['id'],1,{'source_position':0,'face_position':0})
    assert len(calls)==4
    # Expiry must not rewrite an already completed render or restart any stage.
    before=deepcopy(child);monkeypatch.setattr(time,'time',lambda:10**10)
    flow.preflight(owner,child['id']);assert child==before and len(calls)==4
    from mideagent_gpu.face_operations import execute as native_operation
    with pytest.raises(ValueError,match='unexpired'):
        native_operation(r.store,owner,render_command,dict(descriptor=runtime(),python=sys.executable,model_dir=str(tmp_path)),tmp_path/'not-executed',child=lambda *a:pytest.fail('expired approval launched a child'))


@pytest.mark.parametrize('change', ['extra','type','origin','v2_runtime','wrong_role','approved'])
def test_v3_wire_refuses_unsupported_or_client_authority(change):
    value=command()
    if change=='extra': value['options']['context']['actor']='f'*32
    if change=='type': value['inputs']['source']['type']='video'
    if change=='origin': value['inputs']['source']['source_owner_id']='f'*32
    if change=='v2_runtime': value['runtime'].pop('face_protocol')
    if change=='wrong_role': value['agent']['id']='translate'
    if change=='approved': value['options']['approved']=True
    with pytest.raises(ValueError): envelope(OWNER,value)


def test_v2_face_and_model_wire_stays_exact():
    descriptor=runtime();descriptor.pop('face_protocol')
    value=make_command('faceswap',run_id='3'*32,attempt_id='4'*32,generation=1,
        inputs={'video':ref('video'),'session':ref('faceswap_session'),'preview':ref('faceswap_preview')},options={'preset':'fast','video_codec':'h264'},runtime=descriptor)
    assert value['protocol_version']==2 and envelope(OWNER,value).message_type=='agent.engine.command.v2'
    assert decode(envelope(OWNER,value),role='faceswap')['command']==value
    with pytest.raises(ValueError): decode(envelope(OWNER,value),role='transcribe')
    assert set(value)=={'protocol_version','run_id','attempt_id','generation','agent','inputs','options','runtime'}


def test_old_descriptor_holds_first_analysis_without_staging_or_claim(face_runtime,monkeypatch):
    r=face_runtime.runtime
    face_runtime.engine['descriptor'].pop('face_protocol');face_runtime.engine['sha256']=digest(face_runtime.engine['descriptor'])
    opts={'face_input':dict(photo_asset_id='f'*32,engine_revision=2,engine_sha256=face_runtime.engine['sha256'],settings_revision=1,reference_frame=1)}
    child=r.create('b'*32,asset_id='1'*32,definition_id=face_runtime.parent['workflow_id'],definition_revision=1,options=opts,request_id='offline-v2-held')
    child['revision']=1;r.database.jobs[child['id']]=child
    monkeypatch.setattr(r.store,'put',lambda *a,**k:pytest.fail('planning staged content'))
    plan=r._plan(r.database,child,r._preflight_cpu_inputs('b'*32,child['id']))
    assert not plan['ready'] and any('단계별 얼굴 합성' in reason for reason in plan['reasons'])
    assert not r.database.runs[child['id']] and not r.database.outbox


@pytest.mark.parametrize('change',['missing_photo','wrong_type','custodian','engine','settings'])
def test_frozen_face_input_and_context_are_rechecked(face_runtime,change):
    from mideagent_orchestrator.face_workflow import frozen
    child=create_draft(face_runtime);snapshot=child['snapshot']
    if change=='missing_photo': snapshot['inputs'].pop('photo')
    if change=='wrong_type': snapshot['inputs']['photo']['type']='video'
    if change=='custodian': snapshot['inputs']['photo']['source_owner_id']='9'*32
    if change=='engine': snapshot['engine_bindings']['face__face_preview']['revision']+=1
    if change=='settings': snapshot['normal_input_bindings']['photo']['settings']['preset']='quality'
    with pytest.raises(ValueError): frozen(snapshot,child['owner_id'])


def test_actual_cli_argument_construction_accepts_analysis_without_face_selection(tmp_path):
    """Execute only the actual CLI list expression, never main/model imports/child."""
    import importlib.util
    path=ROOT/'tools/gpu/facefusion.py'
    module_spec=importlib.util.spec_from_file_location('face_cli_source_only',path)
    cli=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(cli)
    tree=ast.parse(path.read_text(encoding='utf8'))
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    assignment=next(n for n in ast.walk(main) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='cli' for t in n.targets))
    request={'face_protocol':3,'operation':'analyze_source','settings':context()['settings']}
    settings_spec=importlib.util.spec_from_file_location('face_operations_source_only',ROOT/'tools/gpu/face_operations.py')
    settings_module=importlib.util.module_from_spec(settings_spec);settings_spec.loader.exec_module(settings_module)
    private_settings=settings_module.cli_settings('face_analyze_source',request['settings'])
    env={**cli.__dict__,'request':request,'settings':private_settings,'version':'3.9.0','boost':'256x256','config_path':tmp_path/'not-written.ini'}
    exec(compile(ast.Module(body=[assignment],type_ignores=[]),str(path),'exec'),env)
    assert '--reference-face-position' in env['cli']
    assert private_settings['face_position']==0  # inactive legacy parser input only
    assert 'source_position' not in request['settings'] and 'face_position' not in request['settings']


def test_actual_definition_save_reopen_restore_keeps_new_face_profile(monkeypatch):
    from test_audio_original_input import intake_methods
    from video_service.renewal_contracts import validate
    from video_service.editor_contracts import resolve_editor_contracts
    from mideagent_orchestrator.workflow import upgrade_legacy,compile_definition
    namespace=intake_methods({'save_definition','restore_definition'})
    namespace.update(validate=validate,resolve_editor_contracts=resolve_editor_contracts,upgrade_legacy=upgrade_legacy)
    saved=[];head={'revision':0,'library_removed_at':None}
    class DB:
        @contextmanager
        def connection(self): yield self
        def execute(self,query,params):
            if query.startswith('INSERT INTO workflows'): return SimpleNamespace(fetchone=lambda:None)
            if query.startswith('SELECT revision,library_removed_at FROM workflows'): return SimpleNamespace(fetchone=lambda:deepcopy(head))
            if query.startswith('INSERT INTO workflow_revisions'): saved.append({'definition':deepcopy(params[4]),'sha256':params[5],'provenance':deepcopy(params[6])})
            elif query.startswith('UPDATE workflows'): head['revision']=params[0]
            else: raise AssertionError(query)
            return SimpleNamespace(fetchone=lambda:None)
    r=SimpleNamespace(database=DB(),_bindings=lambda *a,**k:{})
    r.save_definition=MethodType(namespace['save_definition'],r)
    r.restore_definition=MethodType(namespace['restore_definition'],r)
    r.definition=lambda owner,identity,revision=None:deepcopy(saved[(revision or head['revision'])-1]['definition'])
    public=public_definition();public['revision']=0
    first=r.save_definition(OWNER,'d'*32,public)
    assert first['input_profile']=='face_workflow_v1' and head['revision']==1
    before=deepcopy(saved[0])
    restored=r.restore_definition(OWNER,'d'*32,1,1)
    assert restored['revision']==2 and restored['input_profile']=='face_workflow_v1'
    assert compile_definition(restored)['definition']['inputs']=={'video':'video','photo':'image'}
    assert saved[0]==before and saved[-1]['provenance']=={'kind':'definition_revision','revision':1,'sha256':digest(first)}


def test_actual_http_definition_model_accepts_only_supported_face_profile():
    from pydantic import BaseModel,ConfigDict,Field,StrictInt
    from typing import Literal
    tree=ast.parse((ROOT/'apps/api/app/renewal_routes.py').read_text(encoding='utf8'))
    definition=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Definition')
    class Body(BaseModel): model_config=ConfigDict(extra='forbid',strict=True)
    env=dict(Body=Body,Field=Field,StrictInt=StrictInt,Literal=Literal)
    exec(compile(ast.Module(body=[definition],type_ignores=[]),'real-renewal-definition-body','exec'),env)
    payload=env['Definition'](**public_definition()).model_dump(exclude_none=True)
    assert payload['input_profile']=='face_workflow_v1'
    with pytest.raises(ValueError): env['Definition'](**{**payload,'input_profile':'invented_face'})


def test_actual_work_entry_preview_and_create_pin_face_inputs_and_stale_token(face_runtime,monkeypatch):
    from test_normal_inputs import mount_actual_input_handlers
    r=face_runtime.runtime;actual_public=r.create.__func__.__globals__['public_asset']
    r.asset=lambda actor,identity:actual_public(face_runtime.assets[identity])
    r.asset_path=lambda actor,identity:r.store.path(face_runtime.assets[identity]['owner_id'],r.asset_reference(face_runtime.assets[identity]))
    handlers=mount_actual_input_handlers(r)
    args=dict(asset_id='1'*32,definition_id=face_runtime.parent['workflow_id'],definition_revision=1,
              options={'face_input':dict(photo_asset_id='f'*32,engine_revision=2,engine_sha256=face_runtime.engine['sha256'],settings_revision=1,reference_frame=1)})
    monkeypatch.setattr(r.store,'put',lambda *a,**k:pytest.fail('inspect/preview/photo create staged CAS'))
    preview=handlers['preview'](handlers['Selection'](**args),'b'*32)
    assert preview['paid_roles']==[] and preview['selected_inputs'][0]['input']=='photo'
    assert not r.database.children and not r.database.outbox
    other=deepcopy(args);other['options']['face_input']['reference_frame']=2
    with pytest.raises(ValueError): handlers['create'](handlers['Create'](**other,token=preview['token'],request_id='offline-stale-face'),'b'*32)
    assert not r.database.children
    child=handlers['create'](handlers['Create'](**args,token=preview['token'],request_id='offline-face-route'),'b'*32)
    assert child['status']=='draft' and child['active_claim_id'] is None
    assert child['snapshot']['normal_input_bindings']['photo']['settings']['reference_frame']==1
    assert child['snapshot']['asset']['asset_id']=='1'*32 and child['snapshot']['asset']['uploaded_by']=='c'*32
    assert child['snapshot']['face_operation_policy']['operation_limits']=={'analyze_source':1,'analyze_reference':1,'preview':1,'render':1}


@pytest.mark.parametrize('bad',['extra_actor','absent_engine_sha','mismatched_revision'])
def test_face_selector_never_infers_an_engine_or_accepts_client_authority(face_runtime,bad):
    r=face_runtime.runtime
    selected=dict(photo_asset_id='f'*32,engine_revision=2,engine_sha256=face_runtime.engine['sha256'],settings_revision=1,reference_frame=1)
    if bad=='extra_actor': selected['actor']='9'*32
    if bad=='absent_engine_sha': selected['engine_sha256']=None
    if bad=='mismatched_revision': selected['engine_revision']=1
    with pytest.raises(ValueError): r.normal_input_plan('b'*32,'1'*32,face_runtime.definition,{'face_input':selected})
    assert not r.database.children and not r.database.outbox


def test_face_stage_change_and_cancel_do_not_reserve_or_publish(face_runtime):
    from mideagent_orchestrator.face_workflow import FaceWorkflow
    r=face_runtime.runtime;child=create_draft(face_runtime)
    stage=r._preflight_cpu_inputs('b'*32,child['id'])
    child['generation']+=1
    with pytest.raises(ValueError): FaceWorkflow.check_stage(child,[],stage['face'])
    child.update(status='waiting',active_claim_id='9'*32,cancel_requested=True)
    assert r.claim_next('b'*32,child['id']) is None
    assert not r.database.runs[child['id']] and not r.database.outbox


def test_existing_review_routes_keep_session_csrf_origin_and_strict_bodies(state):
    """Actual session/request middleware + route/model AST; domain tested above."""
    import inspect
    from fastapi.responses import FileResponse
    from pydantic import BaseModel,ConfigDict,Field,StrictInt
    from test_face_input_preparation import face_app,call_face
    calls=[]
    runtime=SimpleNamespace(store=state.store,review_save=lambda *a:calls.append(a) or {'revision':2},review_confirm=lambda *a:calls.append(a) or {'status':'confirmed'})
    app=face_app(runtime)
    route=next(r for r in app.routes if getattr(r,'path','')=='/api/work-entry/faceswap-inputs')
    dependency=inspect.signature(route.endpoint).parameters['actor'].default
    class Body(BaseModel): model_config=ConfigDict(extra='forbid',strict=True)
    env=dict(app=app,runtime=runtime,owner_dependency=dependency,Body=Body,Field=Field,StrictInt=StrictInt,FileResponse=FileResponse)
    tree=ast.parse((ROOT/'apps/api/app/renewal_routes.py').read_text(encoding='utf8'))
    definitions=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in {'Review','Revision'}]
    mount=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='mount_runtime')
    handlers=[n for n in mount.body if isinstance(n,ast.FunctionDef) and n.name in {'face_review_image','review_save','review_confirm'}]
    exec(compile(ast.Module(body=[*definitions,*handlers],type_ignores=[]),'real-face-review-http','exec'),env)
    path='/api/renewal/reviews/'+'f'*32+'/save';body={'revision':1,'draft':{'source_position':0,'face_position':0}}
    assert call_face(app,body,path=path,cookie='absent')[0]==401
    assert call_face(app,body,path=path,csrf='bad')[0]==403
    assert call_face(app,body,path=path,origin='https://foreign.invalid')[0]==403
    assert call_face(app,{**body,'actor':OWNER},path=path)[0]==422
    assert not calls
    assert call_face(app,body,path=path)[0]==200 and calls[0][0]=='b'*32
    assert call_face(app,None,path='/api/renewal/reviews/'+'f'*32+'/face-image/source/0',cookie='absent')[0]==401


def test_review_large_jpeg_analysis_publishes_real_bounded_display_images(state, tmp_path, monkeypatch):
    """OFFLINE: noise JPEG + synthetic CLI positions; real CPU image codecs only."""
    import importlib.util,json,random,struct,zlib,subprocess,os,shutil,hashlib
    from video_service.image_original import framing
    from video_service.canonical import canonical
    tools=Path('C:/Users/skygg/AppData/Local/hermes/tools/ffmpeg-9.0.1-win32-x64/bin')
    monkeypatch.setenv('PATH',str(tools)+os.pathsep+os.environ.get('PATH',''))
    width,height=2400,1800
    rgb=random.Random(5178).randbytes(width*height*3)
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+rgb[i*width*3:(i+1)*width*3] for i in range(height))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,1))+chunk(b'IEND',b'')
    pattern=tmp_path/'synthetic-noise.png';pattern.write_bytes(png)
    source=tmp_path/'synthetic-source.jpg';original=tmp_path/'synthetic-cli-original.png';crop=tmp_path/'synthetic-cli-crop.png'
    def cpu_image(arguments):
        subprocess.run([str(tools/'ffmpeg.exe'),'-v','error','-nostdin','-hwaccel','none','-threads','1','-filter_threads','1',*arguments],check=True,capture_output=True,timeout=20)
    cpu_image(['-i',str(pattern),'-frames:v','1','-q:v','5',str(source)])
    cpu_image(['-i',str(source),'-frames:v','1','-c:v','png',str(original)])
    cpu_image(['-i',str(source),'-vf','crop=1200:900:600:450','-frames:v','1','-c:v','png',str(crop)])
    raw=source.read_bytes();raw_sha=hashlib.sha256(raw).hexdigest()
    assert len(raw)<=10*1024**2 and framing(raw)['width']==width
    assert original.stat().st_size>10*1024**2
    package=ModuleType('mideagent_gpu');package.__path__=[str(ROOT/'tools/gpu')];monkeypatch.setitem(sys.modules,'mideagent_gpu',package)
    spec=importlib.util.spec_from_file_location('mideagent_gpu.adapters',ROOT/'tools/gpu/adapters.py')
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    store=state.store;source_owner='9'*32
    ctx=context();ctx['source']=store.put(source_owner,[raw],'image');ctx['source_owner_id']=source_owner
    ctx['target']=store.put(OWNER,[b'OFFLINE video metadata boundary; no video decode'],'video')
    value=command(inputs={'source':{**ctx['source'],'source_owner_id':source_owner},'video':ctx['target']},options={'context':ctx})
    native_calls=[]
    def cli_fixture(argv,work):
        request=json.loads(Path(argv[-1]).read_bytes());native_calls.append(request['operation'])
        out=Path(request['output']);out.mkdir()
        shutil.copyfile(original,out/'original.png');shutil.copyfile(crop,out/'face_0.png')
        (out/'result.json').write_bytes(canonical({'width':width,'height':height,'faces':[{'position':0,'bbox':[.25,.25,.75,.75],'file':'face_0.png'}]}))
    monkeypatch.setattr(adapter,'child',cli_fixture)
    sys.path.insert(0,str(ROOT/'tools/media'))
    from mideagent_media_tools import operations
    monkeypatch.setattr(operations,'probe',lambda *a,**k:dict(duration=12,width=640,height=360))
    outputs=adapter.execute(store,OWNER,value,dict(python=sys.executable,model_dir=str(tmp_path),descriptor=runtime()))
    doc=json.loads(outputs['analysis'][0]);display=store.read(OWNER,doc['image'],limit=10*1024**2)
    display_media=framing(display);face=doc['faces'][0];crop_media=framing(store.read(OWNER,face['image'],limit=10*1024**2))
    assert (doc['width'],doc['height'])==(display_media['width'],display_media['height'])==(1024,768)
    assert face['position']==0 and face['bbox']==[.25,.25,.75,.75]
    assert [round(face['bbox'][i]*[doc['width'],doc['height']][i%2]) for i in range(4)]==[256,192,768,576]
    assert max(crop_media['width'],crop_media['height'])<=1024
    assert ctx['source']['sha256']==raw_sha and store.read(source_owner,ctx['source'],limit=10*1024**2)==raw
    assert native_calls==['analyze_source'] and not list(store.root.rglob('.face-display-*'))
    evidence=dict(offline_fixture=True,real_cpu_image_only=True,native_cli='fixture; never executed',source_jpeg_bytes=len(raw),source_sha256=raw_sha,source_dimensions=[width,height],producer_png_bytes=original.stat().st_size,display_png_bytes=len(display),display_dimensions=[doc['width'],doc['height']],bbox=face['bbox'],crop_dimensions=[crop_media['width'],crop_media['height']],output_owner=OWNER,source_owner=source_owner)
    (Path('C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity')/'codex-face-agent-review-image-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')


def assert_review_image_http(runtime,viewer,review_id,groups):
    """Real route + session middleware, synthetic authenticated shared viewer."""
    import inspect,asyncio,json
    from fastapi.responses import FileResponse,JSONResponse
    from pydantic import BaseModel,ConfigDict,Field,StrictInt
    from test_face_input_preparation import face_app,png
    app=face_app(runtime)
    choice=next(r for r in app.routes if getattr(r,'path','')=='/api/work-entry/faceswap-inputs')
    dependency=inspect.signature(choice.endpoint).parameters['actor'].default
    session=inspect.signature(dependency.dependency).parameters['actor'].default.dependency
    session.__globals__['accounts'].session=lambda token:{'user':{'id':viewer,'role':'user'},'csrf_token':'csrf'} if token=='valid' else None
    class Body(BaseModel): model_config=ConfigDict(extra='forbid',strict=True)
    env=dict(app=app,runtime=runtime,owner_dependency=dependency,Body=Body,Field=Field,StrictInt=StrictInt,FileResponse=FileResponse)
    tree=ast.parse((ROOT/'apps/api/app/renewal_routes.py').read_text(encoding='utf8'))
    classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in {'Review','Revision'}]
    mount=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='mount_runtime')
    handlers=[n for n in mount.body if isinstance(n,ast.FunctionDef) and n.name in {'face_review_image','review_save','review_confirm'}]
    exec(compile(ast.Module(body=[*classes,*handlers],type_ignores=[]),'real-shared-face-http','exec'),env)
    @app.exception_handler(LookupError)
    async def absent(request,error): return JSONResponse({'detail':'not found'},status_code=404)
    async def call(path,body=None,cookie='valid'):
        sent=[];request=[{'type':'http.request','body':json.dumps(body).encode() if body is not None else b'','more_body':False}]
        async def receive():
            if request:return request.pop()
            await asyncio.Event().wait()
        async def send(message):sent.append(message)
        await app(dict(type='http',http_version='1.1',method='GET' if body is None else 'POST',scheme='https',path=path,raw_path=path.encode(),query_string=b'',headers=[(b'host',b'face.invalid'),(b'content-type',b'application/json'),(b'origin',b'https://face.invalid'),(b'cookie',('unit_session='+cookie).encode()),(b'x-csrf-token',b'csrf')],client=('unit',1),server=('face.invalid',443),root_path=''),receive,send)
        return sent[0]['status'],b''.join(m.get('body',b'') for m in sent)
    base='/api/renewal/reviews/'+review_id
    for group in groups:
        status,raw=asyncio.run(call(base+'/face-image/'+group+'/0'))
        assert status==200 and raw==png()
    assert asyncio.run(call(base+'/save',{'revision':1,'draft':{'source_position':0,'face_position':0}}))[0]==404
    assert asyncio.run(call(base+'/confirm',{'revision':1}))[0]==404
    assert asyncio.run(call(base+'/face-image/'+groups[0]+'/0',cookie='absent'))[0]==401
    assert asyncio.run(call(base+'/face-image/unknown/0'))[0]==422
    assert asyncio.run(call(base+'/face-image/'+groups[0]+'/127'))[0]==422


@pytest.mark.parametrize('bad',['pixels','bytes','geometry','path'])
def test_review_display_bounds_reject_before_cpu(state,tmp_path,monkeypatch,bad):
    """Producer-file boundary only; no decoder is run for invalid bounds."""
    import importlib.util,struct,zlib,os
    from test_face_input_preparation import png
    spec=importlib.util.spec_from_file_location('face_display_bounds',ROOT/'tools/gpu/face_operations.py')
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    work=tmp_path/'producer';(work/'output').mkdir(parents=True)
    path=work/'output'/'original.png';raw=png();path.write_bytes(raw)
    if bad=='pixels':
        data=struct.pack('>IIBBBBB',24000001,1,8,2,0,0,0)
        path.write_bytes(raw[:16]+data+struct.pack('>I',zlib.crc32(b'IHDR'+data)&0xffffffff)+raw[33:])
    elif bad=='bytes':
        actual_stat=Path.stat;details=list(path.stat());details[6]=128*1024**2+1
        monkeypatch.setattr(Path,'stat',lambda item,*a,**kw:os.stat_result(details) if item==path else actual_stat(item,*a,**kw))
    elif bad=='path': path=work/'output'/'..'/'outside.png'
    sys.path.insert(0,str(ROOT/'tools/media'))
    from mideagent_media_tools import operations
    monkeypatch.setattr(operations,'process_bounded',lambda *a,**k:pytest.fail('invalid producer bounds reached CPU codec'))
    with pytest.raises(ValueError): adapter.display_png(path,work,expected=(9,4) if bad=='geometry' else None)
