"""Own batch preparation, bounded translation, validation and merge via the existing graph."""
from ..base import GoalAgent

class TranslationAgent(GoalAgent):
    kind = "translation_agent"
    label = "번역 에이전트"
    tool_order = ("translate",)
    primary = "translate"

    def plan(self, media, add):
        tool = self.tool("translate", {"target_language":"ko", "translation_profile":"language_target_v1"}, model=True)
        from video_service.translation_context import description
        text = description(tool["options"].pop("video_description", ""))
        tool["options"].pop("translation_context_profile", None)
        if text:
            tool["options"].update(video_description=text, translation_context_profile="reference_v1")
        add(tool, {"transcript":media["transcript"]},
            input_languages={"transcript": media["transcript_language"]})
        return {**media,"transcript":(tool["id"],"transcript"),
                "transcript_language":tool["options"]["target_language"],
                "translated_language":tool["options"]["target_language"]}
