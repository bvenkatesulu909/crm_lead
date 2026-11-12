"""Public interface of the leads module.

Every function applies the leads module's own record-level policy: sales agents only ever get
their own leads.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import DomainError, ForbiddenError
from app.core.records import LeadQualifierFacts, LeadSnapshot, Recipient, RecordFacts
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.leads import repository, service
from app.modules.leads.checks import duplicate_count
from app.modules.leads.metrics import (
    FollowUp,
    FollowUps,
    LeadMetrics,
    OwnerLeadFigures,
    conversion_table,
    created_at_of,
    follow_ups,
    lead_figures_by_owner,
    lead_metrics,
    recent_lead_activities,
    web_lead_quality_table,
    web_leads_by_month,
)
from app.modules.leads.models import LEAD_STATUSES, Lead, LeadActivity
from app.modules.leads.policies import readable_leads
from app.modules.leads.repository import LeadFilters
from app.modules.leads.schemas import ActivityCreate, LeadCreate, LeadUpdate

__all__ = [
    "COMPANY_FIELDS",
    "InvalidCompanySuggestionError",
    "LeadCompany",
    "apply_company_details",
    "lead_company",
    "conversion_table",
    "duplicate_count",
    "created_at_of",
    "web_lead_quality_table",
    "web_leads_by_month",
    "create_lead_from_website",
    "EXPORT",
    "export_table",
    "qualifier_facts",
    "set_lead_status",
    "assign_lead",
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
    "lead_activity_belongs",
    "BuyerFields",
    "buyer_fields",
    "owned_lead_ids",
    "lead_figures_by_owner",
    "lead_metrics",
    "recent_lead_activities",
]


def is_readable_lead(session: Session, principal: Principal, lead_id: uuid.UUID) -> bool:
    return repository.get_readable(session, principal, lead_id) is not None


def lead_activity_belongs(
    session: Session, principal: Principal, lead_id: uuid.UUID, activity_id: uuid.UUID
) -> bool:
    """Is this timeline entry one of this lead's - and may the person read the lead?"""
    if principal.tenant_id is None or not is_readable_lead(session, principal, lead_id):
        return False
    return (
        session.scalar(
            select(LeadActivity.id).where(
                LeadActivity.tenant_id == principal.tenant_id,
                LeadActivity.lead_id == lead_id,
                LeadActivity.id == activity_id,
            )
        )
        is not None
    )


@dataclass(frozen=True)
class BuyerFields:
    """The lead form's details about what the buyer wants (for buyer memory, ADR 0028)."""

    property_type: str | None
    budget_min_inr: int | None
    budget_max_inr: int | None
    location: str | None


def buyer_fields(session: Session, principal: Principal, lead_id: uuid.UUID) -> BuyerFields | None:
    """What the lead form says the buyer wants, if this person may read the lead, else None."""
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    return BuyerFields(lead.property_type, lead.budget_min_inr, lead.budget_max_inr, lead.location)


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


def create_lead_from_website(
    session: Session,
    principal: Principal,
    *,
    first_name: str | None,
    last_name: str,
    phone: str,
    email: str | None,
    property_type: str | None,
    budget_min_inr: int | None,
    budget_max_inr: int | None,
    location: str | None,
    notes: str | None,
    preferred_language: str | None = None,
    cleaned_codes: list[str] | None = None,
) -> uuid.UUID:
    """A lead from the public website chat (ADR 0013), with this module's own rules and audit.

    ``principal`` is the tenant's Automation identity, so the lead starts unassigned. A
    timeline note says where it came from (and holds the visitor's own notes, if any)."""
    lead = service.create_lead(
        session,
        principal,
        LeadCreate.model_validate(
            {
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "email": email,
                "source": "web",
                "property_type": property_type,
                "budget_min_inr": budget_min_inr,
                "budget_max_inr": budget_max_inr,
                "location": location,
                "preferred_language": preferred_language,
            }
        ),
    )
    service.add_activity(
        session,
        principal,
        lead.id,
        ActivityCreate(kind="note", subject="Created from the website chat", body=notes),
    )
    if cleaned_codes:
        # Only the kinds of finding, never the removed text (ADR 0018).
        service.add_activity(
            session,
            principal,
            lead.id,
            ActivityCreate(
                kind="note",
                subject="Some text from the website chat was cleaned",
                body="Found in what the visitor or the assistant wrote: "
                + ", ".join(cleaned_codes),
            ),
        )
    return lead.id


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


