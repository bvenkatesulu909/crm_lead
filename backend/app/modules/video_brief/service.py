"""The video brief (ADR 0041): gather what the CRM holds - through each module's own ``api.py``, as
the person asking - and arrange it with the pure rules. Nothing is written.

A lead the person may not read is a 404 (the same answer as for a lead that does not exist). Only
the buyer's FIRST name is used; the phone number, e-mail address and last name never leave this
service."""

import uuid

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import DomainError, NotFoundError
from app.modules.buyer_memory import api as memory_api
from app.modules.leads import api as leads_api
from app.modules.quotes import api as quotes_api
from app.modules.video_brief import rules


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # Same message whether the lead doesn't exist, belongs to another tenant or isn't yours.
        super().__init__("Lead not found.")


class QuoteNotFoundError(NotFoundError):
    code = "quote_not_found"

    def __init__(self) -> None:
        # Same answer whether the quote does not exist, is not readable, or is not this lead's.
        super().__init__("Quote not found.")


class QuoteNotReadyError(DomainError):
    status_code = 422
    code = "video_brief_quote_not_ready"


class BriefChoiceInvalidError(DomainError):
    status_code = 422
    code = "video_brief_choice_invalid"


def build(
    session: Session,
    principal: Principal,
    lead_id: uuid.UUID,
    *,
    goal: str,
    language: str | None,
    tone: str,
    length_seconds: int,
    quote_id: uuid.UUID | None = None,
) -> rules.VideoBrief:
    lead = leads_api.brief_facts(session, principal, lead_id)
    memory = memory_api.current_memory(session, principal, lead_id)
    if principal.tenant_id is None or lead is None or memory is None:
        raise LeadNotFoundError()

    chosen = language or lead.preferred_language or "en"
    # Statements come only from facts the buyer confirmed; assumptions become questions.
    facts = [
        rules.KnownFact(i.key, label, i.value, i.source, i.quote)
        for i in memory.current
        if i.status == "fact"
        for label in [dict(memory_api.KEYS)[i.key]]
    ]
    guesses = [
        rules.KnownGuess(i.key, dict(memory_api.KEYS)[i.key], i.value, i.reason)
        for i in memory.current
        if i.status == "assumption"
    ]
    # What the lead form says (the buyer has not confirmed it) - shown, never spoken.
    wishes = [
        (key, text)
        for key, text in (
            ("budget", memory_api.budget_text(lead.budget_min_inr, lead.budget_max_inr)),
            ("property_type", memory_api.property_type_text(lead.property_type)),
            ("location", lead.location),
        )
        if text
    ]
    price = _price(session, principal, lead.converted_account_id, quote_id)
    try:
        return rules.build_video_brief(
            first_name=lead.first_name or "",
            language=chosen,
            goal=goal,
            tone=tone,
            length_seconds=length_seconds,
            facts=facts,
            guesses=guesses,
            form_wishes=wishes,
            price=price,
        )
    except rules.BriefError as exc:
        raise BriefChoiceInvalidError(str(exc)) from None


def _price(
    session: Session,
    principal: Principal,
    lead_account_id: uuid.UUID | None,
    quote_id: uuid.UUID | None,
) -> rules.PriceFacts | None:
    """The prices of a quote, only if the person may read it AND it belongs to the account this lead
    became (a quote cannot belong to a lead any other way). Only approved, sent or accepted quotes:
    nobody stands by the price of a draft."""
    if quote_id is None:
        return None
    facts = quotes_api.price_facts(session, principal, quote_id)
    if facts is None or lead_account_id is None or facts.account_id != lead_account_id:
        raise QuoteNotFoundError()
    if facts.status not in quotes_api.PRICE_FACT_STATUSES:
        raise QuoteNotReadyError(
            "Only an approved, sent or accepted quote can be used in a video brief."
        )
    return rules.PriceFacts(
        label=facts.label,
        currency=facts.currency,
        valid_until=facts.valid_until,
        total=facts.total,
        lines=[
            rules.PriceLine(ln.description, ln.quantity, ln.unit, ln.net_unit_price, ln.line_total)
            for ln in facts.lines
        ],
    )
