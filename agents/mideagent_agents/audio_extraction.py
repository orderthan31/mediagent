"""Prepare a verified WAV result from a selected video, without ASR or MT."""
from .base import GoalAgent


class AudioExtractionAgent(GoalAgent):
    kind = "audio_extraction_agent"
    label = "음성 추출 에이전트"
    tool_order = ("analyze", "extract_audio")
    primary = "extract_audio"
    requires_parent = False
    output_ports = {"audio": "audio", "metadata": "metadata"}

    def plan(self, media, add):
        if "video" not in media:
            raise ValueError("음성을 추출할 영상을 선택하세요.")
        analyze = self.tool("analyze")
        extract = self.tool("extract_audio")
        add(analyze, {"video": media["video"]})
        add(extract, {"video": media["video"]})
        return {**media, "metadata": (analyze["id"], "metadata"), "audio": (extract["id"], "audio")}
