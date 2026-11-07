"""Public interface of the assistant module. Other modules import only from here.

The public website chat (ADR 0013) reuses the model interface, the providers and the
guardrails; it keeps its own conversations and tools.
"""

from typing import Literal

from app.core.config import Settings
from app.modules.assistant import guardrails, staff_conversations
from app.modules.assistant.llm import (
    AssistantUnavailableError,
    ChatModel,
    ClaudeChatModel,
    DeepSeekChatModel,
    ModelReply,
    TextStream,
    ToolUse,
    UnconfiguredChatModel,
    stream_reply,
)

__all__ = [
    "AssistantUnavailableError",
    "ChatModel",
    "ModelReply",
    "TextStream",
    "ToolUse",
    "chat_model_for",
    "delete_stale_staff_conversations",
    "inspect_input",
    "sanitise_output",
    "stream_reply",
]

inspect_input = guardrails.inspect_input
# The worker's clean-up of quiet staff assistant conversations (ADR 0023).
delete_stale_staff_conversations = staff_conversations.delete_stale
sanitise_output = guardrails.sanitise_output


def chat_model_for(settings: Settings, provider: Literal["deepseek", "anthropic"]) -> ChatModel:
    """The model of one provider, or a "not configured" model when its key is missing."""
    if provider == "deepseek":
        if settings.deepseek_api_key is None:
            return UnconfiguredChatModel()
        return DeepSeekChatModel(settings)
    if settings.anthropic_api_key is None:
        return UnconfiguredChatModel()
    return ClaudeChatModel(settings)
