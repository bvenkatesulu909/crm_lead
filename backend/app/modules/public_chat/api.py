"""Public interface of the public_chat module. Other modules (and the worker) import only this."""

from app.modules.public_chat.service import delete_stale_conversations

__all__ = ["delete_stale_conversations"]
