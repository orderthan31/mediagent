"""Own subtitle generation, burn-in encoding and output-video validation."""
from ..subtitle_file import SubtitleFileAgent

class SubtitleVideoAgent(SubtitleFileAgent):
    kind = "subtitle_video_agent"
    label = "자막 영상 제작 에이전트"
    tool_order = ("generate_subtitle", "encode", "validate_video")
    primary = "encode"
    option_roles = {**SubtitleFileAgent.option_roles,
                    **{key: "encode" for key in ("video_codec", "subtitle_mode", "resolution", "quality_profile")}}
    output_ports = {**SubtitleFileAgent.output_ports, "video": "video", "report": "report"}

    @classmethod
    def roles(cls, node):
        return ("encode", "validate_video") if node.get("options", {}).get("subtitle_source") == "selected_subtitles" else cls.tool_order

    def plan(self, media, add):
        if self.node.get("options", {}).get("subtitle_source") == "selected_subtitles":
            if "subtitles" not in media:
                raise ValueError("영상에 넣을 검수·제작된 자막 파일을 연결하세요.")
        else:
            media = self.subtitle(media, add)
        encode = self.tool("encode", {"video_codec":"h264","subtitle_mode":"burn","resolution":"original","quality_profile":"balanced"})
        check = self.tool("validate_video")
        add(encode, {"video":media["video"],"subtitles":media["subtitles"]})
        add(check, {"video":(encode["id"],"video")})
        return {**media,"video":(encode["id"],"video"),"report":(check["id"],"report")}
