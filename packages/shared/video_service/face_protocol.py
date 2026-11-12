"""Face-only v3 contracts. No execution, storage access or approval inference."""
import math
from .canonical import digest

OPERATIONS = {
    "face_analyze_source": "analyze_source",
    "face_analyze_reference": "analyze_reference",
    "face_preview": "preview",
    "face_render": "render",
}
REVIEW_TYPES = {"face_select", "face_confirm_preview"}
POLICY = "face_operations_v1"
TTL_SECONDS = 1800
MAX_JSON = 65536
OUTPUTS = {
    "face_analyze_source": {"analysis": "face_analysis"},
    "face_analyze_reference": {"analysis": "face_analysis"},
    "face_preview": {"preview": "face_preview"},
    "face_render": {"video": "video"},
}

def policy():
    # New-only frozen finite GPU policy, independent from paid LLM budgets.
    return {"id":POLICY,"version":1,"protocol_version":3,
            "operation_limits":{operation:1 for operation in OPERATIONS.values()},
            "timeout_seconds":120,"approval_ttl_seconds":TTL_SECONDS,
            "analysis_ttl_seconds":TTL_SECONDS,"session_ttl_seconds":TTL_SECONDS,"preview_ttl_seconds":TTL_SECONDS,
            "max_faces":128,"max_json_bytes":MAX_JSON,
            "max_photo_bytes":10485760,"max_photo_pixels":24000000,
            "max_video_bytes":268435456,"max_video_seconds":30,
            "max_video_width":1280,"max_video_height":720}


def exact(value, keys, error):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(error)
    return value

def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid_face_integer")
    return value

def context(value, runtime, generation):
    from .engine_protocol import ID, SHA, reference
    exact(value, {"version","job_id","snapshot_sha256","goal_id","generation",
        "source_asset_id","target_asset_id","source_owner_id","target_owner_id","output_owner_id",
        "source","target","settings_revision","settings","runtime_revision",
        "runtime_sha256","policy"}, "invalid_face_context")
    integer(value["generation"],1,2147483647)
    if type(value["version"]) is not int or value["version"] != 1 or value["generation"] != generation or value["policy"] != POLICY:
        raise ValueError("invalid_face_context_version")
    for key in ("job_id","source_asset_id","target_asset_id","source_owner_id","target_owner_id","output_owner_id"):
        if not isinstance(value[key],str) or not ID.fullmatch(value[key]):
            raise ValueError("invalid_face_identity")
    if not isinstance(value["goal_id"],str) or not 0 < len(value["goal_id"]) <= 80:
        raise ValueError("invalid_face_goal")
    if not isinstance(value["snapshot_sha256"],str) or not SHA.fullmatch(value["snapshot_sha256"]):
        raise ValueError("invalid_face_snapshot")
    if value["runtime_sha256"] != digest(runtime):
        raise ValueError("face_runtime_changed")
    for key in ("runtime_revision","settings_revision"):
        integer(value[key],1,2147483647)
    for key,kind,limit in (("source","image",10485760),("target","video",268435456)):
        reference(value[key])
        if value[key]["type"] != kind or value[key]["bytes"] > limit:
            raise ValueError("invalid_face_media")
    settings=exact(value["settings"],{"preset","video_codec","reference_frame","distance"},"invalid_face_settings")
    if settings["preset"] not in {"fast","balanced","quality"} or settings["video_codec"] not in {"h264","hevc"}:
        raise ValueError("unsupported_face_settings")
    integer(settings["reference_frame"],1,3600)
    if type(settings["distance"]) not in (int,float) or not math.isfinite(settings["distance"]) or not 0 <= settings["distance"] <= 1.5:
        raise ValueError("invalid_face_distance")
    return value

