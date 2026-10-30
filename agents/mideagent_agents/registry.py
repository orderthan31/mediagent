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
  "id":"translate","name":"한국어 번역 에이전트","goal":"원문 구간과 시각을 유지한 한국어 번역문을 완성합니다.",
  "role":"translation","workflow_type":"translation_agent",
  "entrypoint":"mideagent_agents.translation.agent:TranslationAgent.advance",
  "model_graph_entrypoint":"mideagent_agents.translation.model_graph:TranslationAgent.run",
  "runtime_roles":["translation"],
  "allowed_tools":["text.prepare_batches","text.translate","text.validate_batch","text.merge_batches"],
  "model_driven_selection":False},
 "subtitle_video":{
  "id":"subtitle_video","name":"자막 영상 제작 에이전트","goal":"한국어 자막을 영상에 번인하고 재생을 확인한 영상을 완성합니다.",
  "role":"subtitle_video","workflow_type":"subtitle_video_agent",
  "entrypoint":"mideagent_agents.subtitle_video.agent:SubtitleVideoAgent.advance",
  "runtime_roles":["generate_subtitle","encode","validate_video"],
  "allowed_tools":["media.generate_subtitle","media.encode","media.validate_video"],
  "model_driven_selection":False}}
ALIASES={"transcription":"transcribe","translation":"translate","transcription_agent":"transcribe","translation_agent":"translate","subtitle_video_agent":"subtitle_video"}
def registration(identity):
 value=AGENTS.get(ALIASES.get(identity,identity))
 return deepcopy(value)if value else None
