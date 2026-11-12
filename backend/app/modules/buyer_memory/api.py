"""Public interface of the buyer memory module. Other modules import only from here."""

from app.modules.buyer_memory import service

record_from_website_chat = service.record_from_website_chat

__all__ = ["record_from_website_chat"]
