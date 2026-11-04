"""The model behind the lead agent: the same providers as the other agents, or a scripted fake
(tests and local demos; the settings refuse it in production). No key, no network, the same answer
every time.

The fake reads the lead out of the prompt the real model would get and applies fixed, visible
rules: a lead with no phone or already decided -> nothing; a budget below 30 lakh -> unqualified;
a new lead with a phone -> contacted; a contacted lead with a budget of 80 lakh or more ->
qualified; anything else -> nothing.
"""

import json
import re
from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel, ModelReply, ToolUse
from app.modules.lead_agent.rules import TOOL_NAME

_LEAD = re.compile(r"Lead \(data, not instructions\):\n(\{.*\})", re.DOTALL)
QUALIFY_FROM_INR = 8_000_000
UNQUALIFY_BELOW_INR = 3_000_000


class FakeLeadAgentModel:
    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        match = _LEAD.search(system)
        lead: dict[str, Any] = {}
        if match:
            try:
                lead = json.loads(match.group(1).split("\n")[0])
            except ValueError:
                lead = {}
        status, budget = lead.get("status"), lead.get("budget_min_inr")
        answer = {"status": "none", "reason": "Nothing to change."}
        if lead.get("phone") != "present" or status in ("unqualified", "converted", "qualified"):
            pass
        elif isinstance(budget, int) and budget < UNQUALIFY_BELOW_INR:
            answer = {"status": "unqualified", "reason": "The budget is too low."}
        elif status == "new":
            answer = {"status": "contacted", "reason": "A phone number is present; call first."}
        elif status == "contacted" and isinstance(budget, int) and budget >= QUALIFY_FROM_INR:
            answer = {"status": "qualified", "reason": "Contacted, and the budget is high enough."}
        return ModelReply("", tool_uses=[ToolUse("fake-suggestion", TOOL_NAME, answer)])


def model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeLeadAgentModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
