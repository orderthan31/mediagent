"""Face goal integration: immutable input pins and SQL-accepted predecessor authority.

Read/planning paths never stage content or invoke native code. Explicit review
confirmation alone materializes a selection/approval under the existing CAS.
"""
from copy import deepcopy
from datetime import datetime
import json
from uuid import uuid4
from video_service.canonical import canonical, digest
from video_service.content_store import reference_origin
from video_service.face_protocol import (OPERATIONS, REVIEW_TYPES, POLICY, TTL_SECONDS,
    MAX_JSON, exact, integer, context as validate_context, selection, approval, predecessor)


def sql_json(value):
    from psycopg.types.json import Jsonb
    return Jsonb(value)


def conflict(message):
    from video_service.postgres import Conflict
    raise Conflict(message)


def selected(snapshot):
    return snapshot.get("agent_definition",{}).get("input_profile")=="face_workflow_v1"


def stamp(job,runs):
    return digest({"snapshot":job["snapshot_sha256"],"generation":job["generation"],
                   "runs":[{k:r.get(k) for k in ("id","status","generation","request_sha256","result")} for r in runs]})


def frozen(snapshot, owner):
    """Validate new-only photo pins without weakening any legacy input schema."""
    if not selected(snapshot): raise ValueError("face_profile_required")
    from video_service.face_protocol import policy as operation_policy
    if snapshot.get("face_operation_policy") != operation_policy(): raise ValueError("frozen_face_operation_policy_changed")
    pin=snapshot.get("normal_input_bindings",{}).get("photo")
    exact(pin,{"kind","asset_id","custodian_id","reference","content_sha256","media","policy","engine","settings"},"frozen_face_photo_required")
    from video_service.image_original import policy
    if pin["kind"]!="photo_original_v1" or pin["policy"]!=policy(): raise ValueError("frozen_face_photo_policy_changed")
    for port,kind in (("photo","image"),("video","video")):
        custodian,ref=reference_origin(owner,snapshot["inputs"].get(port))
        from video_service.engine_protocol import reference
        reference(ref)
        if ref["type"]!=kind: raise ValueError("frozen_face_input_type_changed")
        if port=="photo" and (custodian!=pin["custodian_id"] or ref!=pin["reference"] or ref["sha256"]!=pin["content_sha256"]):
            raise ValueError("frozen_face_photo_origin_changed")
        if port=="video":
            asset=snapshot["asset"]
            if custodian!=asset.get("storage_custodian_id",asset.get("uploaded_by",owner)) or ref["sha256"]!=asset["sha256"] or ref["bytes"]!=asset["size_bytes"]:
                raise ValueError("frozen_face_target_origin_changed")
    from video_service.image_original import validate_media
    validate_media(pin["media"],pin["reference"]["bytes"])
    engine=pin["engine"]
    exact(engine,{"revision","sha256","descriptor"},"frozen_face_engine_required")
    if digest(engine["descriptor"])!=engine["sha256"]: raise ValueError("frozen_face_engine_changed")
    tools=[n for n in snapshot["definition"]["nodes"] if n["type"] in OPERATIONS]
    if len(tools)!=4 or any(snapshot.get("engine_bindings",{}).get(n["id"])!=engine for n in tools):
        raise ValueError("frozen_face_engine_bindings_changed")
    render=next(n for n in tools if n["type"]=="face_render")
    if any(render["options"].get(k)!=pin["settings"][k] for k in ("preset","video_codec")):
        raise ValueError("frozen_face_settings_changed")
    return pin


