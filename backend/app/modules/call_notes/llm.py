"""The model behind the call notes: the same providers as the other agents, or a scripted fake for
local demos and tests (the settings refuse it in production)."""

import re
from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel, ModelReply, ToolUse
from app.modules.call_notes.answer import TOOL_NAME

_LINE = re.compile(r"^\[(\d+)-(\d+)\] (.+)$", re.MULTILINE)


class FakeCallNotesModel:
    """A scripted stand-in with no key and no cost. It reads the first transcript line it is
    shown and quotes it for the first field of the checklist, so a demo shows a real, verifiable
    quote; every other field stays unknown."""

    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        offered = [tool for tool in tools if tool.get("name") == TOOL_NAME]
        if not offered:
            return ModelReply("", tool_uses=[], usage={"input_tokens": 10, "output_tokens": 0})
        properties = offered[0]["input_schema"]["properties"]["checklist"]["items"]["properties"]
        fields: list[str] = properties["field"]["enum"]
        text = "\n".join(str(m.get("content", "")) for m in messages)
        found = _LINE.search(text)
        checklist: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        if found:
            start, end, quote = int(found.group(1)), int(found.group(2)), found.group(3)[:300]
            checklist.append(
                {
                    "field": fields[0],
                    "state": "stated",
                    "value": " ".join(quote.split()[:3]),
                    "quote": quote,
                    "start_ms": start,
                    "end_ms": end,
                }
            )
            notes.append(
                {
                    "text": "Demo note: the first thing said on the call.",
                    "quote": quote,
                    "start_ms": start,
                    "end_ms": end,
                }
            )
        checklist += [{"field": key, "state": "unknown"} for key in fields[len(checklist) :]]
        return ModelReply(
            "",
            tool_uses=[ToolUse("fake-1", TOOL_NAME, {"checklist": checklist, "notes": notes})],
            usage={"input_tokens": 200, "output_tokens": 80},
        )


def model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeCallNotesModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
