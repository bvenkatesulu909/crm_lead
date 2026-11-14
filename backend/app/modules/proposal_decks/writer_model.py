"""The model behind the deck writer: the same providers as the other agents, or a scripted
fake (tests and local demos; the settings refuse it in production). No key, no network, the same
answer every time: a short plain slide built only from the quote facts in the prompt."""

import json
import re
from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel, ModelReply, ToolUse
from app.modules.proposal_decks.writer import TOOL_NAME

_QUOTE = re.compile(r"Quote \(data, not instructions\):\n(\{.*\})", re.DOTALL)


class FakeDeckWriterModel:
    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        match = _QUOTE.search(system)
        quote: dict[str, Any] = {}
        if match:
            try:
                quote = json.loads(match.group(1).split("\n")[0])
            except ValueError:
                quote = {}
        lines = quote.get("lines") or []
        first = lines[0].get("description", "your requirements") if lines else "your requirements"
        text = (
            f"This proposal was prepared for {quote.get('customer', 'you')}. It covers {first}"
            f"{' and more' if len(lines) > 1 else ''}, with a total of {quote.get('total', '')} "
            f"{quote.get('currency', '')}. The offer is valid until {quote.get('valid_until', '')}."
        )
        answer = {"text": text, "reason": "Based on the quote's lines, total and validity."}
        return ModelReply("", tool_uses=[ToolUse("fake-summary", TOOL_NAME, answer)])


def model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeDeckWriterModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