def validate_command(command):
    from .engine_protocol import ID, validate_runtime, reference
    exact(command,{"protocol_version","run_id","attempt_id","generation","agent","inputs","options","runtime"},"invalid_face_command")
    integer(command["generation"],1,2147483647)
    if type(command["protocol_version"]) is not int or command["protocol_version"] != 3:
        raise ValueError("invalid_face_protocol")
    for key in ("run_id","attempt_id"):
        if not isinstance(command[key],str) or not ID.fullmatch(command[key]):
            raise ValueError("invalid_face_identity")
    runtime=validate_runtime(command["runtime"])
    if runtime.get("face_protocol") != 3 or runtime["role"] != "faceswap":
        raise ValueError("face_v3_runtime_required")
    role=command["agent"].get("id") if isinstance(command["agent"],dict) else None
    if role not in OPERATIONS or command["agent"] != {"id":role,"family":"gpu","revision":digest(runtime)}:
        raise ValueError("invalid_face_operation")
    extras={"face_preview":{"selection","predecessors"},"face_render":{"selection","approval","predecessors"}}.get(role,set())
    options=exact(command["options"],{"context"}|extras,"invalid_face_options")
    ctx=context(options["context"],runtime,command["generation"])
    if ctx["job_id"] != command["run_id"]: raise ValueError("face_command_job_changed")
    ports={"source":"image","video":"video"}
    if role in {"face_preview","face_render"}: ports["session"]="face_session"
    if role=="face_render": ports["approval"]="face_approval"
    exact(command["inputs"],ports,"invalid_face_inputs")
    for port,kind in ports.items():
        reference(command["inputs"][port],input_origin=port in {"source","video"})
        if command["inputs"][port]["type"]!=kind:
            raise ValueError("invalid_face_input_type")
    for port,key,owner in (("source","source","source_owner_id"),("video","target","target_owner_id")):
        candidate=dict(command["inputs"][port]); candidate.pop("source_owner_id",None)
        if candidate!=ctx[key] or command["inputs"][port].get("source_owner_id",ctx[owner])!=ctx[owner]:
            raise ValueError("face_input_origin_changed")
    if extras:
        selection(options["selection"],ctx)
        expected={"source","reference"} | ({"preview"} if role=="face_render" else set())
        exact(options["predecessors"],expected,"invalid_face_predecessors")
        for key,proof in options["predecessors"].items():
            exact(proof,{"command","result"},"invalid_face_producer")
            producer=proof["command"]
            expected_role={"source":"face_analyze_source","reference":"face_analyze_reference","preview":"face_preview"}[key]
            if producer.get("agent",{}).get("id")!=expected_role or producer.get("options",{}).get("context")!=ctx:
                raise ValueError("face_producer_context_changed")
            # Recursive proofs have strictly earlier stage types and bounded wire size.
            from .engine_protocol import envelope
            envelope(ctx["output_owner_id"],producer,proof["result"])
            if proof["result"]["status"]!="completed": raise ValueError("accepted_face_producer_required")
        if role=="face_render": approval(options["approval"],ctx,options["selection"])
    return command

def selection(value, ctx):
    exact(value,{"version","context_sha256","source_position","face_position","source_analysis_sha256","reference_analysis_sha256","revision","accepted_at","expires_at"},"invalid_face_selection")
    if type(value["version"]) is not int or value["version"]!=2 or value["context_sha256"]!=digest(ctx):
        raise ValueError("face_selection_context_changed")
    for key in ("accepted_at","expires_at"): integer(value[key],1,2**53-1)
    if value["expires_at"]-value["accepted_at"]!=TTL_SECONDS: raise ValueError("invalid_face_session_expiry")
    for key in ("source_position","face_position"): integer(value[key],0,127)
    integer(value["revision"],1,2147483647)
    from .engine_protocol import SHA
    for key in ("source_analysis_sha256","reference_analysis_sha256"):
        if not isinstance(value[key],str) or not SHA.fullmatch(value[key]): raise ValueError("invalid_face_selection_pin")
    return value

