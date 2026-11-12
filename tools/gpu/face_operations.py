"""Explicit FaceFusion v3 producer. Child execution is the sole inference boundary."""
import json
import math
import shutil
import time
from pathlib import Path
from video_service.canonical import canonical, digest
from video_service.content_store import reference_origin
from video_service.face_protocol import (OPERATIONS, MAX_JSON, exact, integer,
    validate_command, document, predecessor)


def cli_settings(role, settings):
    """Satisfy the legacy CLI parser without selecting an analysis candidate.

    Its parser requires a reference index even for analyze_* (which enumerates
    all faces). This private parser value is never a session, a selected face,
    or an approval. Preview/render require the explicit server-selected values.
    Keep facefusion.py bytes/fingerprint and every v2 request unchanged.
    """
    values = dict(settings)
    if role in {"face_analyze_source", "face_analyze_reference"}:
        if any(key in values for key in ("source_position", "face_position")):
            raise ValueError("analysis_cannot_select_faces")
        values["face_position"] = 0
    elif role not in {"face_preview", "face_render"} or not all(key in values for key in ("source_position", "face_position")):
        raise ValueError("explicit_face_selection_required")
    return values



# Private, completed CLI working files only; published image limits stay 10MiB.
MAX_PRODUCER_PNG = 128 * 1024**2
MAX_DISPLAY_EDGE = 1024


def display_png(path, work, *, expected=None):
    """Bound producer PNG before decoding; publish a separate small display copy."""
    import stat
    import struct
    import tempfile
    import zlib
    from video_service.image_original import framing

    if (path.parent != work / "output" or path.parent.is_symlink()
            or path.parent.is_junction() or path.is_symlink()
            or not stat.S_ISREG(path.stat().st_mode)
            or not 0 < path.stat().st_size <= MAX_PRODUCER_PNG):
        raise ValueError("bounded_face_producer_png_required")
    size=path.stat().st_size
    with path.open("rb") as stream:
        header=stream.read(33)
        if (len(header)!=33 or header[:16]!=b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
                or zlib.crc32(header[12:29])&0xffffffff != struct.unpack(">I",header[29:33])[0]):
            raise ValueError("invalid_face_producer_png_header")
        width,height,depth,color,compression,filtering,interlace=struct.unpack(">IIBBBBB",header[16:29])
        if (min(width,height)<1 or width*height>24000000 or depth!=8
                or color not in (2,6) or (compression,filtering,interlace)!=(0,0,0)
                or expected is not None and (width,height)!=expected):
            raise ValueError("bounded_face_producer_geometry_required")
        # CLI writes plain still PNG. Refuse animation/compressed metadata before
        # the CPU decoder; scan framing with seeks, never expand metadata here.
        data=False;ended=False
        for _ in range(4096):
            chunk=stream.read(8)
            if len(chunk)!=8: break
            length,kind=struct.unpack(">I4s",chunk)
            if stream.tell()+length+4>size: break
            if kind==b"IDAT": data=True
            elif kind==b"IEND" and length==0:
                stream.seek(4,1);ended=data and stream.tell()==size;break
            elif kind!=b"pHYs" or length!=9:
                raise ValueError("plain_face_producer_png_required")
            stream.seek(length+4,1)
        if not ended: raise ValueError("invalid_face_producer_png_framing")
    def read_image(source):
        with source.open("rb") as stream: raw=stream.read(10485761)
        if len(raw)>10485760: raise ValueError("bounded_face_display_required")
        media=framing(raw)
        if media["format"]!="png": raise ValueError("face_producer_png_required")
        return raw,media
    if size<=10485760 and max(width,height)<=MAX_DISPLAY_EDGE:
        return read_image(path)
    scale=min(1,MAX_DISPLAY_EDGE/max(width,height))
    display_width=max(1,round(width*scale));display_height=max(1,round(height*scale))
    from mideagent_media_tools.operations import ffmpeg,process_bounded
    with tempfile.TemporaryDirectory(prefix=".face-display-",dir=work) as directory:
        target=Path(directory)/"display.png"
        arguments=ffmpeg()
        arguments[arguments.index("-max_alloc")+1]="134217728"
        arguments[arguments.index("-format_whitelist")+1]="image2pipe"
        arguments += ["-xerror","-f","image2pipe","-c:v","png","-noautorotate",
                      "-err_detect","explode","-i",str(path),"-frames:v","1",
                      "-an","-sn","-dn","-vf",f"scale={display_width}:{display_height}",
                      "-map_metadata","-1","-pix_fmt","rgb24","-c:v","png","-threads","1",str(target)]
        process_bounded(arguments,output=target,cwd=directory,timeout=10,max_bytes=10485760)
        raw,media=read_image(target)
        if (media["width"],media["height"])!=(display_width,display_height):
            raise ValueError("face_display_geometry_changed")
        return raw,media


