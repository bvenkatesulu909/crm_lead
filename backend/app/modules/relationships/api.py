"""Public interface of the relationships module. Other modules import only from here."""

from app.modules.relationships.service import account_health

__all__ = ["account_health"]
