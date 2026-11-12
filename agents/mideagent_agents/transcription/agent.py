"""Own video analysis, audio preparation and the existing timed-ASR LangGraph."""
from ..base import GoalAgent

class TranscriptionAgent(GoalAgent):
    kind = "transcription_agent"
    label = "전사 에이전트"
    tool_order = ("analyze", "extract_audio", "preprocess_audio", "transcribe")
    primary = "transcribe"
    requires_parent = False
    option_roles = {"source_language": "transcribe", "llm_options": "transcribe"}

    @classmethod
    def roles(cls, node):
        if node.get("options", {}).get("audio_source", "video") == "selected_audio":
            return ("analyze", "preprocess_audio", "transcribe")
        return cls.tool_order

    def plan(self, media, add):
        analyze = self.tool("analyze")
        prepare = self.tool("preprocess_audio", {"audio_filter":"off", "vad_mode":"off"})
        speech = self.tool("transcribe", model=True)
        add(analyze, {"video":media["video"]})
        if "extract_audio" in self.tool_order:
            extract = self.tool("extract_audio")
            add(extract, {"video":media["video"]})
            audio = (extract["id"], "audio")
        else:
            audio = media["audio"]
        add(prepare, {"audio":audio})
        speech_inputs = {"audio":(prepare["id"],"audio")}
        # Resolve preparation defaults before deciding whether the clock port exists.
        from video_service.editor_contracts import resolve_editor_contracts
        from video_service.renewal_contracts import spec
        resolved = resolve_editor_contracts({"nodes":[speech]})["nodes"][0]
        if "timeline" in spec("transcribe", resolved["options"])["inputs"]:
            speech_inputs["timeline"] = (prepare["id"], "timeline")
        add(speech, speech_inputs)
        transcript = (speech["id"], "transcript")
        return {**media, "metadata":(analyze["id"],"metadata"), "transcript":transcript,
                "original_transcript":transcript,
                "original_language":speech["options"].get("source_language", "auto"),
                "transcript_language":speech["options"].get("source_language", "auto")}
