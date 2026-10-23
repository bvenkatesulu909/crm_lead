"""Contract business rules. Functions here never commit: the router commits once.

- A contract starts as a draft. Activating, terminating and renewing are manager actions
  (``contract:manage``); sales agents create and edit contracts on their own accounts.
- An active contract keeps its account, dates and value: those change by RENEWING it, which
  creates a new draft linked to the old contract. The old one becomes "renewed" when the new
  one is activated.
- Every status change and note goes to contract_events (insert-only) and to the audit log in
  the same transaction. Activating and terminating also publish a domain event (ADR 0006).
- Accounts, contacts, deals and quotes are never trusted from the client: each one is loaded
  through its own module's policy and must belong to the contract's account.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.core.events import publish as publish_event
from app.modules.accounts import api as accounts_api
from app.modules.contacts import api as contacts_api
from app.modules.contracts import repository, rules
from app.modules.contracts.models import Contract, ContractEvent
from app.modules.contracts.repository import ContractFilters
from app.modules.contracts.schemas import (
    ContractCreate,
    ContractEventRead,
    ContractRead,
    ContractSummary,
    ContractUpdate,
    RenewInput,
)
from app.modules.identity import api as identity_api
from app.modules.quotes import api as quotes_api
from app.modules.sales import api as sales_api

ENTITY = "contract"
# Status changes other modules may react to (domain events, ADR 0006).
CONTRACT_EVENTS = {
    ("draft", "active"): "contract.activated",
    ("active", "terminated"): "contract.terminated",
}


class ContractNotFoundError(NotFoundError):
    code = "contract_not_found"

    def __init__(self) -> None:
        super().__init__("Contract not found.")


class RelatedNotFoundError(NotFoundError):
    code = "related_not_found"


class InvalidContractError(DomainError):
    status_code = 422
    code = "invalid_contract"


class VersionConflictError(ConflictError):
    code = "version_conflict"


def _today() -> date:
    return datetime.now(UTC).date()


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise ForbiddenError("Only members of an organisation can work with contracts.")
    return principal.tenant_id


def _flush(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as exc:
        raise VersionConflictError("The contract was changed by someone else. Reload it.") from exc


def _add_event(
    session: Session,
    principal: Principal,
    contract: Contract,
    event_type: str,
    *,
    old: str | None = None,
    new: str | None = None,
    note: str | None = None,
) -> None:
    session.add(
        ContractEvent(
            id=uuid.uuid4(),
            tenant_id=contract.tenant_id,
            contract_id=contract.id,
            event_type=event_type,
            from_status=old,
            to_status=new,
            actor_user_id=principal.user_id,
            note=note,
        )
    )


def _audit(
    session: Session, principal: Principal, contract: Contract, action: str, changes: dict[str, Any]
) -> None:
    record_audit(
        session,
        principal,
        action=f"contract.{action}",
        entity_type=ENTITY,
        entity_id=contract.id,
        changes=changes,
    )


def _move(
    session: Session, principal: Principal, contract: Contract, target: str, note: str | None
) -> None:
    rules.check_transition(contract.status, target)
    old = contract.status
    contract.status = target
    _add_event(session, principal, contract, "status_changed", old=old, new=target, note=note)
    _audit(
        session, principal, contract, target, {"status": {"old": old, "new": target}, "note": note}
    )
    name = CONTRACT_EVENTS.get((old, target))
    if name:
        publish_event(
            session,
            contract.tenant_id,
            name,
            {
                "contract_id": str(contract.id),
                "actor_id": str(principal.user_id) if principal.user_id else None,
            },
        )


# --- checks on what the client sends ------------------------------------------------------


def _may_contract_for(session: Session, principal: Principal, account_id: uuid.UUID) -> bool:
    if principal.has_permission(Permission.CONTRACT_WRITE_ALL):
        return accounts_api.is_readable_account(session, principal, account_id)
    return accounts_api.is_owned_account(session, principal, account_id)


def _check_owner(session: Session, principal: Principal, owner_id: uuid.UUID) -> None:
    if owner_id != principal.user_id and not principal.has_permission(
        Permission.CONTRACT_WRITE_ALL
    ):
        raise ForbiddenError("You may not give contracts to other people.")
    if not identity_api.is_assignable_sales_user(session, _tenant(principal), owner_id):
        raise InvalidContractError(
            "The owner must be an active sales employee of your organisation."
        )


def _check_links(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    opportunity_id: uuid.UUID | None,
    quote_id: uuid.UUID | None,
) -> None:
    """Each linked record must be visible to this user AND belong to the contract's account."""
    if contact_id is not None:
        visible, account = contacts_api.contact_account_id(session, principal, contact_id)
        if not visible:
            raise RelatedNotFoundError("Contact not found.")
        if account != account_id:
            raise InvalidContractError("The contact works at another account.")
    if opportunity_id is not None:
        visible, account = sales_api.opportunity_account_id(session, principal, opportunity_id)
        if not visible:
            raise RelatedNotFoundError("Opportunity not found.")
        if account != account_id:
            raise InvalidContractError("The opportunity belongs to another account.")
    if quote_id is not None:
        visible, account = quotes_api.quote_account_id(session, principal, quote_id)
        if not visible:
            raise RelatedNotFoundError("Quote not found.")
        if account != account_id:
            raise InvalidContractError("The quote belongs to another account.")


