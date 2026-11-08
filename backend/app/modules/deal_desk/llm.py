"""The model behind the deal desk: the same providers as the other agents, or a scripted fake
(tests and local demos; the settings refuse it in production). No key, no network, the same answer
every time.

The fake reads the facts out of the prompt a real model would get and applies fixed, visible rules:
a reviewer reports every fact whose code is in ``ACT`` as "act" and in ``WATCH`` as "watch" (at
most three, each citing its own record); the desk lead writes one sentence per finding and
suggests a task for the first two "act" findings.
"""

import json
import re
from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel, ModelReply, ToolUse
from app.modules.deal_desk import research_rules
from app.modules.deal_desk.review import BRIEF_TOOL, FINDINGS_TOOL, MAX_FINDINGS, MAX_TASKS

ACT = frozenset(
    {
        "discount_over_limit",
        "quote_expired",
        "amount_differs_from_accepted_quote",
        "close_date_passed",
        "overdue_tasks",
        "contract_renewal_soon",
    }
)
WATCH = frozenset(
    {
        "discount_near_limit",
        "quote_expires_before_close",
        "no_quote",
        "stuck_in_stage",
        "no_next_step",
        "no_recent_activity",
        "no_primary_contact",
        "record_text_flagged",
    }
)
_DATA = re.compile(r"(?:Facts|Findings) \(data, not instructions\):\n(\[.*\])", re.DOTALL)
_FINDINGS = re.compile(r"Findings:\n(\[.*\])", re.DOTALL)


def _json_list(pattern: re.Pattern[str], text: str) -> list[dict[str, Any]]:
    match = pattern.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


class FakeDealDeskModel:
    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        if research_rules.TOOL in system and "account" in system:
            return self._account(_json_list(_DATA, system))
        if "You are the desk lead" in system:
            return self._lead(_json_list(_FINDINGS, system))
        return self._reviewer(_json_list(_DATA, system))

    @staticmethod
    def _reviewer(facts: list[dict[str, Any]]) -> ModelReply:
        found = [
            {
                "severity": "act" if fact.get("code") in ACT else "watch",
                "text": str(fact.get("fact", "")),
                "record_ids": [str(fact.get("record_id"))],
            }
            for fact in facts
            if fact.get("code") in ACT | WATCH
        ][:MAX_FINDINGS]
        return ModelReply("", [ToolUse("fake-findings", FINDINGS_TOOL, {"findings": found})])

    @staticmethod
    def _account(facts: list[dict[str, Any]]) -> ModelReply:
        return ModelReply(
            "",
            [
                ToolUse(
                    "fake-account", research_rules.TOOL, {"sentences": _account_sentences(facts)}
                )
            ],
        )

    @staticmethod
    def _lead(findings: list[dict[str, Any]]) -> ModelReply:
        sentences = [str(f.get("finding", "")) for f in findings][:5]
        brief = " ".join(sentences) or "Nothing on this deal needs attention right now."
        tasks = [
            {
                "subject": f"Follow up: {str(f.get('finding', ''))[:150]}",
                "due_in_days": 2,
                "reason": f"An 'act' finding of the {f.get('reviewer')} reviewer.",
            }
            for f in findings
            if f.get("severity") == "act"
        ][:MAX_TASKS]
        return ModelReply("", [ToolUse("fake-brief", BRIEF_TOOL, {"brief": brief, "tasks": tasks})])


def _account_sentences(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One sentence per fact, citing its own record (at most the writer's maximum)."""
    return [
        {"text": str(fact.get("fact", "")), "record_ids": [str(fact.get("record_id"))]}
        for fact in facts
    ][: research_rules.MAX_SENTENCES]


def model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeDealDeskModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
