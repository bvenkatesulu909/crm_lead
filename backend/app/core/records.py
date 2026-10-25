"""A neutral description of "a record" for features that work across modules (ADR 0006).

Workflow rules need to read a few facts about a lead, quote, ticket, order or task without
knowing those modules' tables. Each module fills this in through its api.py - and only for a
principal who may see the record.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RecordFacts:
    record_type: str  # "lead", "quote", "ticket", "order", "activity"
    record_id: uuid.UUID
    label: str  # short human text, e.g. "QT-0007: 50 widgets"
    link: str  # page inside the CRM, e.g. /quotes/<id>
    owner_id: uuid.UUID | None  # who is responsible (lead/quote owner, ticket/task assignee)
    account_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    # Values rules may test: text codes (status, priority, …) or numbers (totals, discounts).
    values: Mapping[str, str | Decimal]


@dataclass(frozen=True)
class Recipient:
    """A person the Communication Center may write to (ADR 0012): a lead or a contact.

    Filled in by the leads or contacts module, only for a principal who may read the record, so
    the address always comes from the record and never from the client."""

    first_name: str | None
    full_name: str
    email: str | None
    company: str | None  # a lead's company; for a contact, the name of ``account_id``
    account_id: uuid.UUID | None  # a contact's account; None for a lead
    consent_withdrawn: bool  # the contact said "no more e-mail"; leads have no consent field
