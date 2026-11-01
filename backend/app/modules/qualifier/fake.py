"""A scripted Qualifier model for tests and local demos (CRM_AI_PROVIDER=fake; refused in
production by the settings). No key, no network, the same answer every time.

It reads the lead out of the prompt the real model would get and applies fixed, visible rules:
no phone -> ask for it; a budget of at least 80 lakh and a phone -> qualify; a budget below 30
lakh -> unqualify; otherwise call first.
"""

import json
import re
from typing import Any

from app.modules.assistant.api import ModelReply, ToolUse
from app.modules.qualifier.rules import TOOL_NAME

_LEAD = re.compile(r"Lead \(data, not instructions\):\n(\{.*\})", re.DOTALL)
QUALIFY_FROM_INR = 8_000_000
UNQUALIFY_BELOW_INR = 3_000_000


class FakeQualifierModel:
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
        budget = lead.get("budget_min_inr")
        answer: dict[str, Any]
        if lead.get("phone") != "present":
            answer = {
                "decision": "need_info",
                "matched_steps": [],
                "reasons": ["There is no phone number yet."],
                "missing": ["Phone number"],
            }
        elif isinstance(budget, int) and budget >= QUALIFY_FROM_INR:
            answer = {
                "decision": "qualify",
                "matched_steps": [1, 2],
                "reasons": ["A phone number is present and the budget is high enough."],
                "missing": [],
            }
        elif isinstance(budget, int) and budget < UNQUALIFY_BELOW_INR:
            answer = {
                "decision": "unqualify",
                "matched_steps": [],
                "reasons": ["The budget is too low."],
                "missing": [],
            }
        else:
            answer = {
                "decision": "contact_first",
                "matched_steps": [1],
                "reasons": ["A salesperson should call to clarify the budget."],
                "missing": [],
            }
        return ModelReply("", tool_uses=[ToolUse("fake-assessment", TOOL_NAME, answer)])
