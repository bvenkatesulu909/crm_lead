"""Public interface of the call recordings module. Other modules import only from here."""

from app.modules.calls import service

expire_stale_uploads = service.expire_stale
AGENT_KEY = service.AGENT_KEY

__all__ = ["AGENT_KEY", "expire_stale_uploads"]