def execute(store, owner, command, config, work, *, child):
    validate_command(command)
    if config["descriptor"] != command["runtime"]:
        raise ValueError("face_runtime_changed")
    role=command["agent"]["id"];options=command["options"];ctx=options["context"]
    settings=dict(ctx["settings"])
    if role in {"face_preview","face_render"}:
        sources={name:predecessor(store,owner,options["predecessors"][name],ctx,producer)
                 for name,producer in (("source","face_analyze_source"),("reference","face_analyze_reference"))}
        selected=options["selection"]
        if not selected["accepted_at"]<=time.time()<selected["expires_at"]:
            raise ValueError("accepted_unexpired_face_session_required")
        if json.loads(store.read(owner,command["inputs"]["session"],limit=MAX_JSON))!=selected:
            raise ValueError("face_session_changed")
        for key,position,pin in (("source","source_position","source_analysis_sha256"),("reference","face_position","reference_analysis_sha256")):
            value,ref=sources[key]
            if selected[pin]!=ref["sha256"] or not any(face["position"]==selected[position] for face in value["faces"]):
                raise ValueError("selected_face_not_in_accepted_analysis")
        settings.update({k:selected[k] for k in ("source_position","face_position")})
    if role=="face_render":
        preview,pref=predecessor(store,owner,options["predecessors"]["preview"],ctx,"face_preview")
        approval=options["approval"]
        if (json.loads(store.read(owner,command["inputs"]["approval"],limit=MAX_JSON))!=approval
                or approval["preview_sha256"]!=pref["sha256"]
                or preview["selection_sha256"]!=digest(selected)
                or not approval["accepted_at"]<=time.time()<approval["expires_at"]):
            raise ValueError("accepted_unexpired_face_approval_required")
    executable=Path(config["python"])
    if not executable.is_absolute() or not executable.is_file(): raise ValueError("explicit_face_interpreter_required")
    paths={}
    for port,filename in (("source","source.media"),("video","target.mp4")):
        custodian,ref=reference_origin(owner,command["inputs"][port])
        paths[port]=work/filename
        shutil.copyfile(store.path(custodian,ref),paths[port])
    from video_service.image_original import framing
    framing(paths["source"].read_bytes())
    # Independent worker-side bounds; no native inference or capabilities probe.
    from mideagent_media_tools.operations import probe
    media=probe(paths["video"])
    if (type(media.get("duration")) not in (int,float) or not math.isfinite(media["duration"])
            or not 0<media["duration"]<=30 or not 0<media.get("width",0)<=1280
            or not 0<media.get("height",0)<=720): raise ValueError("face_role_accepts_bounded_video_only")
    output=work/"output"
    request=dict(face_protocol=3,operation=OPERATIONS[role],output=str(output),source=str(paths["source"]),
                 target=str(paths["video"]),fingerprint=command["runtime"]["model_sha256"],
                 session_id=command["attempt_id"],settings=cli_settings(role, settings),
                 preview_frame=settings["reference_frame"],preview_resolution=512,
                 analysis_frame=settings["reference_frame"])
    request_path=work/"request.json";request_path.write_bytes(canonical(request))
    child([str(executable),str(Path(__file__).with_name("facefusion.py")),"--engine",config["model_dir"],"--request",str(request_path)],work)
    def read(name,limit):
        path=output/name
        if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=limit:
            raise ValueError("bounded_face_output_required")
        return path.read_bytes()
    value=json.loads(read("result.json",MAX_JSON))
    if role=="face_render":
        exact(value,{"file"},"invalid_face_render_result")
        if value["file"]!="final.mp4": raise ValueError("invalid_face_render_path")
        return {"video":(read("final.mp4",268435456),"video")}
    keys={"width","height","faces"}
    if role in {"face_analyze_reference","face_preview"}: keys|={"frame_number","frame_count","fps"}
    if role=="face_preview": keys|={"matched_faces","timings_ms"}
    exact(value,keys,"invalid_face_cli_result")
    if not isinstance(value["faces"],list) or len(value["faces"])>128: raise ValueError("invalid_face_candidates")
    def image(name, expected=None):
        raw,media=display_png(output/name,work,expected=expected)
        return store.put(owner,[raw],"image"),media
    integer(value["width"],1,24000000);integer(value["height"],1,24000000)
    full_image,display=image("preview.png" if role=="face_preview" else "original.png",(value["width"],value["height"]))
    result={k:value[k] for k in keys-{"faces","timings_ms"}}
    # Bboxes are normalized in the full display image; their fractions and CLI
    # positions stay unchanged by the proportional pixel-coordinate transform.
    result.update(width=display["width"],height=display["height"])
    result["faces"]=[]
    for i,face in enumerate(value["faces"]):
        exact(face,{"position","bbox","file"},"invalid_face_cli_candidate")
        if face["position"]!=i or face["file"]!=f"face_{i}.png": raise ValueError("invalid_face_cli_candidate")
        crop,_=image(face["file"])
        result["faces"].append(dict(position=i,bbox=face["bbox"],image=crop))
    result.update(version=1,operation=OPERATIONS[role],context_sha256=digest(ctx),request_sha256=digest(command),
                  run_id=command["run_id"],attempt_id=command["attempt_id"],image=full_image)
    if role=="face_preview": result["selection_sha256"]=digest(selected)
    document(result,command)
    raw=canonical(result)
    if len(raw)>MAX_JSON: raise ValueError("face_document_too_large")
    return {"preview" if role=="face_preview" else "analysis":(raw,"face_preview" if role=="face_preview" else "face_analysis")}
