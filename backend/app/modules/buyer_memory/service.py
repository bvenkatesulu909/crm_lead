"""Buyer memory (ADR 0028): read, add, confirm, copy from the lead form, seed from the website chat.

Every function first checks that the person may read the lead (the leads module decides; anything
else is a 404, the same answer as for a lead that does not exist). Nothing here commits - the
router does, once. Audit entries name the key and the status, never the value.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.buyer_memory import repository, rules
from app.modules.buyer_memory.models import BuyerMemoryItem
from app.modules.buyer_memory.schemas import MemoryConfirm, MemoryItemCreate
from app.modules.leads import api as leads_api

# A lead holds at most this many rows; the history grows but not without bound.
MAX_ITEMS_PER_LEAD = 200


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # Same message whether the lead doesn't exist, belongs to another tenant or isn't yours.
        super().__init__("Lead not found.")


class ItemNotFoundError(NotFoundError):
    code = "memory_item_not_found"

    def __init__(self) -> None:
        super().__init__("That buyer memory item was not found.")


class MemoryInvalidError(DomainError):
    status_code = 422
    code = "memory_invalid"


class MemoryValueRefusedError(DomainError):
    status_code = 422
    code = "memory_value_refused"


class MemorySourceNotFoundError(DomainError):
    status_code = 422
    code = "memory_source_not_found"

    def __init__(self) -> None:
        super().__init__("That timeline entry does not belong to this lead.")


class MemoryFullError(ConflictError):
    code = "memory_full"

    def __init__(self) -> None:
        super().__init__("This lead's buyer memory is full.")


class NotAnAssumptionError(ConflictError):
    code = "memory_not_an_assumption"

    def __init__(self) -> None:
        super().__init__("Only an assumption can be confirmed.")


class NotCurrentError(ConflictError):
    code = "memory_not_current"

    def __init__(self) -> None:
        super().__init__("A newer entry exists for this key; confirm that one instead.")


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise LeadNotFoundError()
    return principal.tenant_id


def _require_lead(session: Session, principal: Principal, lead_id: uuid.UUID) -> uuid.UUID:
    tenant_id = _tenant(principal)
    if not leads_api.is_readable_lead(session, principal, lead_id):
        raise LeadNotFoundError()
    return tenant_id


def _checked(**fields: object) -> rules.NewItem:
    try:
        return rules.check_new_item(**fields)  # type: ignore[arg-type]
    except rules.MemoryRuleError as exc:
        if exc.refused:
            raise MemoryValueRefusedError(str(exc)) from None
        raise MemoryInvalidError(str(exc)) from None


def _store(
    session: Session,
    principal: Principal,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    item: rules.NewItem,
) -> BuyerMemoryItem:
    if repository.count_of_lead(session, tenant_id, lead_id) >= MAX_ITEMS_PER_LEAD:
        raise MemoryFullError()
    return repository.add(
        session,
        BuyerMemoryItem(
            tenant_id=tenant_id,
            lead_id=lead_id,
            recorded_by_user_id=principal.user_id,
            key=item.key,
            value=item.value,
            status=item.status,
            source=item.source,
            source_ref=item.source_ref,
            quote=item.quote,
            reason=item.reason,
        ),
    )


def _audit(
    session: Session, principal: Principal, lead_id: uuid.UUID, action: str, **changes: object
) -> None:
    record_audit(
        session,
        principal,
        action=action,
        entity_type="lead",
        entity_id=lead_id,
        changes={k: v for k, v in changes.items()},
    )


def view(session: Session, principal: Principal, lead_id: uuid.UUID) -> rules.Arranged:
    tenant_id = _require_lead(session, principal, lead_id)
    return rules.arrange(repository.rows_of_lead(session, tenant_id, lead_id))


def add_item(
    session: Session, principal: Principal, lead_id: uuid.UUID, data: MemoryItemCreate
) -> BuyerMemoryItem:
    tenant_id = _require_lead(session, principal, lead_id)
    item = _checked(
        key=data.key,
        value=data.value,
        status=data.status,
        source=data.source,
        source_ref=data.source_ref,
        quote=data.quote,
        reason=data.reason,
    )
    if item.source == "timeline_entry" and (
        item.source_ref is None
        or not leads_api.lead_activity_belongs(session, principal, lead_id, item.source_ref)
    ):
        raise MemorySourceNotFoundError()
    stored = _store(session, principal, tenant_id, lead_id, item)
    _audit(
        session, principal, lead_id, "buyer_memory.added",
        key=item.key, status=item.status, item_id=str(stored.id),
    )  # fmt: skip
    return stored


def confirm_item(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    item_id: uuid.UUID,
    data: MemoryConfirm,
) -> BuyerMemoryItem:
    tenant_id = _require_lead(session, principal, lead_id)
    old = repository.get_of_lead(session, tenant_id, lead_id, item_id)
    if old is None:
        raise ItemNotFoundError()
    if old.status != "assumption":
        raise NotAnAssumptionError()
    current = rules.arrange(repository.rows_of_lead(session, tenant_id, lead_id)).current
    if all(row.id != old.id for row in current):
        raise NotCurrentError()
    item = _checked(
        key=old.key,
        value=data.value if data.value is not None else old.value,
        status="fact",
        source=data.source,
        source_ref=data.source_ref,
        quote=data.quote,
        reason=None,
    )
    if item.source == "timeline_entry" and (
        item.source_ref is None
        or not leads_api.lead_activity_belongs(session, principal, lead_id, item.source_ref)
    ):
        raise MemorySourceNotFoundError()
    stored = _store(session, principal, tenant_id, lead_id, item)
    _audit(
        session, principal, lead_id, "buyer_memory.confirmed",
        key=item.key, item_id=str(stored.id), confirmed_item_id=str(old.id),
    )  # fmt: skip
    return stored


def _form_facts(fields: leads_api.BuyerFields) -> list[tuple[str, str | None]]:
    return [
        ("budget", rules.budget_text(fields.budget_min_inr, fields.budget_max_inr)),
        ("property_type", rules.property_type_text(fields.property_type)),
        ("location", fields.location),
    ]


def copy_from_lead(session: Session, principal: Principal, lead_id: uuid.UUID) -> int:
    """Copy the lead form's details in as facts - only for keys that have no answer yet."""
    tenant_id = _require_lead(session, principal, lead_id)
    fields = leads_api.buyer_fields(session, principal, lead_id)
    if fields is None:
        raise LeadNotFoundError()
    answered = {
        row.key
        for row in rules.arrange(repository.rows_of_lead(session, tenant_id, lead_id)).current
    }
    added: list[str] = []
    for key, text in _form_facts(fields):
        if text is None or key in answered:
            continue
        item = _checked(
            key=key, value=text, status="fact", source="lead_record", quote=f"Lead form: {text}"
        )
        _store(session, principal, tenant_id, lead_id, item)
        added.append(key)
    if added:
        _audit(session, principal, lead_id, "buyer_memory.copied", keys=added)
    return len(added)


def record_from_website_chat(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    property_type: str | None,
    budget_min_inr: int | None,
    budget_max_inr: int | None,
    location: str | None,
) -> int:
    """What the website visitor gave becomes facts, citing the conversation. Nothing else is
    written: no guess, and the chat's free notes are not turned into facts (ADR 0028, BM6)."""
    tenant_id = _require_lead(session, principal, lead_id)
    fields = leads_api.BuyerFields(property_type, budget_min_inr, budget_max_inr, location)
    added: list[str] = []
    for key, text in _form_facts(fields):
        if text is None:
            continue
        item = _checked(
            key=key,
            value=text,
            status="fact",
            source="website_chat",
            source_ref=conversation_id,
            quote=f"Told the website chat: {text}",
        )
        _store(session, principal, tenant_id, lead_id, item)
        added.append(key)
    if added:
        _audit(session, principal, lead_id, "buyer_memory.recorded_from_chat", keys=added)
    return len(added)
