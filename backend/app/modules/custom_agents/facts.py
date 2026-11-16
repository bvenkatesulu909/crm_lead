"""What a custom agent is shown about one record (ADR 0034, AB2b).

Everything is read through the other modules' ``api.py`` AS THE PERSON WHO STARTED THE RUN, so that
person's own record-level rules decide what exists: a record they may not read is simply "not
found". Only the read sets the agent's definition lists are shown; text typed by people goes
through the same cleaning as every other record text (ADR 0017).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import DomainError
from app.core.screening import clean_records
from app.modules.accounts import api as accounts_api
from app.modules.activities import api as activities_api
from app.modules.leads import api as leads_api
from app.modules.quotes import api as quotes_api
from app.modules.relationships import api as relationships_api
from app.modules.sales import api as sales_api

RECENT_ENTRIES = 5
MAX_TASKS = 10


@dataclass(frozen=True)
class RecordView:
    """The record as one run sees it."""

    shown: dict[str, Any]
    # The NAMES of the read sets that were shown (for the audit trail).
    sets_shown: list[str]
    # Whether any text looked like an instruction to an AI.
    suspicious: bool
    # What the plan needs and the model is not asked to choose.
    status: str | None
    owner_id: uuid.UUID | None


def _day(moment: datetime | None) -> str | None:
    return moment.date().isoformat() if moment else None


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def load(
    session: Session,
    principal: Principal,
    record_type: str,
    record_id: uuid.UUID,
    read_sets: list[str],
) -> RecordView | None:
    """The record, or None when it does not exist or this person may not read it."""
    if record_type == "lead":
        view = _lead(session, principal, record_id, read_sets)
    elif record_type == "account":
        view = _account(session, principal, record_id, read_sets)
    else:
        view = _deal(session, principal, record_id, read_sets)
    if view is None:
        return None
    cleaned, suspicious = clean_records(view.shown)
    return RecordView(cleaned, sorted(cleaned), suspicious, view.status, view.owner_id)


def _lead(
    session: Session, principal: Principal, lead_id: uuid.UUID, read_sets: list[str]
) -> RecordView | None:
    facts = leads_api.qualifier_facts(session, principal, lead_id)
    if facts is None:
        return None
    shown: dict[str, Any] = {}
    if "lead" in read_sets:
        shown["lead"] = {
            **facts.fields,
            "status": facts.status,
            "score_reasons": facts.score_reasons,
        }
    if "lead_activity" in read_sets:
        shown["lead_activity"] = {
            "timeline": [
                {
                    "kind": entry.kind,
                    "on": _day(entry.occurred_at),
                    "subject": entry.subject,
                    "body": entry.body,
                }
                for entry in leads_api.recent_timeline(session, principal, lead_id, RECENT_ENTRIES)
            ],
            "open_tasks": [
                {"subject": task.subject, "due": _day(task.due_at), "priority": task.priority}
                for task in activities_api.open_tasks_of_lead(
                    session, principal, lead_id, MAX_TASKS
                )
            ],
        }
    return RecordView(shown, [], False, facts.status, facts.owner_id)


def _account(
    session: Session, principal: Principal, account_id: uuid.UUID, read_sets: list[str]
) -> RecordView | None:
    try:
        brief = accounts_api.get_account_brief(session, principal, account_id)
    except DomainError:  # not found, or not an account this person may read
        return None
    shown: dict[str, Any] = {}
    if "account" in read_sets:
        shown["account"] = {key: value for key, value in brief.items() if key not in ("id", "link")}
    if "account_health" in read_sets:
        try:
            health = relationships_api.account_health(session, principal, account_id)
        except DomainError:
            health = None
        if health is not None:
            shown["account_health"] = {
                "score": health.score,
                "label": health.label,
                "last_interaction": _day(health.last_interaction_at),
                "days_inactive": health.days_inactive,
                "factors": [factor.label for factor in health.factors],
            }
    owner = accounts_api.account_owner_id(session, principal, account_id)
    return RecordView(shown, [], False, None, owner)


def _deal(
    session: Session, principal: Principal, deal_id: uuid.UUID, read_sets: list[str]
) -> RecordView | None:
    deal = sales_api.deal_facts(session, principal, deal_id)
    if deal is None:
        return None
    shown: dict[str, Any] = {}
    if "deal" in read_sets:
        shown["deal"] = {
            "name": deal.name,
            "stage": deal.stage,
            "open": deal.is_open,
            "amount": str(deal.amount) if deal.amount is not None else None,
            "currency": deal.currency,
            "expected_close_date": _iso(deal.expected_close_date),
            "next_step": deal.next_step,
            "in_stage_since": _day(deal.stage_entered_at),
            "other_open_deals_with_account": deal.other_open_deals,
        }
    if "deal_quotes" in read_sets:
        shown["deal_quotes"] = [
            {
                "label": quote.label,
                "status": quote.status,
                "currency": quote.currency,
                "total": str(quote.total),
                "max_discount_percent": str(quote.max_discount_percent),
                "valid_until": _iso(quote.valid_until),
            }
            for quote in quotes_api.deal_quotes(session, principal, deal.id)
        ]
    return RecordView(shown, [], False, None, deal.owner_id)
