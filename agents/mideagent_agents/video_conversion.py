"""Convert video without model work, and validate the actual encoded result."""
from .base import GoalAgent


class VideoConversionAgent(GoalAgent):
    kind = "video_conversion_agent"
    label = "영상 변환 에이전트"
    tool_order = ("encode", "validate_video")
    primary = "encode"
    requires_parent = False
    output_ports = {"video": "video", "report": "report"}

    def plan(self, media, add):
        encode = self.tool("encode", {"subtitle_mode": "none", "video_codec": "h264",
                                     "resolution": "original", "quality_profile": "balanced"})
        if encode["options"]["subtitle_mode"] != "none":
            raise ValueError("자막을 넣으려면 자막 영상 제작 목표를 사용하세요.")
        check = self.tool("validate_video")
        add(encode, {"video": media["video"]})
        add(check, {"video": (encode["id"], "video")})
        return {**media, "video": (encode["id"], "video"), "report": (check["id"], "report")}
