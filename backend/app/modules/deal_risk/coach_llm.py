"""The model behind the deal risk coach: the same providers as the other agents, or a scripted fake
(tests and local demos; the settings refuse it in production). No key, no network, the same answer
every time.

The fake reads the forecast out of the prompt and writes one line of advice per reason (at most
three), citing that reason's code, and one follow-up task for the highest-scoring reason when the
forecast is not low.
"""

import json
import re
from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel, ModelReply, ToolUse
from app.modules.deal_risk.coach_rules import TOOL_NAME

_FORECAST = re.compile(r"Forecast \(data, not instructions\):\n(\{.*\})", re.DOTALL)


class FakeDealRiskCoachModel:
    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        forecast: dict[str, Any] = {}
        match = _FORECAST.search(system)
        if match:
            try:
                forecast = json.loads(match.group(1).split("\n")[0])
            except ValueError:
                forecast = {}
        reasons = sorted(
            forecast.get("reasons", []), key=lambda r: r.get("points", 0), reverse=True
        )
        advice = [
            {"text": f"Act on this first: {r['sentence']}.", "factors": [r["code"]]}
            for r in reasons[:3]
        ]
        tasks = (
            [{"subject": "Call the buyer and agree a next step", "due_in_days": 2,
              "factor": reasons[0]["code"]}]
            if reasons and forecast.get("level") != "low"
            else []
        )  # fmt: skip
        answer = {"advice": advice, "tasks": tasks}
        return ModelReply("", tool_uses=[ToolUse("fake-advice", TOOL_NAME, answer)])


def coach_model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeDealRiskCoachModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