def _check_dates(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise InvalidContractError("The end date cannot be before the start date.")


def _require_manage(principal: Principal) -> None:
    if not principal.has_permission(Permission.CONTRACT_MANAGE):
        raise ForbiddenError("Only managers and administrators can do this.")


# --- create and change --------------------------------------------------------------------


def create_contract(session: Session, principal: Principal, data: ContractCreate) -> Contract:
    tenant_id = _tenant(principal)
    if principal.user_type != "staff" or not (
        principal.has_permission(Permission.CONTRACT_WRITE_ALL)
        or principal.has_permission(Permission.CONTRACT_WRITE_OWN)
    ):
        raise ForbiddenError("You may not create contracts.")
    if not _may_contract_for(session, principal, data.account_id):
        raise RelatedNotFoundError("Account not found.")
    _check_links(
        session, principal, data.account_id, data.contact_id, data.opportunity_id, data.quote_id
    )
    if data.owner_id is not None:
        _check_owner(session, principal, data.owner_id)
    contract = Contract(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        number=repository.next_contract_number(session, tenant_id),
        title=data.title,
        status="draft",
        account_id=data.account_id,
        contact_id=data.contact_id,
        opportunity_id=data.opportunity_id,
        quote_id=data.quote_id,
        owner_id=data.owner_id or principal.user_id,
        created_by_user_id=principal.user_id,
        start_date=data.start_date,
        end_date=data.end_date,
        auto_renew=data.auto_renew,
        renewal_notice_days=data.renewal_notice_days,
        renewal_term_months=data.renewal_term_months,
        currency=data.currency,
        total_value=data.total_value,
        billing_frequency=data.billing_frequency,
        terms=data.terms,
    )
    session.add(contract)
    _add_event(session, principal, contract, "created", new="draft")
    _audit(session, principal, contract, "created", {"number": contract.number})
    _flush(session)
    return contract


def _load_for_change(session: Session, principal: Principal, contract_id: uuid.UUID) -> Contract:
    contract = repository.get_writable(session, principal, contract_id)
    if contract is None:
        if repository.get_readable(session, principal, contract_id) is not None:
            raise ForbiddenError("You may view this contract but not change it.")
        raise ContractNotFoundError()
    return contract


def _check_version(contract: Contract, version: int) -> None:
    if contract.version != version:
        raise VersionConflictError(
            f"The contract was changed by someone else (now version {contract.version}). Reload it."
        )


def update_contract(
    session: Session, principal: Principal, contract_id: uuid.UUID, data: ContractUpdate
) -> Contract:
    contract = _load_for_change(session, principal, contract_id)
    _check_version(contract, data.version)
    fields = data.model_fields_set - {"version"}
    if contract.status == "active":
        locked = fields - rules.EDITABLE_WHEN_ACTIVE
        if locked:
            raise rules.ContractStateError(
                "An active contract keeps its account, dates and value; renew it to change "
                f"them (not allowed here: {', '.join(sorted(locked))})."
            )
    elif contract.status != "draft":
        raise rules.ContractStateError("Only draft and active contracts can be changed.")

    contact = data.contact_id if "contact_id" in fields else contract.contact_id
    opportunity = data.opportunity_id if "opportunity_id" in fields else contract.opportunity_id
    _check_links(session, principal, contract.account_id, contact, opportunity, None)
    if "owner_id" in fields and data.owner_id != contract.owner_id:
        if not principal.has_permission(Permission.CONTRACT_WRITE_ALL):
            raise ForbiddenError("Only managers and administrators can change the owner.")
        if data.owner_id is not None:
            _check_owner(session, principal, data.owner_id)
    start = data.start_date if "start_date" in fields else contract.start_date
    end = data.end_date if "end_date" in fields else contract.end_date
    _check_dates(start, end)

    for field in fields:
        setattr(contract, field, getattr(data, field))
    if fields & rules.RENEWAL_DATE_FIELDS:
        contract.renewal_reminded_at = None  # the renewal date moved: remind again when due
    _audit(session, principal, contract, "updated", {"fields": sorted(fields)})
    _flush(session)
    return contract


# --- status steps -------------------------------------------------------------------------


def activate(
    session: Session,
    principal: Principal,
    contract_id: uuid.UUID,
    *,
    version: int,
    note: str | None,
) -> Contract:
    _require_manage(principal)
    contract = _load_for_change(session, principal, contract_id)
    _check_version(contract, version)
    rules.check_transition(contract.status, "active")
    if contract.start_date is None or contract.end_date is None:
        raise InvalidContractError("Set the start and end date before activating.")
    if contract.end_date < _today():
        raise InvalidContractError("The end date is already in the past.")
    _move(session, principal, contract, "active", note)
    if contract.renewed_from_id is not None:
        previous = repository.get_in_tenant(session, contract.tenant_id, contract.renewed_from_id)
        if previous is not None and previous.status in rules.RENEWABLE:
            _move(
                session,
                principal,
                previous,
                "renewed",
                f"Renewed by {rules.label(contract.number)}",
            )
    _flush(session)
    return contract


def terminate(
    session: Session,
    principal: Principal,
    contract_id: uuid.UUID,
    *,
    version: int,
    reason: str,
) -> Contract:
    _require_manage(principal)
    contract = _load_for_change(session, principal, contract_id)
    _check_version(contract, version)
    rules.check_transition(contract.status, "terminated")
    contract.terminated_at = datetime.now(UTC)
    contract.termination_reason = reason
    _move(session, principal, contract, "terminated", reason)
    _flush(session)
    return contract


def renew(
    session: Session, principal: Principal, contract_id: uuid.UUID, data: RenewInput
) -> Contract:
    """Create the renewal as a new draft; activate it later to replace the old contract."""
    _require_manage(principal)
    old = _load_for_change(session, principal, contract_id)
    _check_version(old, data.version)
    if old.status not in rules.RENEWABLE:
        raise rules.ContractStateError("Only active or expired contracts can be renewed.")
    existing = repository.renewal_of(session, old)
    if existing is not None:
        raise rules.ContractStateError(
            f"{rules.label(existing.number)} already renews this contract."
        )
    if old.start_date is None or old.end_date is None:  # cannot happen (database rule); be safe
        raise InvalidContractError("The contract has no dates to renew from.")

    start = data.start_date or rules.renewal_defaults(old.start_date, old.end_date, None)[0]
    end = data.end_date or rules.renewal_end(
        start, old.renewal_term_months, (old.end_date - old.start_date).days
    )
    _check_dates(start, end)
    renewal = Contract(
        id=uuid.uuid4(),
        tenant_id=old.tenant_id,
        number=repository.next_contract_number(session, old.tenant_id),
        title=old.title,
        status="draft",
        account_id=old.account_id,
        contact_id=old.contact_id,
        opportunity_id=old.opportunity_id,
        quote_id=None,
        owner_id=old.owner_id,
        created_by_user_id=principal.user_id,
        renewed_from_id=old.id,
        start_date=start,
        end_date=end,
        auto_renew=old.auto_renew,
        renewal_notice_days=old.renewal_notice_days,
        renewal_term_months=old.renewal_term_months,
        currency=old.currency,
        total_value=data.total_value if data.total_value is not None else old.total_value,
        billing_frequency=old.billing_frequency,
        terms=old.terms,
    )
    session.add(renewal)
    _add_event(
        session,
        principal,
        renewal,
        "created",
        new="draft",
        note=data.note or f"Renewal of {rules.label(old.number)}",
    )
    _add_event(
        session,
        principal,
        old,
        "note",
        note=f"Renewal {rules.label(renewal.number)} created",
    )
    _audit(
        session,
        principal,
        renewal,
        "renewal_created",
        {"renews": str(old.id), "number": renewal.number},
    )
    _flush(session)
    return renewal


def add_note(session: Session, principal: Principal, contract_id: uuid.UUID, note: str) -> Contract:
    contract = _load_for_change(session, principal, contract_id)
    _add_event(session, principal, contract, "note", note=note)
    _audit(session, principal, contract, "note_added", {})
    _flush(session)
    return contract


# --- reading ------------------------------------------------------------------------------


def get_contract(session: Session, principal: Principal, contract_id: uuid.UUID) -> Contract:
    contract = repository.get_readable(session, principal, contract_id)
    if contract is None:
        raise ContractNotFoundError()
    return contract


def list_contracts(
    session: Session, principal: Principal, filters: ContractFilters
) -> tuple[Sequence[Contract], int]:
    return repository.search(session, principal, filters)


def _values(
    contract: Contract, accounts: dict[uuid.UUID, str], people: dict[uuid.UUID, tuple[str, str]]
) -> dict[str, Any]:
    end = contract.end_date
    return {
        **{c.key: getattr(contract, c.key) for c in Contract.__table__.columns},
        "label": rules.label(contract.number),
        "account_name": accounts.get(contract.account_id),
        "owner_name": people[contract.owner_id][0] if contract.owner_id in people else None,
        "renewal_date": rules.renewal_date(end, contract.renewal_notice_days) if end else None,
        "days_to_end": (end - _today()).days if end else None,
    }


def summaries(
    session: Session, tenant_id: uuid.UUID, contracts: Sequence[Contract]
) -> list[ContractSummary]:
    accounts = accounts_api.account_names(session, tenant_id, {c.account_id for c in contracts})
    people = identity_api.people_by_id(session, tenant_id, {c.owner_id for c in contracts})
    return [ContractSummary.model_validate(_values(c, accounts, people)) for c in contracts]


def to_read(session: Session, contract: Contract) -> ContractRead:
    accounts = accounts_api.account_names(session, contract.tenant_id, {contract.account_id})
    people = identity_api.people_by_id(session, contract.tenant_id, {contract.owner_id})
    renewal = repository.renewal_of(session, contract)
    return ContractRead.model_validate(
        {**_values(contract, accounts, people), "renewed_to_id": renewal.id if renewal else None}
    )


def history(
    session: Session, principal: Principal, contract_id: uuid.UUID
) -> list[ContractEventRead]:
    contract = get_contract(session, principal, contract_id)
    events = repository.events_of(session, contract)
    people = identity_api.people_by_id(
        session, contract.tenant_id, {e.actor_user_id for e in events if e.actor_user_id}
    )
    return [
        ContractEventRead(
            event_type=e.event_type,
            from_status=e.from_status,
            to_status=e.to_status,
            note=e.note,
            created_at=e.created_at,
            actor_name=(
                people.get(e.actor_user_id, ("Former user", ""))[0] if e.actor_user_id else None
            ),
        )
        for e in events
    ]
