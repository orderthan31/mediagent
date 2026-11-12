"""Public business-agent capabilities; native tools are not workflow members."""
from copy import deepcopy
from .transcription.agent import TranscriptionAgent
from .translation.agent import TranslationAgent
from .subtitle_video.agent import SubtitleVideoAgent
from .audio_extraction import AudioExtractionAgent
from .subtitle_file import SubtitleFileAgent
from .video_conversion import VideoConversionAgent
from video_service.renewal_contracts import spec

CLASSES = {c.kind:c for c in (TranscriptionAgent,TranslationAgent,SubtitleVideoAgent,AudioExtractionAgent,SubtitleFileAgent,VideoConversionAgent)}
ROLE_KEYS = {kind:cls.primary for kind,cls in CLASSES.items()}

def catalog():
    stages=[]
    for identity,cls in CLASSES.items():
        role=ROLE_KEYS[identity]
        native=spec(role,{})
        options={k:deepcopy(v)for k,v in native["options"].items()if k in (
            ("source_language","llm_options") if role=="transcribe" else ("target_language","llm_options") if role=="translate" else ("resolution","quality_profile","video_codec"))}
        if role == "transcribe":
            options["audio_source"] = ["video", "selected_audio"]
        if issubclass(cls, SubtitleFileAgent):
            subtitle = spec("generate_subtitle", {})
            options.update(format=deepcopy(subtitle["options"]["format"]),
                           language=["from_transcript", *subtitle["options"]["language"]],
                           transcript_source=["current", "original", "translated"])
            if role == "encode":
                options["subtitle_mode"] = [v for v in native["options"]["subtitle_mode"] if v != "none"]
        output_types = {"transcript": "transcript", "subtitles": "subtitle", "video": "video",
                        "audio": "audio", "report": "validation_report"}
        stages.append({"id":identity,"label":cls.label,"kind":"agent","node_kind":"agent","public":True,
            "inputs":{}if not cls.requires_parent else{"media":"media_task"},
            "outputs":{"media":"media_task", **{p:output_types[p] for p in cls.output_ports if p != "sami"}},
            **({"conditional_outputs":{"format":{"srt_smi":{"sami":"subtitle"}}}} if issubclass(cls, SubtitleFileAgent) else {}),
            "optional_inputs":[],"options":options,"option_labels":native.get("option_labels",{}),
            "option_defaults": {"target_language": "ko"} if role == "translate" else {},
            "option_roles":{key: (cls.option_roles or {}).get(key, role) for key in options if key not in {"transcript_source", "audio_source"}},
            "model_role": "transcription" if role=="transcribe" else "translation" if role=="translate" else None,
            "entrypoint":cls.__module__+":"+cls.__name__+".advance","execution":"goal_agent",
            "workflow_binding":True,"autonomous":False})
    return {"version":2,"nodes":stages,"controls":[],"executable":False}


def goal_options(node):
    """Read effective saved goal settings for inspection without changing revisions."""
    descriptor = next(item for item in catalog()["nodes"] if item["id"] == node["type"])
    settings = node.get("tool_settings", {})
    return {key: node.get("options", {}).get(key,
                settings.get(descriptor["option_roles"].get(key), {}).get(key, descriptor["option_defaults"].get(key, choices[0])))
            for key, choices in descriptor["options"].items()}
