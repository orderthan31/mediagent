"""Public business-agent capabilities; native tools are not workflow members."""
from copy import deepcopy
from .transcription.agent import TranscriptionAgent
from .translation.agent import TranslationAgent
from .subtitle_video.agent import SubtitleVideoAgent
from .audio_extraction import AudioExtractionAgent
from .subtitle_file import SubtitleFileAgent
from .video_conversion import VideoConversionAgent
from .faceswap import FaceSwapAgent
from video_service.renewal_contracts import spec

CLASSES = {c.kind:c for c in (TranscriptionAgent,TranslationAgent,SubtitleVideoAgent,AudioExtractionAgent,SubtitleFileAgent,VideoConversionAgent,FaceSwapAgent)}
ROLE_KEYS = {kind:cls.primary for kind,cls in CLASSES.items()}


BUSINESS_INPUTS = {
    "transcription_agent": {"video": "video", "audio": "audio"},
    "translation_agent": {"transcript": "transcript"},
    "subtitle_file_agent": {"transcript": "transcript"},
    "subtitle_video_agent": {"transcript": "transcript", "video": "video", "subtitles": "subtitle"},
    "audio_extraction_agent": {"video": "video"},
    "video_conversion_agent": {"video": "video"},
}
PUBLIC_CONTROLS = frozenset({"select", "join", "review", "control_if", "control_switch", "subtitle_tracks", "subtitle_outputs", "subtitle_track"})

def catalog():
    stages=[]
    for identity,cls in CLASSES.items():
        role=ROLE_KEYS[identity]
        native=spec(role,{})
        options={k:deepcopy(v)for k,v in native["options"].items()if k in (
            ("source_language","llm_options") if role=="transcribe" else ("target_language","llm_options") if role=="translate" else ("resolution","quality_profile","video_codec"))}
        if role == "translate":
            options["video_description"] = [""]
        if role == "face_render":
            options = {k: deepcopy(native["options"][k]) for k in ("preset", "video_codec")}
        if role == "transcribe":
            options["audio_source"] = ["video", "selected_audio", "audio_file_v1"]
        if issubclass(cls, SubtitleFileAgent):
            subtitle = spec("generate_subtitle", {})
            options.update(format=deepcopy(subtitle["options"]["format"]),
                           language=["from_transcript", *subtitle["options"]["language"]],
                           transcript_source=["current", "original", "translated"])
            if role == "encode":
                options["subtitle_mode"] = [v for v in native["options"]["subtitle_mode"] if v != "none"]
                options["subtitle_source"] = ["from_transcript", "selected_subtitles"]
        output_types = {"transcript": "transcript", "subtitles": "subtitle", "video": "video",
                        "audio": "audio", "report": "validation_report", "metadata": "media_metadata"}
        stages.append({"id":identity,"label":cls.label,"kind":"agent","node_kind":"agent","public":True,
            "inputs": {} if identity == "faceswap_agent" else {"media": "media_task", "gate": "control_signal", **BUSINESS_INPUTS.get(identity, {})},
            "outputs":{"media":"media_task", **{p:output_types[p] for p in cls.output_ports if p != "sami"}},
            **({"conditional_outputs":{"format":{"srt_smi":{"sami":"subtitle"}}}} if issubclass(cls, SubtitleFileAgent) else {}),
            **({"hidden_outputs": {"subtitle_source": {"selected_subtitles": ["subtitles", "sami"]}},
                "hidden_options": {"subtitle_source": {"selected_subtitles": ["format", "language", "transcript_source"]}}} if identity == "subtitle_video_agent" else {}),
            "optional_inputs": ["gate", *BUSINESS_INPUTS.get(identity, {})], "options":options,"option_labels":native.get("option_labels",{}),
            "option_defaults": {"target_language": "ko"} if role == "translate" else {},
            "option_roles":{key: (cls.option_roles or {}).get(key, role) for key in options if key not in {"transcript_source", "audio_source", "subtitle_source"}},
            "model_role": "transcription" if role=="transcribe" else "translation" if role=="translate" else None,
            "entrypoint":cls.__module__+":"+cls.__name__+".advance","execution":"goal_agent",
            "workflow_binding":True,"autonomous":False})
    from video_service.renewal_contracts import catalog as native_catalog
    controls = []
    for item in native_catalog()["nodes"]:
        if item["id"] not in PUBLIC_CONTROLS:
            continue
        control = deepcopy(item)
        control.update(node_kind="control", public=True, workflow_binding=True,
                       option_roles={}, option_defaults={k: v for k, v in {
                           "data_type": "video", "left_type": "video", "right_type": "video",
                           "review_kind": "approve_only", "selection": "a",
                       }.items() if k in control["options"]}, model_role=None)
        controls.append(control)
    return {"version": 2, "nodes": [*stages, *controls], "controls": controls, "executable": False}


def goal_options(node):
    """Read effective saved goal settings for inspection without changing revisions."""
    descriptor = next(item for item in catalog()["nodes"] if item["id"] == node["type"])
    settings = node.get("tool_settings", {})
    return {key: node.get("options", {}).get(key,
                settings.get(descriptor["option_roles"].get(key), {}).get(key, descriptor["option_defaults"].get(key, choices[0])))
            for key, choices in descriptor["options"].items()}
