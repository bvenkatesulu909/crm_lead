"""Opportunity (pipeline) business rules. Functions here never commit: the router commits once.

Pipeline rules:
- an opportunity moves freely between the four OPEN stages (Kanban);
- "won" needs an estimated value; "lost" needs a reason; both set the close date;
- a closed deal is read-only until a manager reopens it;
- every stage change is stored in ``opportunity_stage_changes`` and every change in the
  audit log, in the same transaction.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import diff, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import SALES_ROLES, Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.reporting import money_by_currency
from app.modules.accounts import api as accounts_api
from app.modules.contacts import api as contacts_api
from app.modules.identity import api as identity_api
from app.modules.sales import repository
from app.modules.sales.models import (
    CLOSED_STAGES,
    OPEN_STAGES,
    STAGE_PROBABILITY,
    Opportunity,
    OpportunityStageChange,
)
from app.modules.sales.policies import can_write
from app.modules.sales.repository import OpportunityFilters
from app.modules.sales.schemas import (
    Board,
    BoardColumn,
    MoneyRead,
    OpportunityCreate,
    OpportunityRead,
    OpportunityUpdate,
    StageChangeRead,
)

ENTITY = "opportunity"
CENT = Decimal("0.01")
_FIELDS = (
    "name",
    "primary_contact_id",
    "owner_id",
    "amount",
    "currency",
    "expected_close_date",
    "next_step",
    "description",
    "stage",
)


class OpportunityNotFoundError(NotFoundError):
    code = "opportunity_not_found"

    def __init__(self) -> None:
        super().__init__("Opportunity not found.")


class RelatedNotFoundError(NotFoundError):
    """An account or contact to link doesn't exist or isn't visible to you."""

    code = "related_not_found"


class VersionConflictError(ConflictError):
    code = "version_conflict"


class OpportunityClosedError(ConflictError):
    code = "opportunity_closed"


class InvalidOpportunityError(DomainError):
    status_code = 422
    code = "invalid_opportunity"


# --- helpers ----------------------------------------------------------------------------


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None or principal.user_type != "staff":
        raise ForbiddenError("Only staff of an organisation can work with opportunities.")
    return principal.tenant_id


def _snapshot(o: Opportunity) -> dict[str, object]:
    return {field: getattr(o, field) for field in _FIELDS}


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError(
            "The opportunity was changed by someone else. Reload it and try again."
        ) from exc


def _audit(
    session: Session, principal: Principal, o: Opportunity, action: str, changes: dict[str, Any]
) -> None:
    record_audit(
        session, principal, action=action, entity_type=ENTITY, entity_id=o.id, changes=changes
    )


def _stage_change(
    session: Session, principal: Principal, o: Opportunity, old: str | None, note: str | None
) -> None:
    session.add(
        OpportunityStageChange(
            tenant_id=o.tenant_id,
            opportunity_id=o.id,
            from_stage=old,
            to_stage=o.stage,
            note=note,
            changed_by_user_id=principal.user_id,
        )
    )


def _load_for_write(session: Session, principal: Principal, opp_id: uuid.UUID) -> Opportunity:
    o = repository.get_readable(session, principal, opp_id, for_update=True)
    if o is None:
        raise OpportunityNotFoundError()
    if not can_write(principal, o):
        raise ForbiddenError("You may view this opportunity but not change it.")
    return o


def _check_version(o: Opportunity, version: int) -> None:
    if o.version != version:
        raise VersionConflictError(
            f"The opportunity was changed by someone else (now version {o.version}). Reload it."
        )


def _check_open(o: Opportunity) -> None:
    if o.stage in CLOSED_STAGES:
        raise OpportunityClosedError(
            "This opportunity is closed. A manager can reopen it if it needs to change."
        )


def _check_owner(session: Session, principal: Principal, owner_id: uuid.UUID) -> None:
    if owner_id != principal.user_id and not principal.has_permission(
        Permission.OPPORTUNITY_WRITE_ALL
    ):
        raise ForbiddenError("You may not give opportunities to other people.")
    if not identity_api.is_assignable_sales_user(session, _tenant(principal), owner_id):
        raise InvalidOpportunityError(
            "The owner must be an active sales employee of your organisation."
        )


def _check_contact(
    session: Session, principal: Principal, contact_id: uuid.UUID, account_id: uuid.UUID
) -> None:
    visible, contact_account = contacts_api.contact_account_id(session, principal, contact_id)
    if not visible:
        raise RelatedNotFoundError("Contact not found.")
    if contact_account != account_id:
        raise InvalidOpportunityError("The primary contact must work at the same account.")


# --- use cases --------------------------------------------------------------------------


def create_opportunity(
    session: Session, principal: Principal, data: OpportunityCreate
) -> Opportunity:
    tenant_id = _tenant(principal)
    if not accounts_api.is_readable_account(session, principal, data.account_id):
        raise RelatedNotFoundError("Account not found.")
    if data.owner_id is not None:
        _check_owner(session, principal, data.owner_id)
        owner_id: uuid.UUID | None = data.owner_id
    elif principal.roles & SALES_ROLES:
        owner_id = principal.user_id
    else:
        owner_id = None
    if data.primary_contact_id is not None:
        _check_contact(session, principal, data.primary_contact_id, data.account_id)

    o = Opportunity(tenant_id=tenant_id, owner_id=owner_id, **data.model_dump(exclude={"owner_id"}))
    session.add(o)
    session.flush()
    _stage_change(session, principal, o, None, "Created")
    _audit(session, principal, o, "opportunity.created", diff({}, _snapshot(o)))
    _flush(session)
    return o


def get_opportunity(session: Session, principal: Principal, opp_id: uuid.UUID) -> Opportunity:
    o = repository.get_readable(session, principal, opp_id)
    if o is None:
        raise OpportunityNotFoundError()
    return o


def list_opportunities(
    session: Session, principal: Principal, filters: OpportunityFilters
) -> tuple[Sequence[Opportunity], int]:
    return repository.search(session, principal, filters)


def board(
    session: Session,
    principal: Principal,
    filters: OpportunityFilters,
    *,
    limit: int,
    closed_days: int,
) -> Board:
    since = datetime.now(UTC) - timedelta(days=closed_days)

    def column(stage: str) -> BoardColumn:
        cards, count, sums = repository.column(
            session,
            principal,
            filters,
            stage,
            closed_since=since if stage in CLOSED_STAGES else None,
            limit=limit,
        )
        value = money_by_currency(sums)
        probability = STAGE_PROBABILITY[stage]
        return BoardColumn(
            stage=stage,
            probability=probability,
            count=count,
            value=[MoneyRead(currency=m.currency, amount=m.amount) for m in value],
            weighted=[
                MoneyRead(
                    currency=m.currency,
                    amount=(m.amount * probability / 100).quantize(CENT),
                )
                for m in value
            ],
            items=[OpportunityRead.model_validate(o) for o in cards],
        )

    return Board(
        columns=[column(stage) for stage in OPEN_STAGES],
        won=column("closed_won"),
        lost=column("closed_lost"),
    )


def update_opportunity(
    session: Session, principal: Principal, opp_id: uuid.UUID, data: OpportunityUpdate
) -> Opportunity:
    o = _load_for_write(session, principal, opp_id)
    _check_version(o, data.version)
    _check_open(o)
    changes = data.changes()
    if "owner_id" in changes and changes["owner_id"] != o.owner_id:
        if not principal.has_permission(Permission.OPPORTUNITY_WRITE_ALL):
            raise ForbiddenError("Only managers and administrators can change the deal owner.")
        if data.owner_id is not None:
            _check_owner(session, principal, data.owner_id)
    if data.primary_contact_id is not None and data.primary_contact_id != o.primary_contact_id:
        _check_contact(session, principal, data.primary_contact_id, o.account_id)
    before = _snapshot(o)
    for field, value in changes.items():
        setattr(o, field, value)
    changed = diff(before, _snapshot(o))
    if changed:
        _audit(session, principal, o, "opportunity.updated", changed)
    _flush(session)
    return o


def move_stage(
    session: Session,
    principal: Principal,
    opp_id: uuid.UUID,
    *,
    version: int,
    stage: str,
    note: str | None,
) -> Opportunity:
    o = _load_for_write(session, principal, opp_id)
    _check_version(o, version)
    _check_open(o)
    if stage not in OPEN_STAGES:
        raise InvalidOpportunityError("Use 'won' or 'lost' to close an opportunity.")
    if o.stage == stage:
        raise ConflictError(f"The opportunity is already in {stage}.")
    old = o.stage
    o.stage = stage
    _stage_change(session, principal, o, old, note)
    _audit(
        session, principal, o, "opportunity.stage_changed", {"stage": {"old": old, "new": stage}}
    )
    _flush(session)
    return o


def mark_won(
    session: Session, principal: Principal, opp_id: uuid.UUID, *, version: int, note: str | None
) -> Opportunity:
    o = _load_for_write(session, principal, opp_id)
    _check_version(o, version)
    _check_open(o)
    if o.amount is None:
        raise InvalidOpportunityError("Add the deal value before marking the opportunity as won.")
    old = o.stage
    o.stage = "closed_won"
    o.closed_at = datetime.now(UTC)
    _stage_change(session, principal, o, old, note)
    _audit(session, principal, o, "opportunity.won", {"stage": {"old": old, "new": o.stage}})
    _flush(session)
    return o


def mark_lost(
    session: Session, principal: Principal, opp_id: uuid.UUID, *, version: int, reason: str
) -> Opportunity:
    o = _load_for_write(session, principal, opp_id)
    _check_version(o, version)
    _check_open(o)
    old = o.stage
    o.stage = "closed_lost"
    o.closed_at = datetime.now(UTC)
    o.lost_reason = reason
    _stage_change(session, principal, o, old, reason)
    _audit(
        session,
        principal,
        o,
        "opportunity.lost",
        {"stage": {"old": old, "new": o.stage}, "reason": reason},
    )
    _flush(session)
    return o


def reopen(
    session: Session,
    principal: Principal,
    opp_id: uuid.UUID,
    *,
    version: int,
    stage: str,
    note: str | None,
) -> Opportunity:
    if not principal.has_permission(Permission.OPPORTUNITY_WRITE_ALL):
        raise ForbiddenError("Only managers and administrators can reopen a closed deal.")
    o = _load_for_write(session, principal, opp_id)
    _check_version(o, version)
    if o.stage not in CLOSED_STAGES:
        raise ConflictError("The opportunity is not closed.")
    old = o.stage
    o.stage = stage
    o.closed_at = None
    o.lost_reason = None
    _stage_change(session, principal, o, old, note)
    _audit(session, principal, o, "opportunity.reopened", {"stage": {"old": old, "new": stage}})
    _flush(session)
    return o


def stage_history(
    session: Session, principal: Principal, opp_id: uuid.UUID
) -> list[StageChangeRead]:
    o = get_opportunity(session, principal, opp_id)
    rows = repository.stage_changes(session, o)
    people = identity_api.people_by_id(
        session, o.tenant_id, {r.changed_by_user_id for r in rows if r.changed_by_user_id}
    )
    return [
        StageChangeRead(
            from_stage=r.from_stage,
            to_stage=r.to_stage,
            note=r.note,
            changed_at=r.changed_at,
            changed_by_name=people.get(r.changed_by_user_id, ("Former colleague", ""))[0]
            if r.changed_by_user_id
            else None,
        )
        for r in rows
    ]
