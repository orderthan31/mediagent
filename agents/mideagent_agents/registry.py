"""Business goal registrations; model graphs are internal implementations, not workflow nodes."""
from copy import deepcopy
AGENTS={
 "transcribe":{
  "id":"transcribe","name":"전사 에이전트","goal":"영상의 음성을 준비하고 원본 시각이 맞는 전사문을 완성합니다.",
  "role":"transcription","workflow_type":"transcription_agent",
  "entrypoint":"mideagent_agents.transcription.agent:TranscriptionAgent.advance",
  "model_graph_entrypoint":"mideagent_agents.transcription.model_graph:TranscriptionAgent.run",
  "runtime_roles":["analyze","extract_audio","preprocess_audio","transcription"],
  "allowed_tools":["media.analyze","media.extract_audio","media.preprocess_audio","speech.prepare_audio","speech.transcribe","speech.validate_chunk","speech.merge_segments"],
  "model_driven_selection":False},
 "translate":{
  "id":"translate","name":"번역 에이전트","goal":"원문 구간과 시각을 유지한 선택 언어 번역문을 완성합니다.",
  "role":"translation","workflow_type":"translation_agent",
  "entrypoint":"mideagent_agents.translation.agent:TranslationAgent.advance",
  "model_graph_entrypoint":"mideagent_agents.translation.model_graph:TranslationAgent.run",
  "runtime_roles":["translation"],
  "allowed_tools":["text.prepare_batches","text.translate","text.validate_batch","text.merge_batches"],
  "model_driven_selection":False},
 "subtitle_video":{
  "id":"subtitle_video","name":"자막 영상 제작 에이전트","goal":"선택한 원문·번역 자막을 번인하거나 소프트 자막으로 넣고 출력 영상을 검증합니다.",
  "role":"subtitle_video","workflow_type":"subtitle_video_agent",
  "entrypoint":"mideagent_agents.subtitle_video.agent:SubtitleVideoAgent.advance",
  "runtime_roles":["generate_subtitle","encode","validate_video"],
  "allowed_tools":["media.generate_subtitle","media.encode","media.validate_video"],
  "model_driven_selection":False}}
ALIASES={"transcription":"transcribe","translation":"translate","transcription_agent":"transcribe","translation_agent":"translate","subtitle_video_agent":"subtitle_video"}
AGENTS["transcribe"]["profiles"] = {"selected_audio": {"runtime_roles": ["analyze", "preprocess_audio", "transcription"],
    "input": "같은 영상의 완료된 16kHz 모노 PCM WAV 추출 결과"}}

for identity, label, goal, roles, module, classname in (
    ("audio_extraction", "음성 추출 에이전트", "영상에서 16kHz 모노 WAV를 추출합니다.",
     ["analyze", "extract_audio"], "audio_extraction", "AudioExtractionAgent"),
    ("subtitle_file", "자막 파일 제작 에이전트", "전사·번역 결과에서 SRT 또는 SRT와 SAMI를 만듭니다.",
     ["generate_subtitle"], "subtitle_file", "SubtitleFileAgent"),
    ("video_conversion", "영상 변환 에이전트", "모델 처리 없이 영상을 변환하고 출력 영상을 검증합니다.",
     ["encode", "validate_video"], "video_conversion", "VideoConversionAgent"),
):
    AGENTS[identity] = {"id": identity, "name": label, "goal": goal,
                        "role": identity, "workflow_type": identity + "_agent",
                        "entrypoint": "mideagent_agents." + module + ":" + classname + ".advance",
                        "runtime_roles": roles, "allowed_tools": ["media." + role for role in roles],
                        "model_driven_selection": False}
    ALIASES[identity + "_agent"] = identity
def registration(identity, *, node=None):
 value=AGENTS.get(ALIASES.get(identity,identity))
 if value is None:return None
 value=deepcopy(value)
 if node is not None:
  from .catalog import CLASSES
  if node["type"]!=value["workflow_type"]:raise ValueError("goal_registration_mismatch")
  roles=CLASSES[node["type"]].roles(node)
  value["runtime_roles"]=[{"transcribe":"transcription","translate":"translation"}.get(role,role)for role in roles]
  if "extract_audio"not in roles:value["allowed_tools"]=[tool for tool in value["allowed_tools"]if tool!="media.extract_audio"]
 return value
