"""Lead business rules. Functions here never commit: the router commits once at the end, so
every request is one transaction - it either fully happens or not at all.

Every change to a lead also writes (in the same transaction):
- a timeline entry in ``lead_activities`` for status changes, assignment and conversion;
- an ``audit_log`` row with who changed what, from which value to which value.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import diff, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import SALES_ROLES, Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish as publish_event
from app.modules.accounts import api as accounts_api
from app.modules.contacts import api as contacts_api
from app.modules.identity import api as identity_api
from app.modules.leads import repository, scoring
from app.modules.leads.models import Lead, LeadActivity, LeadAssignment
from app.modules.leads.policies import can_write
from app.modules.leads.repository import LeadFilters
from app.modules.leads.schemas import (
    ActivityCreate,
    ConversionResult,
    LeadConvert,
    LeadCreate,
    LeadRead,
    LeadScore,
    LeadUpdate,
    ScoreFactor,
)
from app.modules.leads.transitions import check_transition
from app.modules.sales import api as sales_api

ENTITY = "lead"
_DETAIL_FIELDS = (
    "first_name",
    "last_name",
    "company_name",
    "email",
    "phone",
    "job_title",
    "source",
)


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # Same message whether the lead doesn't exist, belongs to another tenant or isn't yours.
        super().__init__("Lead not found.")


class LeadConvertedError(ConflictError):
    code = "lead_converted"


class VersionConflictError(ConflictError):
    code = "version_conflict"


class InvalidAssigneeError(DomainError):
    status_code = 422
    code = "invalid_assignee"


# --- helpers ----------------------------------------------------------------------------


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:  # guarded by permissions already; belt and braces
        raise ForbiddenError("Only members of a tenant can work with leads.")
    return principal.tenant_id


def _snapshot(lead: Lead) -> dict[str, object]:
    return {field: getattr(lead, field) for field in (*_DETAIL_FIELDS, "status", "owner_id")}


def _load_for_write(session: Session, principal: Principal, lead_id: uuid.UUID) -> Lead:
    lead = repository.get_readable(session, principal, lead_id, for_update=True)
    if lead is None:
        raise LeadNotFoundError()
    if not can_write(principal, lead):
        raise ForbiddenError("You may view this lead but not change it.")
    return lead


def _reject_if_converted(lead: Lead) -> None:
    if lead.status == "converted":
        raise LeadConvertedError("A converted lead can no longer be changed.")


def _timeline(
    session: Session, principal: Principal, lead: Lead, kind: str, subject: str, body: str | None
) -> None:
    session.add(
        LeadActivity(
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            kind=kind,
            subject=subject,
            body=body,
            actor_user_id=principal.user_id,
        )
    )


def _check_assignee(session: Session, principal: Principal, owner_id: uuid.UUID) -> None:
    if owner_id != principal.user_id and not principal.has_permission(Permission.LEAD_ASSIGN):
        raise ForbiddenError("You may not assign leads to other people.")
    if not identity_api.is_assignable_sales_user(session, _tenant(principal), owner_id):
        raise InvalidAssigneeError(
            "The new owner must be an active sales employee of your organisation."
        )


def _record_assignment(
    session: Session,
    principal: Principal,
    lead: Lead,
    previous: uuid.UUID | None,
    reason: str | None,
) -> None:
    if lead.owner_id is None:
        raise RuntimeError("an assignment needs a new owner")
    session.add(
        LeadAssignment(
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            from_user_id=previous,
            to_user_id=lead.owner_id,
            assigned_by_user_id=principal.user_id,
            reason=reason,
        )
    )
    _timeline(session, principal, lead, "assigned", "Lead assigned", reason)


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError(
            "The lead was changed by someone else. Reload it and try again."
        ) from exc


# --- use cases --------------------------------------------------------------------------


def create_lead(session: Session, principal: Principal, data: LeadCreate) -> Lead:
    tenant_id = _tenant(principal)
    if data.owner_id is not None:
        _check_assignee(session, principal, data.owner_id)
        owner_id: uuid.UUID | None = data.owner_id
    elif principal.roles & SALES_ROLES:
        owner_id = principal.user_id  # sales staff own what they create
    else:
        owner_id = None  # e.g. a tenant admin: stays unassigned until a manager assigns it

    lead = Lead(tenant_id=tenant_id, owner_id=owner_id, **data.model_dump(exclude={"owner_id"}))
    session.add(lead)
    session.flush()
    _timeline(session, principal, lead, "created", "Lead created", None)
    if owner_id is not None:
        _record_assignment(session, principal, lead, None, "Initial owner")
    record_audit(
        session,
        principal,
        action="lead.created",
        entity_type=ENTITY,
        entity_id=lead.id,
        changes=diff({}, _snapshot(lead)),
    )
    _flush(session)
    return lead


def get_lead(session: Session, principal: Principal, lead_id: uuid.UUID) -> Lead:
    lead = repository.get_readable(session, principal, lead_id)
    if lead is None:
        raise LeadNotFoundError()
    return lead


def list_leads(
    session: Session, principal: Principal, filters: LeadFilters
) -> tuple[Sequence[Lead], int]:
    return repository.search(session, principal, filters)


def update_lead(
    session: Session, principal: Principal, lead_id: uuid.UUID, data: LeadUpdate
) -> Lead:
    lead = _load_for_write(session, principal, lead_id)
    _reject_if_converted(lead)
    if lead.version != data.version:
        raise VersionConflictError(
            f"The lead was changed by someone else (now version {lead.version}). Reload it."
        )
    before = _snapshot(lead)
    for field, value in data.changes().items():
        setattr(lead, field, value)
    changes = diff(before, _snapshot(lead))
    if changes:
        record_audit(
            session,
            principal,
            action="lead.updated",
            entity_type=ENTITY,
            entity_id=lead.id,
            changes=changes,
        )
    _flush(session)
    return lead


def _actor(principal: Principal) -> str | None:
    return str(principal.user_id) if principal.user_id else None


def assign_lead(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    owner_id: uuid.UUID,
    reason: str | None,
) -> Lead:
    lead = _load_for_write(session, principal, lead_id)
    _reject_if_converted(lead)
    if not principal.has_permission(Permission.LEAD_ASSIGN):
        raise ForbiddenError("You may not assign leads.")
    if lead.owner_id == owner_id:
        raise ConflictError("The lead already belongs to this person.")
    _check_assignee(session, principal, owner_id)
    previous = lead.owner_id
    lead.owner_id = owner_id
    _record_assignment(session, principal, lead, previous, reason)
    record_audit(
        session,
        principal,
        action="lead.assigned",
        entity_type=ENTITY,
        entity_id=lead.id,
        changes={"owner_id": {"old": previous, "new": owner_id}, "reason": reason},
    )
    publish_event(
        session,
        lead.tenant_id,
        "lead.assigned",
        {"lead_id": str(lead.id), "assignee_id": str(owner_id), "actor_id": _actor(principal)},
    )
    _flush(session)
    return lead


def change_status(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    target: str,
    reason: str | None,
) -> Lead:
    lead = _load_for_write(session, principal, lead_id)
    _reject_if_converted(lead)
    previous = lead.status
    check_transition(previous, target)
    lead.status = target
    _timeline(
        session,
        principal,
        lead,
        "status_changed",
        f"Status changed from {previous} to {target}",
        reason,
    )
    record_audit(
        session,
        principal,
        action="lead.status_changed",
        entity_type=ENTITY,
        entity_id=lead.id,
        changes={"status": {"old": previous, "new": target}, "reason": reason},
    )
    _flush(session)
    return lead


def convert_lead(
    session: Session, principal: Principal, lead_id: uuid.UUID, data: LeadConvert
) -> ConversionResult:
    """Qualified lead -> account (new or existing) + contact (+ opportunity), all or nothing.

    Idempotent: converting an already converted lead returns the original result and
    creates nothing. The row lock taken by _load_for_write makes simultaneous requests wait
    for each other, so a lead can never be converted twice.
    """
    lead = _load_for_write(session, principal, lead_id)
    if lead.status == "converted":
        # The database guarantees these are set for converted leads (ck_leads_converted_*).
        if not (lead.converted_account_id and lead.converted_contact_id and lead.converted_at):
            raise RuntimeError("converted lead without conversion records")
        return ConversionResult(
            lead_id=lead.id,
            account_id=lead.converted_account_id,
            contact_id=lead.converted_contact_id,
            opportunity_id=lead.converted_opportunity_id,
            converted_at=lead.converted_at,
            already_converted=True,
        )

    needed = {Permission.ACCOUNT_WRITE_ALL, Permission.ACCOUNT_WRITE_OWN}
    if not principal.has_permission(Permission.LEAD_CONVERT) or not principal.permissions & needed:
        raise ForbiddenError("You may not convert leads.")
    check_transition(lead.status, "converted", via_conversion=True)

    tenant_id = _tenant(principal)
    person = " ".join(part for part in (lead.first_name, lead.last_name) if part)

    if data.account.existing_account_id is not None:
        # Linking to an account you can't see is treated exactly like a missing account.
        if not accounts_api.is_readable_account(
            session, principal, data.account.existing_account_id
        ):
            raise NotFoundError("Account not found.")
        account_id = data.account.existing_account_id
    else:
        account_id = accounts_api.create_account(
            session,
            tenant_id=tenant_id,
            name=data.account.name or lead.company_name or person,
            website=None,
            phone=lead.phone,
            owner_id=lead.owner_id,
        )

    contact_id = contacts_api.create_contact(
        session,
        tenant_id=tenant_id,
        first_name=lead.first_name,
        last_name=lead.last_name,
        email=lead.email,
        phone=lead.phone,
        job_title=lead.job_title,
        account_id=account_id,
        owner_id=lead.owner_id,
    )

    opportunity_id = None
    if data.opportunity is not None:
        opportunity_id = sales_api.create_opportunity(
            session,
            tenant_id=tenant_id,
            name=data.opportunity.name or f"{lead.company_name or person} - new opportunity",
            account_id=account_id,
            primary_contact_id=contact_id,
            owner_id=lead.owner_id,
            amount=data.opportunity.amount,
            currency=data.opportunity.currency,
            expected_close_date=data.opportunity.expected_close_date,
            created_by_user_id=principal.user_id,
        )

    converted_at = datetime.now(UTC)
    lead.status = "converted"
    lead.converted_at = converted_at
    lead.converted_account_id = account_id
    lead.converted_contact_id = contact_id
    lead.converted_opportunity_id = opportunity_id
    _timeline(session, principal, lead, "converted", "Lead converted", None)
    record_audit(
        session,
        principal,
        action="lead.converted",
        entity_type=ENTITY,
        entity_id=lead.id,
        changes={
            "status": {"old": "qualified", "new": "converted"},
            "account_id": account_id,
            "account_created": data.account.existing_account_id is None,
            "contact_id": contact_id,
            "opportunity_id": opportunity_id,
        },
    )
    _flush(session)
    return ConversionResult(
        lead_id=lead.id,
        account_id=account_id,
        contact_id=contact_id,
        opportunity_id=opportunity_id,
        converted_at=converted_at,
        already_converted=False,
    )


def add_activity(
    session: Session, principal: Principal, lead_id: uuid.UUID, data: ActivityCreate
) -> LeadActivity:
    lead = _load_for_write(session, principal, lead_id)
    activity = LeadActivity(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        kind=data.kind,
        subject=data.subject,
        body=data.body,
        actor_user_id=principal.user_id,
        **({"occurred_at": data.occurred_at} if data.occurred_at else {}),
    )
    session.add(activity)
    _flush(session)
    return activity


def list_activities(
    session: Session, principal: Principal, lead_id: uuid.UUID
) -> Sequence[LeadActivity]:
    return repository.list_activities(session, get_lead(session, principal, lead_id))


def list_assignments(
    session: Session, principal: Principal, lead_id: uuid.UUID
) -> Sequence[LeadAssignment]:
    return repository.list_assignments(session, get_lead(session, principal, lead_id))


def with_scores(session: Session, principal: Principal, leads: Sequence[Lead]) -> list[LeadRead]:
    """Lead responses including score and priority (one query for all of them)."""
    found = repository.scores(session, principal, [lead.id for lead in leads])
    result = []
    for lead in leads:
        read = LeadRead.model_validate(lead)
        if lead.id in found:
            read.score = found[lead.id]
            read.priority = scoring.priority_of(found[lead.id])  # type: ignore[assignment]
        result.append(read)
    return result


def lead_score(session: Session, principal: Principal, lead_id: uuid.UUID) -> LeadScore:
    lead = get_lead(session, principal, lead_id)
    count, last = repository.activity_stats(session, lead)
    score, priority, factors = scoring.explain(lead, count, last, datetime.now(UTC))
    return LeadScore(
        lead_id=lead.id,
        score=score,
        priority=priority,
        factors=[ScoreFactor(label=f.label, points=f.points) for f in factors],
    )
