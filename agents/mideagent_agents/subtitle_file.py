"""Reusable timed subtitle export, retaining original transcript provenance."""
from video_service.renewal_contracts import spec
from .base import GoalAgent


class SubtitleFileAgent(GoalAgent):
    kind = "subtitle_file_agent"
    label = "자막 파일 제작 에이전트"
    tool_order = ("generate_subtitle",)
    primary = "generate_subtitle"
    option_roles = {"format": "generate_subtitle", "language": "generate_subtitle"}
    output_ports = {"subtitles": "subtitles", "sami": "sami"}

    def subtitle(self, media, add):
        source = self.node.get("options", {}).get("transcript_source", "current")
        key = "original_transcript" if source == "original" else "transcript"
        language = media.get("original_language" if source == "original" else "transcript_language", "und")
        if key not in media or source == "translated" and not media.get("translated_language"):
            raise ValueError("자막 제작에 사용할 전사·번역 결과를 연결하세요.")
        subtitle = self.tool("generate_subtitle", {"format": "srt"})
        selected = subtitle["options"].get("language", "from_transcript")
        if selected == "from_transcript":
            selected = language
        # Native generation accepts base language codes, translation retains BCP-47.
        selected = "und" if selected == "auto" else selected.split("-")[0]
        if selected not in spec("generate_subtitle", {})["options"]["language"]:
            raise ValueError("자막 생성 도구가 지원하는 언어를 명시하세요.")
        subtitle["options"]["language"] = selected
        if media.get("cue_policy") == "preserve_v1":
            subtitle["options"]["cue_policy"] = "preserve_v1"
        add(subtitle, {"transcript": media[key]})
        outputs = spec("generate_subtitle", subtitle["options"])["outputs"]
        return {**media, **{port: (subtitle["id"], port) for port in outputs}}

    def plan(self, media, add):
        return self.subtitle(media, add)
