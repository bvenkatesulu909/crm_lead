"""Public interface of the leads module.

Every function applies the leads module's own record-level policy: sales agents only ever get
their own leads.
"""

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ForbiddenError
from app.core.records import Recipient, RecordFacts
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.leads import repository, service
from app.modules.leads.metrics import (
    FollowUp,
    FollowUps,
    LeadMetrics,
    OwnerLeadFigures,
    conversion_table,
    follow_ups,
    lead_figures_by_owner,
    lead_metrics,
    recent_lead_activities,
)
from app.modules.leads.models import LEAD_STATUSES, Lead
from app.modules.leads.policies import readable_leads
from app.modules.leads.repository import LeadFilters

__all__ = [
    "conversion_table",
    "EXPORT",
    "export_table",
    "set_lead_status",
    "lead_facts",
    "LEAD_STATUSES",
    "lead_brief",
    "lead_recipient",
    "FollowUp",
    "FollowUps",
    "LeadMetrics",
    "OwnerLeadFigures",
    "follow_ups",
    "is_readable_lead",
    "owned_lead_ids",
    "lead_figures_by_owner",
    "lead_metrics",
    "recent_lead_activities",
]


def is_readable_lead(session: Session, principal: Principal, lead_id: uuid.UUID) -> bool:
    return repository.get_readable(session, principal, lead_id) is not None


def owned_lead_ids(principal: Principal) -> Select[uuid.UUID]:
    """Subquery: IDs of the (not deleted) leads this user owns in their tenant."""
    return select(Lead.id).where(
        Lead.tenant_id == principal.tenant_id,
        Lead.owner_id == principal.user_id,
        Lead.deleted_at.is_(None),
    )


def lead_brief(session: Session, principal: Principal, lead_id: uuid.UUID) -> str | None:
    """A short label for a lead this principal may see (for notifications), else None."""
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    name = " ".join(p for p in (lead.first_name, lead.last_name) if p)
    return f"{name} ({lead.company_name})" if lead.company_name else name


def lead_recipient(session: Session, principal: Principal, lead_id: uuid.UUID) -> Recipient | None:
    """Who to write to (Communication Center), if this principal may see the lead, else None."""
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    return Recipient(
        first_name=lead.first_name,
        full_name=" ".join(p for p in (lead.first_name, lead.last_name) if p),
        email=lead.email,
        company=lead.company_name,
        account_id=None,
        consent_withdrawn=False,
    )


def lead_facts(session: Session, principal: Principal, lead_id: uuid.UUID) -> RecordFacts | None:
    """Facts for workflow rules, if this principal may see the lead."""
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    return RecordFacts(
        record_type="lead",
        record_id=lead.id,
        label=lead_brief(session, principal, lead_id) or "Lead",
        link=f"/leads/{lead.id}",
        owner_id=lead.owner_id,
        account_id=None,
        lead_id=lead.id,
        values={"status": lead.status, "source": lead.source or ""},
    )


def set_lead_status(
    session: Session, principal: Principal, lead_id: uuid.UUID, status: str, reason: str
) -> None:
    """Change a lead's status with the leads module's own rules (transitions, audit)."""
    service.change_status(session, principal, lead_id, status, reason)


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("first_name", "First name", "text"),
        Column("last_name", "Last name", "text"),
        Column("company_name", "Company", "text"),
        Column("email", "E-mail", "text"),
        Column("phone", "Phone", "text"),
        Column("source", "Source", "text"),
        Column("status", "Status", "text"),
        Column("owner_id", "Owner", "user"),
        Column("converted_at", "Converted", "datetime"),
    ),
    statuses=LEAD_STATUSES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Lead,
        columns={key: getattr(Lead, key) for key in allowed},
        wanted=wanted,
        condition=readable_leads(principal),
        created=Lead.created_at,
        owner=Lead.owner_id,
        status=Lead.status,
        filters=filters,
    )


# --- staff assistant (read-only, record-policy enforced) -------------------------------------


def search_leads(
    session: Session, principal: Principal, *, q: str = "", limit: int = 10
) -> list[dict[str, Any]]:
    if not (
        principal.has_permission(Permission.LEAD_READ_ALL)
        or principal.has_permission(Permission.LEAD_READ_OWN)
    ):
        raise ForbiddenError("You may not read leads.")
    items, _ = service.list_leads(
        session, principal, LeadFilters(q=q.strip()[:100] or None, limit=min(limit, 50))
    )
    return [
        {
            "id": str(lead.id),
            "name": " ".join(part for part in (lead.first_name, lead.last_name) if part),
            "company": lead.company_name,
            "email": lead.email,
            "status": lead.status,
            "link": f"/leads/{lead.id}",
        }
        for lead in items
    ]
