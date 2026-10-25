"""The model behind the public website chat (ADR 0013): DeepSeek, Claude, or a fake.

The fake needs no key and behaves the same every time, so tests and local demos can run the
whole flow - ask for details, call save_lead, thank the visitor - without a paid service.
Settings refuse it in production.
"""

import json
import re
from typing import Any

from app.core.config import Settings
from app.modules.assistant import api as assistant_api

_PHONE = re.compile(r"\+?\d[\d\s-]{7,16}\d")
_NAME = re.compile(
    r"(?:\bI am|\bI'm|\bmy name is)\s+([A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,3}?)"
    r"(?=\s*(?:,|\.|\band\b|\bphone\b|\bmy\b|$))",
    re.IGNORECASE,
)


class FakeVisitorModel:
    """Asks for a phone number; once it sees one, saves the lead; then thanks the visitor."""

    available = True

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> assistant_api.ModelReply:
        last = messages[-1] if messages else {"content": ""}
        content = last.get("content")
        if isinstance(content, list):  # the result of our tool call
            results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            body = str(results[0].get("content", "")) if results else ""
            if '"already_saved"' in body:
                return assistant_api.ModelReply(
                    "Your details were already passed on to our property advisor. Thank you!"
                )
            if results and not results[0].get("is_error"):
                return assistant_api.ModelReply(
                    "Thank you! Your details were passed on to our property advisor, who will "
                    "call you soon."
                )
            return assistant_api.ModelReply("Could you share your name and phone number again?")
        text = str(content or "")
        phone = _PHONE.search(text)
        if not phone:
            return assistant_api.ModelReply(
                "Hello! I can help you find a home. May I have your name and phone number?"
            )
        name = _NAME.search(text)
        arguments = {
            "full_name": name.group(1).strip() if name else "Website visitor",
            "phone": phone.group(0).strip(),
            "property_type": "apartment",
            "budget_min_inr": 12_000_000,
            "budget_max_inr": 15_000_000,
            "location": "Kokapet, Hyderabad",
        }
        return assistant_api.ModelReply(
            "",
            [
                assistant_api.ToolUse(
                    f"fake-{len(messages)}", "save_lead", json.loads(json.dumps(arguments))
                )
            ],
            "tool_use",
        )


def build_public_chat_model(settings: Settings) -> assistant_api.ChatModel:
    if settings.public_chat_provider == "fake":
        return FakeVisitorModel()
    return assistant_api.chat_model_for(settings, settings.public_chat_provider)
