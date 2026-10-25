"""A scripted staff assistant model for tests and local demos (ADR 0014, step AP5).

No key, no network. It understands exactly one sentence:

    mark lead <lead id> as contacted|qualified|unqualified [because <reason>]

and answers with a ``propose_lead_status`` tool call - the same path a real model takes, so the
approval queue can be tried end to end. ``CRM_AI_PROVIDER=fake`` selects it; settings refuse it
in production.
"""

import re
from typing import Any

from app.modules.assistant.llm import ModelReply, ToolUse

_REQUEST = re.compile(
    r"\bmark lead (?P<lead>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) "
    r"as (?P<status>contacted|qualified|unqualified)\b(?: because (?P<reason>.+))?",
    re.IGNORECASE | re.DOTALL,
)
HELP = (
    "This demo assistant only understands: mark lead <lead id> as contacted because <reason>. "
    "(Statuses: contacted, qualified, unqualified.)"
)
WAITING = "I proposed it. It is waiting for a manager's approval - nothing has changed yet."
REFUSED = "I could not propose that. Please check the lead and try again."
DEFAULT_REASON = "Requested by the employee in the assistant."


class FakeStaffModel:
    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        last = messages[-1]["content"] if messages else ""
        if isinstance(last, list):  # the results of the tool call we made
            results = [part for part in last if part.get("type") == "tool_result"]
            return ModelReply(REFUSED if any(r.get("is_error") for r in results) else WAITING)
        found = _REQUEST.search(str(messages[0]["content"]))
        if found is None:
            return ModelReply(HELP)
        return ModelReply(
            "",
            [
                ToolUse(
                    "fake-1",
                    "propose_lead_status",
                    {
                        "lead_id": found["lead"].lower(),
                        "status": found["status"].lower(),
                        "reason": (found["reason"] or DEFAULT_REASON).strip()[:500],
                    },
                )
            ],
            stop_reason="tool_use",
        )
