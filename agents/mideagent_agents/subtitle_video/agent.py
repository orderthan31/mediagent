"""Own subtitle generation, burn-in encoding and output-video validation."""
from ..base import GoalAgent

class SubtitleVideoAgent(GoalAgent):
    kind = "subtitle_video_agent"
    label = "자막 영상 제작 에이전트"
    tool_order = ("generate_subtitle", "encode", "validate_video")
    primary = "encode"

    def plan(self, media, add):
        if media.get("translated_language") != "ko":
            raise ValueError("자막 영상 제작에는 한국어 번역 결과를 연결하세요.")
        subtitle = self.tool("generate_subtitle", {"format":"srt", "language":"ko"})
        subtitle["options"]["language"] = "ko"
        encode = self.tool("encode", {"video_codec":"h264","subtitle_mode":"burn","resolution":"original","quality_profile":"balanced"})
        encode["options"]["subtitle_mode"] = "burn"
        check = self.tool("validate_video")
        add(subtitle, {"transcript":media["transcript"]})
        add(encode, {"video":media["video"],"subtitles":(subtitle["id"],"subtitles")})
        add(check, {"video":(encode["id"],"video")})
        return {**media,"video":(encode["id"],"video"),"subtitles":(subtitle["id"],"subtitles"),"report":(check["id"],"report")}
