"""Read-only checks about one lead for the lead agent (ADR 0022, step LA3)."""

import re
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.leads import repository
from app.modules.leads.models import Lead
from app.modules.leads.policies import readable_leads

MIN_PHONE_DIGITS = 7  # fewer digits would match unrelated people


def duplicate_count(session: Session, principal: Principal, lead_id: uuid.UUID) -> int | None:
    """How many OTHER leads the asker may read share this lead's e-mail address or phone number,
    or ``None`` when the asker may not read the lead. Only a number leaves this function: the
    other leads' names and contact details never do. An agent who sees only their own leads
    counts only those; that is the record rule, not a bug."""
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    matches = []
    if lead.email:
        matches.append(func.lower(Lead.email) == lead.email.lower())
    digits = re.sub(r"\D", "", lead.phone or "")
    if len(digits) >= MIN_PHONE_DIGITS:
        matches.append(func.regexp_replace(Lead.phone, r"\D", "", "g") == digits)
    if not matches:
        return 0
    count = session.scalar(
        select(func.count()).where(
            and_(readable_leads(principal), Lead.id != lead_id, or_(*matches))
        )
    )
    return int(count or 0)
