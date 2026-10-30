"""Own video analysis, audio preparation and the existing timed-ASR LangGraph."""
from ..base import GoalAgent

class TranscriptionAgent(GoalAgent):
    kind = "transcription_agent"
    label = "전사 에이전트"
    tool_order = ("analyze", "extract_audio", "preprocess_audio", "transcribe")
    primary = "transcribe"

    def plan(self, media, add):
        analyze = self.tool("analyze")
        extract = self.tool("extract_audio")
        prepare = self.tool("preprocess_audio", {"audio_filter":"off", "vad_mode":"off"})
        speech = self.tool("transcribe", model=True)
        add(analyze, {"video":media["video"]})
        add(extract, {"video":media["video"]})
        add(prepare, {"audio":(extract["id"],"audio")})
        speech_inputs = {"audio":(prepare["id"],"audio")}
        # Resolve preparation defaults before deciding whether the clock port exists.
        from video_service.editor_contracts import resolve_editor_contracts
        from video_service.renewal_contracts import spec
        resolved = resolve_editor_contracts({"nodes":[speech]})["nodes"][0]
        if "timeline" in spec("transcribe", resolved["options"])["inputs"]:
            speech_inputs["timeline"] = (prepare["id"], "timeline")
        add(speech, speech_inputs)
        return {**media, "metadata":(analyze["id"],"metadata"), "transcript":(speech["id"],"transcript")}
