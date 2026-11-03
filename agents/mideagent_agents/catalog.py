"""Public business-agent capabilities; native tools are not workflow members."""
from copy import deepcopy
from .transcription.agent import TranscriptionAgent
from .translation.agent import TranslationAgent
from .subtitle_video.agent import SubtitleVideoAgent
from video_service.renewal_contracts import spec

CLASSES = {c.kind:c for c in (TranscriptionAgent,TranslationAgent,SubtitleVideoAgent)}
ROLE_KEYS = {"transcription_agent":"transcribe","translation_agent":"translate","subtitle_video_agent":"encode"}

def catalog():
    stages=[]
    for identity,cls in CLASSES.items():
        role=ROLE_KEYS[identity]
        native=spec(role,{})
        options={k:deepcopy(v)for k,v in native["options"].items()if k in (
            ("source_language","llm_options") if role=="transcribe" else ("target_language","llm_options") if role=="translate" else ("resolution","quality_profile","video_codec"))}
        if role=="translate":options["target_language"]=["ko"]
        stages.append({"id":identity,"label":cls.label,"kind":"agent","node_kind":"agent","public":True,
            "inputs":{}if role=="transcribe"else{"media":"media_task"},
            "outputs":{"video":"video","subtitle":"subtitle","report":"report"}if role=="encode"else{"media":"media_task"},
            "optional_inputs":[],"options":options,"option_labels":native.get("option_labels",{}),
            "model_role": "transcription" if role=="transcribe" else "translation" if role=="translate" else None,
            "entrypoint":cls.__module__+":"+cls.__name__+".advance","execution":"goal_agent",
            "workflow_binding":True,"autonomous":False})
    return {"version":2,"nodes":stages,"controls":[],"executable":False}
