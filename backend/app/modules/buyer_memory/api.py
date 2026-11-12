"""Public interface of the buyer memory module. Other modules import only from here."""

import uuid

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.buyer_memory import rules, service

record_from_website_chat = service.record_from_website_chat
MemoryArranged = rules.Arranged
KEYS = tuple((k.key, k.label) for k in rules.KEYS)
budget_text = rules.budget_text
property_type_text = rules.property_type_text

__all__ = [
    "KEYS",
    "MemoryArranged",
    "budget_text",
    "current_memory",
    "property_type_text",
    "record_from_website_chat",
]


def current_memory(
    session: Session, principal: Principal, lead_id: uuid.UUID
) -> rules.Arranged | None:
    """The current entries, history and gaps of a lead's buyer memory, or None if this person may
    not read the lead."""
    try:
        return service.view(session, principal, lead_id)
    except service.LeadNotFoundError:
        return None
