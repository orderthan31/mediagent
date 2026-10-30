"""Read-only public goal states from durable tool attempts and actual capacity observations."""
from mideagent_agents.catalog import CLASSES
from video_service.renewal_contracts import spec
from .workflow import scope_snapshot

LABELS={"waiting":"대기","preparing":"준비 중","running":"처리 중","completed":"완료","failed":"오류","cancelled":"취소됨","blocked":"선행 오류","skipped":"미선택"}

def project_agents(job,runs,demands,instances,execution_observations=None):
    scope=scope_snapshot(job["snapshot"])
    if scope is None:return None
    public=scope["definition"];indexed={r["node_id"]:r for r in runs};result=[]
    native={n["id"]:n for n in job["snapshot"]["definition"]["nodes"]}
    pending={d["node_id"]:d for d in demands if d.get("node_run_id")is None} if job["status"]not in {"cancelled","cancelling","completed","failed"}else{}
    observations=execution_observations or {}
    for node in public["nodes"]:
        cls=CLASSES[node["type"]];agent=cls(node,tool_bindings=scope["bindings"][node["id"]]);tools=[]
        for role in cls.tool_order:
            identity=agent.tool_id(role);run=indexed.get(identity);demand=pending.get(identity)
            state=(run.get("display_status")or run["status"])if run else "waiting"
            reason=(run.get("display_reason")or "")if run else ""
            if state in {"held","unknown","quarantined"}:state="failed"
            if demand:
                pool=[i for i in instances if i["role"]==demand["role"]]
                available=any(i["phase"]in {"ready","busy"}and i.get("fresh",False)for i in pool)
                failed=any(i.get("error_code")and i["phase"]not in {"removed","stopped","retiring"}for i in pool)
                state="failed"if failed and not available else "preparing"
                if state=="failed":reason="실행기 준비에 실패했습니다."
            if run and state in {"running","waiting"}:
                observation=observations.get(run["id"],{})
                phase=(run.get("dispatch")or{}).get("phase")
                if phase in {"pending","queued","sending","sent"}or observation.get("phase")in {"ready","sending","sent"} and not observation.get("has_calls"):
                    state="preparing"
                if observation.get("started") or observation.get("has_calls") or phase=="received":
                    state="running"
            dispatch_phase=(run.get("dispatch")or{}).get("phase")if run else None
            if run and run["status"]not in {"completed","cancelled"}and dispatch_phase in {"held","failed","unknown"}:
                state="failed";reason="실행 요청 전달을 확인하지 못했습니다. 자동으로 다시 보내지 않습니다."
            if state=="failed"and not reason:reason=spec(role,native[identity]["options"])["label"]+"에 실패했습니다."
            tools.append({"node_id":identity,"role":role,"label":{"transcribe":"구간 전사 처리","translate":"구간 번역 처리"}.get(role,spec(role,native[identity]["options"])["label"]),
                          "state":state,"reason":reason,"run_id":run["id"]if run else None})
        failed=next((t for t in tools if t["state"]in {"failed","blocked"}),None)
        active=next((t for t in tools if t["state"]in {"running","preparing"}),None)
        completed=[t for t in tools if t["state"]=="completed"]
        if failed:state="failed";reason=failed["reason"]
        elif len(completed)==len(tools):state="completed";reason=""
        elif active:state="running"if completed else active["state"];reason=""
        elif job["status"]in {"cancelled","cancelling"}or any(t["state"]=="cancelled"for t in tools):state="cancelled";reason=""
        elif completed:state="running";reason=""
        else:state="waiting";reason=""
        if state=="completed":
            decision=agent.next_tool(indexed,job["snapshot"]["definition"])
            if decision["state"]!="completed":state="failed";reason=decision.get("reason")or"처리 결과를 확인할 수 없습니다."
        primary=next((t for t in tools if t["role"]==cls.primary and t["run_id"]),None)
        selected=failed or active or primary or (completed[-1]if completed else tools[0])
        result.append({"id":node["id"],"type":node["type"],"label":cls.label,"state":state,
                       "status_label":LABELS.get(state,"상태 확인 필요"),"reason":reason,
                       "selected_tool_id":selected["node_id"],"tools":tools})
    # No fixed timer, guessed readiness or spinner during an agent's internal tools.
    by_id={n["id"]:n for n in result};edges={}
    for edge in public["edges"]:
        parent=by_id[edge["source"]["node"]];target=by_id[edge["target"]["node"]]
        if parent["state"]=="completed"and target["state"]=="preparing":
            edges[edge["id"]]={"state":"preparing","label":"다음 단계 준비 중"}
        elif parent["state"]=="completed"and target["state"]=="failed":
            edges[edge["id"]]={"state":"failed","label":"실행 오류"}
    return {"definition":public,"legacy_projection":scope["legacy_projection"],"nodes":result,"edges":edges}

def read_agent_view(db,job,runs):
    if scope_snapshot(job["snapshot"])is None:return None
    demands=[];instances=[];observations={}
    if db.execute("SELECT to_regclass('agent_pool_demands') value").fetchone()["value"]:
        demands=db.execute("SELECT node_id,role,node_run_id FROM agent_pool_demands WHERE owner_id=%s AND job_id=%s AND generation=%s",(job["owner_id"],job["id"],job["generation"])).fetchall()
        roles=list({d["role"]for d in demands})
        if roles:instances=db.execute("SELECT role,phase,error_code,(observed_at>now()-interval '5 seconds') IS TRUE fresh FROM agent_pool_instances WHERE role=ANY(%s)AND phase<>'removed'",(roles,)).fetchall()
    if db.execute("SELECT to_regclass('model_role_tasks') value").fetchone()["value"]:
        observations={r["attempt_id"]:dict(r) for r in db.execute("SELECT m.attempt_id,m.phase,EXISTS(SELECT 1 FROM model_role_tool_calls c WHERE c.task_id=m.task_id) has_calls FROM model_role_tasks m WHERE m.owner_id=%s AND m.job_id=%s",(job["owner_id"],job["id"])).fetchall()}
    if runs and db.execute("SELECT to_regclass('worker_observation_events') value").fetchone()["value"]:
        started=db.execute("SELECT DISTINCT attempt_id FROM worker_observation_events WHERE ticket_id=%s AND attempt_id=ANY(%s)AND state IN('busy','stopping')",(job["id"],[r["id"]for r in runs])).fetchall()
        for row in started:observations.setdefault(row["attempt_id"],{})["started"]=True
    return project_agents(job,runs,demands,instances,observations)
