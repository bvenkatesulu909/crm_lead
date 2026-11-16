"""The model behind the custom agents: the same providers as the staff assistant, or the scripted
fake (tests and local demos; the settings refuse it in production)."""

from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api
from app.modules.assistant.api import ChatModel, ModelReply, ToolUse
from app.modules.custom_agents.run_rules import TOOL_NAME


class FakeCustomAgentModel:
    """A scripted stand-in with no key and no cost. It reads the tool it is offered and picks the
    first thing the agent may suggest: a follow-up task, else a status change, else nothing."""

    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        offered = [tool for tool in tools if tool.get("name") == TOOL_NAME]
        if not offered:
            return ModelReply("", tool_uses=[], usage={"input_tokens": 10, "output_tokens": 0})
        actions = offered[0]["input_schema"]["properties"]["action"]["enum"]
        if "create_task" in actions:
            arguments: dict[str, Any] = {
                "action": "create_task",
                "task_subject": "Follow up with this record (demo suggestion)",
                "due_in_days": 2,
                "reason": "Demo agent: nothing was logged recently.",
            }
        elif "set_status" in actions:
            arguments = {
                "action": "set_status",
                "status": "contacted",
                "reason": "Demo agent: the lead looks ready for a first call.",
            }
        else:
            arguments = {"action": "none", "reason": "Demo agent: nothing to suggest."}
        return ModelReply(
            "",
            tool_uses=[ToolUse("fake-1", TOOL_NAME, arguments)],
            usage={"input_tokens": 120, "output_tokens": 40},
        )


def model_for(settings: Settings) -> ChatModel:
    if settings.ai_provider == "fake":
        return FakeCustomAgentModel()
    if settings.ai_provider == "deepseek":
        return assistant_api.chat_model_for(settings, "deepseek")
    return assistant_api.chat_model_for(settings, "anthropic")