def approval(value, ctx, selected):
    exact(value,{"version","context_sha256","selection_sha256","preview_sha256","accepted_at","expires_at","review_id","revision"},"invalid_face_approval")
    if type(value["version"]) is not int or value["version"]!=1 or value["context_sha256"]!=digest(ctx) or value["selection_sha256"]!=digest(selected):
        raise ValueError("face_approval_context_changed")
    integer(value["accepted_at"],1,2**53-1); integer(value["expires_at"],1,2**53-1)
    if value["expires_at"]-value["accepted_at"]!=TTL_SECONDS: raise ValueError("invalid_face_approval_expiry")
    from .engine_protocol import ID, SHA
    if not isinstance(value["review_id"],str) or not ID.fullmatch(value["review_id"]) or not isinstance(value["preview_sha256"],str) or not SHA.fullmatch(value["preview_sha256"]):
        raise ValueError("invalid_face_approval_identity")
    integer(value["revision"],1,2147483647)
    return value


def document(value, command):
    from .engine_protocol import reference
    role=command["agent"]["id"]
    operation=OPERATIONS[role]
    keys={"version","operation","context_sha256","request_sha256","run_id","attempt_id","faces","width","height","image"}
    if role in {"face_analyze_reference","face_preview"}: keys|={"frame_number","frame_count","fps"}
    if role=="face_preview": keys|={"matched_faces","selection_sha256"}
    exact(value,keys,"invalid_face_document")
    if type(value["version"]) is not int or value["version"]!=1 or value["operation"]!=operation or any(value[k]!=command[k] for k in ("run_id","attempt_id")) or value["request_sha256"]!=digest(command) or value["context_sha256"]!=digest(command["options"]["context"]):
        raise ValueError("face_document_producer_changed")
    integer(value["width"],1,24000000);integer(value["height"],1,24000000)
    if value["width"]*value["height"]>24000000: raise ValueError("face_image_pixel_bound")
    def image(ref):
        reference(ref)
        if ref["type"]!="image" or ref["bytes"]>10485760: raise ValueError("invalid_face_image")
    image(value["image"])
    if not isinstance(value["faces"],list) or len(value["faces"])>128: raise ValueError("invalid_face_candidates")
    for i,face in enumerate(value["faces"]):
        exact(face,{"position","bbox","image"},"invalid_face_candidate")
        if type(face["position"]) is not int or face["position"]!=i or not isinstance(face["bbox"],list) or len(face["bbox"])!=4 or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1 for n in face["bbox"]):
            raise ValueError("invalid_face_candidate")
        if face["bbox"][0]>=face["bbox"][2] or face["bbox"][1]>=face["bbox"][3]: raise ValueError("invalid_face_candidate")
        image(face["image"])
    if "frame_number" in keys:
        integer(value["frame_count"],1,3600);integer(value["frame_number"],1,value["frame_count"])
        if value["frame_number"]!=command["options"]["context"]["settings"]["reference_frame"] or type(value["fps"]) not in (int,float) or not math.isfinite(value["fps"]) or not 0<value["fps"]<=120 or value["frame_count"]/value["fps"]>30:
            raise ValueError("invalid_face_frame")
    if role=="face_preview":
        integer(value["matched_faces"],1,128)
        if value["selection_sha256"]!=digest(command["options"]["selection"]): raise ValueError("face_preview_selection_changed")
    return value

def predecessor(store, owner, proof, ctx, role):
    """Validate an admitted SQL-selected proof against immutable worker records.

    This does NOT infer SQL acceptance from CAS. The publisher must first bind
    the exact completed SQL run and TicketArtifacts into the admitted command.
    """
    import json
    from .engine_protocol import envelope
    exact(proof,{"command","result"},"invalid_face_producer")
    command=proof["command"];result=proof["result"]
    envelope(owner,command,result)
    if command["agent"]["id"]!=role or command["options"]["context"]!=ctx or result["status"]!="completed":
        raise ValueError("accepted_face_predecessor_required")
    if store.read_attempt_result(owner,command)!=result:
        raise ValueError("face_worker_result_changed")
    port="preview" if role=="face_preview" else "analysis"
    reference=result["outputs"][port]
    value=document(json.loads(store.read(owner,reference,limit=MAX_JSON)),command)
    for ref in [value["image"],*[face["image"] for face in value["faces"]]]:
        store.path(owner,ref)
    return value,reference