def lead_snapshot(
    session: Session, principal: Principal, lead_id: uuid.UUID
) -> LeadSnapshot | None:
    """State and free text of a lead this principal may see (for the Sentinel, ADR 0017)."""
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    fields = (lead.first_name, lead.last_name, lead.company_name, lead.job_title, lead.location)
    texts = [text for text in fields if text]
    for activity in list(repository.list_activities(session, lead))[:10]:
        texts.append(f"{activity.subject}\n{activity.body or ''}")
    return LeadSnapshot(lead.tenant_id, lead.status, lead.owner_id, texts, lead.version)


def qualifier_facts(
    session: Session, principal: Principal, lead_id: uuid.UUID
) -> LeadQualifierFacts | None:
    """The few fields of a lead the Qualifier may see (docs/qualifier.md), or None if this
    principal may not read the lead. Phone and e-mail are only "present" or "missing"."""
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    score = service.lead_score(session, principal, lead_id)
    name = " ".join(part for part in (lead.first_name, lead.last_name) if part)
    return LeadQualifierFacts(
        lead_id=lead.id,
        tenant_id=lead.tenant_id,
        owner_id=lead.owner_id,
        status=lead.status,
        fields={
            "name": name,
            "company": lead.company_name,
            "source": lead.source,
            "phone": "present" if lead.phone else "missing",
            "email": "present" if lead.email else "missing",
            "property_type": lead.property_type,
            "budget_min_inr": lead.budget_min_inr,
            "budget_max_inr": lead.budget_max_inr,
            "location": lead.location,
            "score": score.score,
        },
        score_reasons=[factor.label for factor in score.factors][:10],
    )


def set_lead_status(
    session: Session, principal: Principal, lead_id: uuid.UUID, status: str, reason: str
) -> None:
    """Change a lead's status with the leads module's own rules (transitions, audit)."""
    service.change_status(session, principal, lead_id, status, reason)


def assign_lead(
    session: Session, principal: Principal, lead_id: uuid.UUID, owner_id: uuid.UUID, reason: str
) -> None:
    """Give a lead to a sales person with the same rules as the Assign button (permission,
    assignee check, history, audit, event)."""
    service.assign_lead(session, principal, lead_id, owner_id, reason)


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


# --- the company behind a lead (BP-02, ADR 0026) ------------------------------------------------


@dataclass(frozen=True)
class LeadCompany:
    """What the company-details feature may know about a lead the person can read: the three
    company fields, the e-mail address (only its domain is used, to find the company's site) and
    the version for a later save."""

    company_name: str | None
    website: str | None
    industry: str | None
    size: str | None
    email: str | None
    version: int


COMPANY_FIELDS = ("company_website", "company_industry", "company_size")


class InvalidCompanySuggestionError(DomainError):
    status_code = 422
    code = "invalid_company_suggestion"

    def __init__(self) -> None:
        super().__init__("The suggestion is no longer valid. Ask for the company details again.")


def lead_company(session: Session, principal: Principal, lead_id: uuid.UUID) -> LeadCompany | None:
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        return None
    return LeadCompany(
        company_name=lead.company_name,
        website=lead.company_website,
        industry=lead.company_industry,
        size=lead.company_size,
        email=lead.email,
        version=lead.version,
    )


def apply_company_details(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    *,
    version: int,
    values: dict[str, str],
    evidence_id: uuid.UUID,
) -> None:
    """Save chosen company suggestions with the normal lead rules (who may write, the version,
    the field checks, the ``lead.updated`` audit), then note where they came from."""
    if not values or set(values) - set(COMPANY_FIELDS):
        raise InvalidCompanySuggestionError()
    try:
        data = LeadUpdate.model_validate({"version": version, **values})
    except ValidationError:
        raise InvalidCompanySuggestionError() from None
    service.update_lead(session, principal, lead_id, data)
    record_audit(
        session,
        principal,
        action="lead.enriched",
        entity_type="lead",
        entity_id=lead_id,
        changes={
            "fields": sorted(values),
            "source": "company_site",
            "evidence_id": str(evidence_id),
        },
    )
