"""What rules can be built from: triggers, the fields conditions may test, and actions.

A fixed catalogue on purpose (ADR 0006): tenants combine these pieces, but can't write code or
expressions, and can only change a short whitelist of fields.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.modules.accounts.api import ACCOUNT_SEGMENTS
from app.modules.activities.api import ACTIVITY_PRIORITIES
from app.modules.leads.api import LEAD_STATUSES
from app.modules.orders.api import ORDER_STATUSES
from app.modules.support.api import TICKET_CATEGORIES, TICKET_PRIORITIES

FieldType = Literal["choice", "text", "number"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: FieldType
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriggerSpec:
    key: str
    label: str
    kind: Literal["event", "schedule"]
    record_type: str
    days_label: str | None = None  # schedules: what "N days" means


@dataclass(frozen=True)
class FieldUpdateSpec:
    key: str
    label: str
    record_types: tuple[str, ...]  # triggers whose record allows this change
    options: tuple[str, ...] = field(default=())


QUOTE_STATUSES = ("sent", "accepted", "declined", "pending_approval", "approved")

RECORD_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "lead": (
        FieldSpec("status", "Lead status", "choice", LEAD_STATUSES),
        FieldSpec("source", "Lead source", "text"),
    ),
    "quote": (
        FieldSpec("total", "Quote total", "number"),
        FieldSpec("max_discount_percent", "Largest line discount (%)", "number"),
        FieldSpec("currency", "Currency", "text"),
        FieldSpec("status", "Quote status", "choice", QUOTE_STATUSES),
    ),
    "ticket": (
        FieldSpec("priority", "Ticket priority", "choice", TICKET_PRIORITIES),
        FieldSpec("category", "Ticket category", "choice", TICKET_CATEGORIES),
    ),
    "order": (
        FieldSpec("status", "Order status", "choice", ORDER_STATUSES),
        FieldSpec("total", "Order total", "number"),
        FieldSpec("currency", "Currency", "text"),
    ),
    "activity": (FieldSpec("priority", "Task priority", "choice", ACTIVITY_PRIORITIES),),
}

TRIGGERS: dict[str, TriggerSpec] = {
    t.key: t
    for t in (
        TriggerSpec("lead.assigned", "A lead is assigned to someone", "event", "lead"),
        TriggerSpec("quote.approval_requested", "A quote needs approval", "event", "quote"),
        TriggerSpec("quote.accepted", "A customer accepts a quote", "event", "quote"),
        TriggerSpec("quote.declined", "A customer declines a quote", "event", "quote"),
        TriggerSpec("ticket.assigned", "A ticket is assigned", "event", "ticket"),
        TriggerSpec("ticket.customer_replied", "A customer replies on a ticket", "event", "ticket"),
        TriggerSpec("order.status_changed", "An order changes status", "event", "order"),
        TriggerSpec(
            "schedule.quote_expiring",
            "A sent quote expires soon",
            "schedule",
            "quote",
            "Days before it expires",
        ),
        TriggerSpec(
            "schedule.task_overdue", "A task is overdue", "schedule", "activity", "Days overdue"
        ),
    )
}

# Which event data holds the record a trigger is about.
EVENT_RECORD_KEY = {
    "lead.assigned": "lead_id",
    "quote.approval_requested": "quote_id",
    "quote.accepted": "quote_id",
    "quote.declined": "quote_id",
    "ticket.assigned": "ticket_id",
    "ticket.customer_replied": "ticket_id",
    "order.status_changed": "order_id",
}

FIELD_UPDATES: dict[str, FieldUpdateSpec] = {
    "lead.status": FieldUpdateSpec(
        "lead.status",
        "Set the lead's status",
        ("lead",),
        tuple(s for s in LEAD_STATUSES if s != "converted"),  # converting needs a person
    ),
    "account.segment": FieldUpdateSpec(
        "account.segment",
        "Set the customer's segment",
        ("quote", "ticket", "order"),
        ACCOUNT_SEGMENTS,
    ),
}

ACTION_TYPES = ("create_task", "notify", "update_field")
ROLES = ("tenant_admin", "sales_manager", "sales_agent", "support_agent")
OPERATORS: dict[FieldType, tuple[str, ...]] = {
    "choice": ("eq", "neq", "in"),
    "text": ("eq", "neq"),
    "number": ("eq", "neq", "gt", "gte", "lt", "lte"),
}
MAX_CONDITIONS = 5
MAX_ACTIONS = 5
