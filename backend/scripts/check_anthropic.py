"""Check that the assistant's Claude settings work: one tiny request with the key in .env.

Run in CMD from the backend folder with the virtual environment active:
    python -m scripts.check_anthropic

Prints only the key TYPE (never the key), the model, and Anthropic's answer or error. Costs a
fraction of a cent.
"""

import sys

import anthropic

from app.core.config import Settings
from app.modules.assistant.llm import ClaudeChatModel


def main() -> int:
    settings = Settings()
    if settings.anthropic_api_key is None:
        print("No CRM_ANTHROPIC_API_KEY in backend\\.env.")
        return 1
    key = settings.anthropic_api_key.get_secret_value()
    kind = "workspace key (sk-ant-api)" if key.startswith("sk-ant-api") else "user-level key"
    print(f"Key type: {kind} | model: {settings.assistant_model}")
    client = ClaudeChatModel(settings)._client
    try:
        reply = client.messages.create(
            model=settings.assistant_model,
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with the single word OK"}],
        )
    except anthropic.APIStatusError as exc:
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error") or {}
        print(f"FAILED (HTTP {exc.status_code}): {error.get('message', exc)}")
        return 1
    except anthropic.APIError as exc:
        print(f"FAILED: {type(exc).__name__}")
        return 1
    text = reply.content[0].text if reply.content and reply.content[0].type == "text" else ""
    print(f"WORKS: Claude answered {text.strip()!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
