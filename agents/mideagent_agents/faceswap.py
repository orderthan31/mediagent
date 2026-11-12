"""Own face analysis, explicit decisions, preview, render and final validation."""
from .base import GoalAgent

class FaceSwapAgent(GoalAgent):
    kind="faceswap_agent"
    label="얼굴 합성 에이전트"
    tool_order=("face_analyze_source","face_analyze_reference","face_select","face_preview","face_confirm_preview","face_render","validate_video")
    primary="face_render"
    requires_parent=False
    output_ports={"video":"video","report":"report"}
    option_roles={"preset":"face_render","video_codec":"face_render"}

    def plan(self, media, add):
        settings={"preset":"fast","video_codec":"h264"}
        source=self.tool("face_analyze_source");reference=self.tool("face_analyze_reference")
        select=self.tool("face_select");preview=self.tool("face_preview")
        confirm=self.tool("face_confirm_preview");render=self.tool("face_render",settings)
        validate=self.tool("validate_video")
        inputs={"source":media["photo"],"video":media["video"]}
        add(source,inputs);add(reference,inputs)
        add(select,{"source_analysis":(source["id"],"analysis"),"reference_analysis":(reference["id"],"analysis")})
        add(preview,{**inputs,"session":(select["id"],"session")})
        add(confirm,{"preview":(preview["id"],"preview"),"session":(select["id"],"session")})
        add(render,{**inputs,"session":(select["id"],"session"),"approval":(confirm["id"],"approval")})
        add(validate,{"video":(render["id"],"video")})
        return {**media,"video":(render["id"],"video"),"report":(validate["id"],"report")}
