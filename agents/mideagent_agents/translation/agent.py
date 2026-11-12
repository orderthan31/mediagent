"""Own batch preparation, bounded translation, validation and merge via the existing graph."""
from ..base import GoalAgent

class TranslationAgent(GoalAgent):
    kind = "translation_agent"
    label = "번역 에이전트"
    tool_order = ("translate",)
    primary = "translate"

    def plan(self, media, add):
        tool = self.tool("translate", {"target_language":"ko", "translation_profile":"language_target_v1"}, model=True)
        add(tool, {"transcript":media["transcript"]},
            input_languages={"transcript": media["transcript_language"]})
        return {**media,"transcript":(tool["id"],"transcript"),
                "transcript_language":tool["options"]["target_language"],
                "translated_language":tool["options"]["target_language"]}