def command_context(job):
    snapshot=job["snapshot"];owner=job["owner_id"];pin=frozen(snapshot,owner)
    target_owner,target=reference_origin(owner,snapshot["inputs"]["video"])
    goal=next(n["id"] for n in snapshot["agent_definition"]["nodes"] if n["type"]=="faceswap_agent")
    value=dict(version=1,job_id=job["id"],snapshot_sha256=job["snapshot_sha256"],goal_id=goal,
        generation=job["generation"],source_asset_id=pin["asset_id"],target_asset_id=snapshot["asset"]["asset_id"],
        source_owner_id=pin["custodian_id"],target_owner_id=target_owner,output_owner_id=owner,source=pin["reference"],target=target,
        settings_revision=pin["settings"]["revision"],settings={k:pin["settings"][k] for k in ("preset","video_codec","reference_frame","distance")},
        runtime_revision=pin["engine"]["revision"],runtime_sha256=pin["engine"]["sha256"],policy=POLICY)
    validate_context(value,pin["engine"]["descriptor"],job["generation"])
    return value


class FaceWorkflow:
    def __init__(self,runtime):
        self.runtime=runtime;self.store=runtime.store;self.database=runtime.database

    def resolve(self,db,actor,asset,definition,options):
        from video_service.postgres.engine_runtimes import EngineRuntimes
        from video_service.image_original import asset_media,policy
        selector=exact(options.get("face_input"),{"photo_asset_id","engine_revision","engine_sha256","settings_revision","reference_frame"},"사진과 실행기·기준 프레임을 선택하세요.")
        from video_service.engine_protocol import ID, SHA
        if (type(selector["engine_revision"]) is not int or selector["engine_revision"]<1
                or not isinstance(selector["engine_sha256"],str) or not SHA.fullmatch(selector["engine_sha256"])):
            raise ValueError("등록 얼굴 합성 실행기 버전을 직접 선택하세요.")
        if not isinstance(selector["photo_asset_id"],str) or not ID.fullmatch(selector["photo_asset_id"]): raise ValueError("등록 사진을 선택하세요.")
        if selector["settings_revision"]!=1 or type(selector["settings_revision"]) is not int: raise ValueError("합성 설정 버전을 확인하세요.")
        integer(selector["reference_frame"],1,3600)
        if any(k in options for k in ("accepted_inputs","subtitle_srt","transcript","saved_subtitle","audio_goal","translation_goal","render_goal")):
            raise ValueError("얼굴 합성에는 사진과 대상 영상을 선택하세요.")
        photo=self.runtime._shared_asset(db,selector["photo_asset_id"]);media=asset_media(photo)
        target=self.runtime.asset_reference(asset);video=asset.get("metadata",{}).get("media",{})
        import math
        if (media is None or target["type"]!="video" or target["bytes"]>268435456
                or type(video.get("duration")) not in (int,float) or not math.isfinite(video["duration"]) or not 0<video["duration"]<=30
                or any(type(video.get(k)) is not int for k in ("width","height"))
                or not 0<video["width"]<=1280 or not 0<video["height"]<=720):
            raise ValueError("검증된 JPEG·PNG 사진과 30초·1280×720·256MiB 이내 영상을 선택하세요.")
        engine=EngineRuntimes.resolve_in(db,"faceswap",sha256=selector["engine_sha256"])
        if type(selector["engine_revision"]) is not int or engine["revision"]!=selector["engine_revision"]: raise ValueError("실행기 버전이 바뀌었습니다.")
        pinengine={k:deepcopy(engine[k]) for k in ("revision","sha256","descriptor")}
        node=definition["nodes"][0]
        from mideagent_agents.catalog import goal_options
        settings=goal_options(node)
        settings={"revision":1,"reference_frame":selector["reference_frame"],"distance":0.6,**settings}
        pref=self.runtime.asset_reference(photo);custodian=photo["owner_id"]
        self.store.path(custodian,pref);self.store.path(asset["owner_id"],target)
        pin=dict(kind="photo_original_v1",asset_id=photo["id"],custodian_id=custodian,reference=deepcopy(pref),
                 content_sha256=pref["sha256"],media=deepcopy(media),policy=policy(),engine=pinengine,settings=settings)
        return {"references":{"photo":{**pref,**({"source_owner_id":custodian} if custodian!=actor else {})}},
                "bindings":{"photo":pin},"segments":None,"language":None}

    def preflight(self,owner,identity):
        with self.database.connection() as db:
            job=self.runtime._job(db,owner,identity)
            if not selected(job["snapshot"]): return None
            runs=self.runtime._runs(db,owner,identity)
            reviews=db.execute("SELECT * FROM review_tasks WHERE owner_id=%s AND job_id=%s ORDER BY id",(owner,identity)).fetchall()
        ctx=command_context(job)
        # All CAS/worker-receipt reads happen after leaving the metadata transaction.
        self.runtime.ticket_artifacts.read(job,runs)
        for ref in job["snapshot"]["inputs"].values(): self.store.path(owner,ref)
        proofs={};documents={};references={};decisions={};accepted_times={}
        names={"face_analyze_source":"source","face_analyze_reference":"reference","face_preview":"preview"}
        for run in runs:
            if run["status"]!="completed" or run["generation"]!=job["generation"]: continue
            role=run["node_type"]
            if role in names:
                request=run["request"]
                if run["request_sha256"]!=digest(request): raise ValueError("face_sql_request_changed")
                result=self.store.read_attempt_result(owner,request)
                receipt=run["result"]
                if any(receipt.get(k)!=v for k,v in result.items()): raise ValueError("face_sql_accepted_result_changed")
                proof={"command":request,"result":result}
                doc,ref=predecessor(self.store,owner,proof,ctx,role)
                proofs[names[role]]=proof;documents[names[role]]=doc;references[names[role]]=ref
                accepted_times[names[role]]=int(run["completed_at"].timestamp())
            elif role in REVIEW_TYPES:
                review=next((r for r in reviews if r["node_run_id"]==run["id"] and r["status"]=="confirmed"),None)
                if not review or review["contract"].get("context")!=ctx: raise ValueError("confirmed_face_review_required")
                port="session" if role=="face_select" else "approval"
                ref=run["result"]["outputs"][port]
                value=json.loads(self.store.read(owner,ref,limit=MAX_JSON))
                if digest(value)!=review["confirmed_sha256"]: raise ValueError("face_confirmed_review_changed")
                decisions[port]=value;references[port]=ref
        if "session" in decisions:
            selection(decisions["session"],ctx)
            self.validate_selection(decisions["session"],documents,references)
        if "approval" in decisions: approval(decisions["approval"],ctx,decisions["session"])
        return dict(stamp=stamp(job,runs),context=ctx,proofs=proofs,documents=documents,references=references,decisions=decisions,accepted_times=accepted_times)

    @staticmethod
    def validate_selection(value,documents,references):
        for name,position,pin in (("source","source_position","source_analysis_sha256"),("reference","face_position","reference_analysis_sha256")):
            if name not in documents or value[pin]!=references[name]["sha256"] or not any(f["position"]==value[position] for f in documents[name]["faces"]):
                raise ValueError("실제 분석 결과에 있는 인물을 각각 선택하세요.")

    @staticmethod
    def check_stage(job,runs,stage):
        if not stage or stage["stamp"]!=stamp(job,runs): conflict("얼굴 합성 자료가 바뀌었습니다. 다시 확인하세요.")

    @staticmethod
    def plan_reasons(job,runs,stage):
        import time
        # Future human decisions never block initial analysis. A committed render
        # is historical even when its preview's window subsequently expires.
        if not any(run["node_type"]=="face_render" for run in runs):
            session=(stage or {}).get("decisions",{}).get("session")
            if session and not session["accepted_at"]<=time.time()<session["expires_at"]:
                return ["인물 선택 자료가 만료됐습니다. 자동으로 다시 분석하지 않습니다."]
            approved=(stage or {}).get("decisions",{}).get("approval")
            if approved and not approved["accepted_at"]<=time.time()<approved["expires_at"]:
                return ["미리보기 확인이 만료됐습니다. 자동으로 다시 실행하지 않습니다."]
        return []

    @staticmethod
    def command_options(job,node,stage):
        if not stage or stage["context"]!=command_context(job): conflict("얼굴 합성 명령의 입력 맥락이 바뀌었습니다.")
        role=node["type"];options={"context":stage["context"]}
        if role in {"face_preview","face_render"}:
            options.update(selection=stage["decisions"]["session"],predecessors={k:stage["proofs"][k] for k in ("source","reference")})
        if role=="face_render":
            options["predecessors"]["preview"]=stage["proofs"]["preview"]
            options["approval"]=stage["decisions"]["approval"]
            # Time is rechecked again by native against this exact admitted receipt.
            import time
            if not options["approval"]["accepted_at"]<=time.time()<options["approval"]["expires_at"]: conflict("미리보기 확인이 만료됐습니다. 자동으로 다시 실행하지 않습니다.")
        return options

    @staticmethod
    def review_contract(node,stage):
        kind=node["type"]
        if kind=="face_select":
            if not all(stage["documents"].get(k,{}).get("faces") for k in ("source","reference")):
                raise ValueError("선택할 인물이 없습니다. 사진과 기준 프레임을 확인하세요.")
            return {"version":1,"kind":kind,"context":stage["context"],
                    "source":stage["documents"]["source"],"reference":stage["documents"]["reference"],
                    "source_analysis_sha256":stage["references"]["source"]["sha256"],
                    "reference_analysis_sha256":stage["references"]["reference"]["sha256"]}, {"source_position":None,"face_position":None}
        return {"version":1,"kind":kind,"context":stage["context"],"preview":stage["documents"]["preview"],
                "preview_sha256":stage["references"]["preview"]["sha256"],"expires_at":stage["accepted_times"]["preview"]+TTL_SECONDS,"selection":stage["decisions"]["session"]}, {"confirmed":False}

    def result_preflight(self,owner,command,result):
        from video_service.engine_protocol import envelope
        from video_service.face_protocol import document
        envelope(owner,command,result)
        if result["status"]=="completed":
            if self.store.read_attempt_result(owner,command)!=result:
                raise ValueError("face_result_not_immutable_worker_receipt")
            if command["agent"]["id"]!="face_render":
                port="preview" if command["agent"]["id"]=="face_preview" else "analysis"
                value=document(json.loads(self.store.read(owner,result["outputs"][port],limit=MAX_JSON)),command)
                for ref in [value["image"],*[face["image"] for face in value["faces"]]]: self.store.path(owner,ref)
            for ref in result["outputs"].values(): self.store.path(owner,ref)
        return {"request_sha256":digest(command),"result_sha256":digest(result)}

    def stage_result(self,owner,command,result):
        """Stage ticket blobs/manifest off the mutable job lock, never acceptance.

        A later cancellation/context race leaves ignored orphan artifacts. The
        receiver must compare this exact SQL run frontier before adopting it.
        """
        if result["status"]!="completed": return None
        with self.database.connection() as db:
            job=self.runtime._job(db,owner,command["run_id"])
            runs=self.runtime._runs(db,owner,job["id"])
            run=next((r for r in runs if r["id"]==command["attempt_id"]),None)
            if (not run or run["status"]!="running" or run["request_sha256"]!=digest(command)
                    or run["generation"]!=job["generation"] or job["cancel_requested"]): return None
            if command["options"]["context"]!=command_context(job): raise ValueError("face_result_context_changed")
            frozen_stamp=stamp(job,runs)
            receipt=self.runtime.ticket_artifacts.capture(db,job,run,{**deepcopy(result),"previews":{}})
        return {"stamp":frozen_stamp,"receipt":receipt}

    def image(self,actor,identity,group,index):
        # Same shared authenticated read boundary as Execution.review_source.
        # Mutations still use the owner-scoped _review method unchanged.
        from video_service.postgres import Missing
        from video_service.postgres.registry import resource_id
        if group not in {"source","reference","preview"}: raise ValueError("검수 사진을 확인하세요.")
        integer(index,0,127)
        with self.database.connection() as db:
            rows=db.execute("SELECT * FROM review_tasks WHERE id=%s LIMIT 2",(resource_id(identity),)).fetchall()
            if len(rows)!=1 or rows[0]["contract"].get("kind") not in REVIEW_TYPES:
                raise Missing("얼굴 합성 검수 자료를 찾을 수 없습니다.")
            review=rows[0]
            job=self.runtime._shared_job(db,review["job_id"])
            runs=self.runtime._runs(db,job["owner_id"],job["id"])
            matching=[r for r in runs if r["id"]==review["node_run_id"]]
            if (job["owner_id"]!=review["owner_id"] or job["id"]!=review["job_id"]
                    or len(matching)!=1 or matching[0]["node_type"]!=review["contract"]["kind"]
                    or matching[0]["generation"]!=job["generation"]
                    or job["snapshot"].get("agent_tool_owners",{}).get(matching[0]["node_id"])!=review["contract"]["context"]["goal_id"]):
                raise Missing("현재 작업의 얼굴 합성 검수 자료가 아닙니다.")
        owner=job["owner_id"]
        stage=self.preflight(owner,job["id"])
        if review["contract"]["context"]!=stage["context"]:
            raise ValueError("현재 얼굴 합성 검수 자료가 아닙니다.")
        if review["contract"]["kind"]=="face_confirm_preview" and group=="preview" and index==0:
            if (review["contract"].get("preview")!=stage["documents"].get("preview")
                    or review["contract"].get("preview_sha256")!=stage["references"].get("preview",{}).get("sha256")):
                raise ValueError("확인할 미리보기가 바뀌었습니다.")
            ref=stage["documents"]["preview"]["image"]
        elif review["contract"]["kind"]=="face_select" and group in {"source","reference"} and group in stage["documents"]:
            if review["contract"].get(group)!=stage["documents"][group]: raise ValueError("분석 자료가 바뀌었습니다.")
            faces=stage["documents"][group]["faces"]
            ref=next((f["image"] for f in faces if f["position"]==index),None)
            if ref is None: raise ValueError("선택한 인물 사진이 없습니다.")
        else: raise ValueError("검수 사진을 확인하세요.")
        return self.store.path(owner,ref)

    def handles(self,owner,identity):
        with self.database.connection() as db: return self.runtime._review(db,owner,identity)["contract"].get("kind") in REVIEW_TYPES

    @staticmethod
    def validate_draft(row,draft):
        contract=row["contract"]
        if contract["kind"]=="face_select":
            exact(draft,{"source_position","face_position"},"사진과 영상의 인물을 각각 선택하세요.")
            for name,key in (("source","source_position"),("reference","face_position")):
                integer(draft[key],0,127)
                if not any(f["position"]==draft[key] for f in contract[name]["faces"]): raise ValueError("분석 결과에 없는 인물입니다.")
        else:
            exact(draft,{"confirmed"},"미리보기 확인 값을 확인하세요.")
            if type(draft["confirmed"]) is not bool: raise ValueError("미리보기를 직접 확인하세요.")
        return deepcopy(draft)

    def save_review(self,owner,identity,revision,draft):
        with self.database.connection() as db:
            hint=self.runtime._review(db,owner,identity)
            job=self.runtime._job(db,owner,hint["job_id"],lock=True)
            row=self.runtime._review(db,owner,identity,lock=True)
            self.guard(job,row,revision)
            draft=self.validate_draft(row,draft);next_revision=revision+1
            db.execute("INSERT INTO review_revisions VALUES (%s,%s,%s,%s,%s,now())",(owner,identity,next_revision,sql_json(draft),digest(draft)))
            row=db.execute("UPDATE review_tasks SET revision=%s,draft=%s,status='draft' WHERE owner_id=%s AND id=%s RETURNING *",(next_revision,sql_json(draft),owner,identity)).fetchone()
            db.execute("UPDATE jobs SET revision=revision+1 WHERE owner_id=%s AND id=%s",(owner,job["id"]))
            return row

    @staticmethod
    def guard(job,row,revision):
        if row["revision"]!=revision or row["status"]=="confirmed" or job["status"]!="review_required" or job["cancel_requested"] or row["contract"]["context"]!=command_context(job):
            conflict("검수 대상이 바뀌었습니다. 다시 확인하세요.")

    def confirm_review(self,owner,identity,revision):
        with self.database.connection() as db:
            row=self.runtime._review(db,owner,identity)
            job=self.runtime._job(db,owner,row["job_id"])
            now=int(db.execute("SELECT extract(epoch FROM now())::bigint AS epoch").fetchone()["epoch"])
        self.guard(job,row,revision);draft=self.validate_draft(row,row["draft"])
        stage=self.preflight(owner,job["id"])
        if stage["context"]!=row["contract"]["context"]: conflict("얼굴 합성 자료가 바뀌었습니다.")
        if row["contract"]["kind"]=="face_select":
            accepted_at=min(stage["accepted_times"]["source"],stage["accepted_times"]["reference"])
            if not accepted_at<=now<accepted_at+TTL_SECONDS: conflict("인물 분석 자료가 만료됐습니다. 자동으로 다시 분석하지 않습니다.")
            value={"version":2,"context_sha256":digest(stage["context"]),**draft,"revision":revision,"accepted_at":accepted_at,"expires_at":accepted_at+TTL_SECONDS,
                   "source_analysis_sha256":stage["references"]["source"]["sha256"],"reference_analysis_sha256":stage["references"]["reference"]["sha256"]}
            self.validate_selection(value,stage["documents"],stage["references"]);selection(value,stage["context"])
            port,kind="session","face_session"
        else:
            if draft["confirmed"] is not True: raise ValueError("미리보기를 확인한 뒤 확정하세요.")
            if stage["documents"]["preview"]!=row["contract"]["preview"]: conflict("미리보기가 바뀌었습니다.")
            accepted_at=stage["accepted_times"]["preview"]
            if not accepted_at<=now<accepted_at+TTL_SECONDS: conflict("미리보기가 만료됐습니다. 자동으로 다시 실행하지 않습니다.")
            value=dict(version=1,context_sha256=digest(stage["context"]),selection_sha256=digest(stage["decisions"]["session"]),
                       preview_sha256=stage["references"]["preview"]["sha256"],accepted_at=accepted_at,expires_at=accepted_at+TTL_SECONDS,review_id=identity,revision=revision)
            approval(value,stage["context"],stage["decisions"]["session"]);port,kind="approval","face_approval"
        # Explicit user confirmation only; orphan CAS on a race has no authority.
        ref=self.store.put(owner,[canonical(value)],kind)
        with self.database.connection() as staging_db:
            staged_job=self.runtime._job(staging_db,owner,job["id"])
            staged_run=next(r for r in self.runtime._runs(staging_db,owner,job["id"]) if r["id"]==row["node_run_id"])
            staged_receipt=self.runtime.ticket_artifacts.capture(staging_db,staged_job,staged_run,{"outputs":{port:ref},"transport":"human_gate","review_id":identity,"review_revision":revision,"confirmed_sha256":digest(value)})
        with self.database.connection() as db:
            current=self.runtime._job(db,owner,job["id"],lock=True)
            review=self.runtime._review(db,owner,identity,lock=True)
            self.guard(current,review,revision)
            self.check_stage(current,self.runtime._runs(db,owner,job["id"]),stage)
            if review["draft"]!=draft: conflict("검수 내용이 바뀌었습니다.")
            db.execute("UPDATE review_tasks SET status='confirmed',confirmed_sha256=%s WHERE owner_id=%s AND id=%s",(digest(value),owner,identity))
            run=next(r for r in self.runtime._runs(db,owner,job["id"]) if r["id"]==review["node_run_id"])
            receipt=staged_receipt
            db.execute("UPDATE node_runs SET status='completed',result=%s,completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",(sql_json(receipt),owner,job["id"],run["id"]))
            db.execute("UPDATE jobs SET active_claim_id=NULL,revision=revision+1 WHERE owner_id=%s AND id=%s",(owner,job["id"]))
            return self.runtime._view(db,self.runtime._job(db,owner,job["id"]))
