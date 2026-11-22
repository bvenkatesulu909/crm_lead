"""The model behind the video-script drafter: the same providers as the other agents, or a scripted
fake (tests and local demos; the settings refuse it in production). No key, no network, the same
answer every time: a short plain script built only from the facts in the prompt, in English."""

import json
import re
from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel, ModelReply, ToolUse
from app.modules.video_brief.draft import TOOL_NAME

_FACTS = re.compile(r"Facts \(data, not instructions\):\n(\{.*\})", re.DOTALL)


class FakeVideoBriefModel:
    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        match = _FACTS.search(system)
        facts: dict[str, Any] = {}
        if match:
            try:
                facts = json.loads(match.group(1).split("\n")[0])
            except ValueError:
                facts = {}
        lines = [f"Hello {facts.get('first_name') or 'there'},"]
        for fact in facts.get("facts", [])[:3]:
            lines.append(f"On {fact['label']}, you told us: {fact['value']}.")
        for price in facts.get("quote_prices", [])[:2]:
            lines.append(f"{price['text']}.")
        for guess in facts.get("ask_only_as_questions", [])[:2]:
            lines.append(f"Is {guess['value']} still right for {guess['label']}?")
        lines.append("Thank you for your time.")
        answer = {"lines": lines, "reason": "Based on the confirmed facts."}
        return ModelReply("", tool_uses=[ToolUse("fake-script", TOOL_NAME, answer)])


def model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeVideoBriefModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
