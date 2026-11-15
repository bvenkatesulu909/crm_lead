"""The rep's brief before a site visit (ADR 0029): gather what the CRM holds - through each module's
own ``api.py``, as the person asking - and arrange it with the pure rules. Nothing is written.

A lead the person may not read is a 404 (the same answer as for a lead that does not exist)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import DomainError, NotFoundError
from app.modules.activities import api as activities_api
from app.modules.buyer_memory import api as memory_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api
from app.modules.site_brief import rules

# More open follow-ups than this are not useful in a car.
MAX_TASKS = 10


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # Same message whether the lead doesn't exist, belongs to another tenant or isn't yours.
        super().__init__("Lead not found.")


class PlaceInvalidError(DomainError):
    status_code = 422
    code = "brief_place_invalid"


def build(
    session: Session, principal: Principal, lead_id: uuid.UUID, place: str | None
) -> rules.Brief:
    try:
        clean_place = rules.clean_place(place)
    except rules.PlaceError as exc:
        raise PlaceInvalidError(str(exc)) from None
    tenant_id = principal.tenant_id
    lead = leads_api.brief_facts(session, principal, lead_id)
    memory = memory_api.current_memory(session, principal, lead_id)
    if tenant_id is None or lead is None or memory is None:
        raise LeadNotFoundError()

    owner = None
    if lead.owner_id is not None:
        people = identity_api.people_by_id(session, tenant_id, {lead.owner_id})
        owner = people.get(lead.owner_id, (None, ""))[0]
    # The same wording as buyer memory's "copy from the lead form".
    form_budget = memory_api.budget_text(lead.budget_min_inr, lead.budget_max_inr)
    form_type = memory_api.property_type_text(lead.property_type)
    form_location = lead.location
    buyer = rules.BuyerFacts(
        name=" ".join(p for p in (lead.first_name, lead.last_name) if p),
        status=lead.status,
        source=lead.source,
        owner_name=owner,
        phone=lead.phone,
        email=lead.email,
        language=lead.preferred_language,
        form_budget=form_budget,
        form_property_type=form_type,
        form_location=form_location,
    )
    labels = dict(memory_api.KEYS)
    facts = [
        rules.KnownFact(i.key, labels[i.key], i.value, i.source, i.quote, i.created_at)
        for i in memory.current
        if i.status == "fact"
    ]
    guesses = [
        rules.KnownGuess(i.key, labels[i.key], i.value, i.reason, i.created_at)
        for i in memory.current
        if i.status == "assumption"
    ]
    recent = [
        rules.TimelineEntry(e.kind, e.occurred_at, e.subject, rules.excerpt(e.body))
        for e in leads_api.recent_timeline(session, principal, lead_id, rules.RECENT_ENTRIES)
    ]
    tasks = [
        rules.OpenTask(t.subject, t.due_at, t.priority)
        for t in activities_api.open_tasks_of_lead(session, principal, lead_id, MAX_TASKS)
    ]
    return rules.build_brief(
        buyer=buyer,
        facts=facts,
        guesses=guesses,
        recent=recent,
        tasks=tasks,
        place=clean_place,
        now=datetime.now(UTC),
        keys=list(memory_api.KEYS),
    )
