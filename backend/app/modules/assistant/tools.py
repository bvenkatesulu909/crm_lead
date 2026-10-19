"""The assistant's tools: the ONLY way the model can see CRM data.

Every tool calls the same public functions the customer portal uses, AS the signed-in customer
(``principal``). Tenant isolation, portal grants and "no drafts / no internal notes" therefore
apply unchanged. The model never gets database access, IDs it could not already see, or a way
to change data: the only action, opening a support ticket, is a PROPOSAL the customer must
confirm in the portal (see service.confirm_action).

Model arguments are untrusted input: each tool validates them with a strict schema, and
anything not visible to the customer looks exactly like "not found".
"""

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import DomainError, NotFoundError
from app.modules.accounts import api as accounts_api
from app.modules.invoices import api as invoices_api
from app.modules.orders import api as orders_api
from app.modules.support import api as support_api

MAX_RESULT_CHARS = 6_000
Outcome = Literal["ok", "not_found", "invalid", "refused", "error"]


@dataclass(frozen=True)
class ToolResult:
    outcome: Outcome
    content: str  # JSON text handed to the model

    @property
    def is_error(self) -> bool:
        return self.outcome != "ok"


def _json(data: Any) -> str:
    text = json.dumps(data, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        # Keep the model's context small and predictable; ask for a narrower question instead.
        text = json.dumps({"truncated": True, "note": "Too much data; ask about one item."})
    return text


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


Number = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]


class NoArgs(_Args):
    pass


class OrderArgs(_Args):
    order_number: Number = Field(description="e.g. SO-0003 or 3")


class InvoiceArgs(_Args):
    invoice_number: Number = Field(description="e.g. INV-0002 or 2")


class InvoiceListArgs(_Args):
    state: Literal["unpaid", "overdue", "paid"] | None = None


class TicketArgs(_Args):
    ticket_number: Number = Field(description="e.g. T-0001 or 1")


class ProposeTicketArgs(_Args):
    account_id: uuid.UUID
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


def _number(value: str, prefix: str) -> int:
    match = re.fullmatch(rf"(?:{prefix}-)?0*(\d{{1,9}})", value.strip().upper())
    if not match:
        raise ValueError(f"expected a number like {prefix}-0001")
    return int(match.group(1))


def _fmt(prefix: str, number: int) -> str:
    return f"{prefix}-{number:04d}"


# --- the tools ----------------------------------------------------------------------------


def list_my_accounts(session: Session, principal: Principal, _: NoArgs) -> Any:
    accounts = accounts_api.list_portal_accounts(session, principal, limit=50, offset=0)
    return [{"account_id": a.id, "name": a.name, "status": a.status} for a in accounts]


def list_orders(session: Session, principal: Principal, _: NoArgs) -> Any:
    orders = orders_api.customer_orders(session, principal, limit=20)
    return [
        {
            "order": _fmt("SO", o.number),
            "status": o.status,
            "total": f"{o.total} {o.currency}",
            "your_reference": o.customer_reference,
            "expected_delivery": o.expected_delivery_date,
        }
        for o in orders
    ]


def get_order(session: Session, principal: Principal, args: OrderArgs) -> Any:
    number = _number(args.order_number, "SO")
    match = [
        o
        for o in orders_api.customer_orders(session, principal, q=_fmt("SO", number), limit=5)
        if o.number == number
    ]
    if not match:
        raise NotFoundError("No order with this number is visible to you.")
    order = orders_api.customer_order(session, principal, match[0].id)
    return {
        "order": _fmt("SO", order.number),
        "status": order.status,
        "your_reference": order.customer_reference,
        "total": f"{order.total} {order.currency}",
        "expected_delivery": order.expected_delivery_date,
        "tracking_reference": order.tracking_reference,
        "cancellation_reason": order.cancellation_reason,
        "timeline": [{"status": s.status, "at": s.at} for s in order.timeline],
        "lines": [
            {"item": line.description, "quantity": line.quantity, "amount": line.line_total}
            for line in order.lines
        ],
    }


def list_invoices(session: Session, principal: Principal, args: InvoiceListArgs) -> Any:
    invoices = invoices_api.customer_invoices(session, principal, state=args.state, limit=20)
    return [
        {
            "invoice": _fmt("INV", i.number),
            "state": i.payment_state,
            "total": f"{i.total} {i.currency}",
            "amount_due": f"{i.balance_due} {i.currency}",
            "due_date": i.due_date,
        }
        for i in invoices
    ]


def get_invoice(session: Session, principal: Principal, args: InvoiceArgs) -> Any:
    number = _number(args.invoice_number, "INV")
    match = [
        i
        for i in invoices_api.customer_invoices(session, principal, q=_fmt("INV", number), limit=5)
        if i.number == number
    ]
    if not match:
        raise NotFoundError("No invoice with this number is visible to you.")
    inv = invoices_api.customer_invoice(session, principal, match[0].id)
    return {
        "invoice": _fmt("INV", inv.number),
        "state": inv.payment_state,
        "issued": inv.issue_date,
        "due_date": inv.due_date,
        "total": f"{inv.total} {inv.currency}",
        "credited": f"{inv.amount_credited} {inv.currency}",
        "paid": f"{inv.amount_paid} {inv.currency}",
        "amount_due": f"{inv.balance_due} {inv.currency}",
        "payments": [{"amount": p.amount, "received_on": p.received_on} for p in inv.payments],
        "credit_notes": [
            {"credit_note": _fmt("CN", n.number), "total": n.total, "reason": n.reason}
            for n in inv.credit_notes
        ],
    }


def list_tickets(session: Session, principal: Principal, _: NoArgs) -> Any:
    tickets = support_api.customer_tickets(session, principal, limit=20)
    return [
        {
            "ticket": _fmt("T", t.number),
            "subject": t.subject,
            "status": t.status,
            "opened": t.created_at,
            "last_update": t.updated_at,
        }
        for t in tickets
    ]


def get_ticket(session: Session, principal: Principal, args: TicketArgs) -> Any:
    number = _number(args.ticket_number, "T")
    tickets = support_api.customer_tickets(session, principal, q=_fmt("T", number), limit=5)
    match = [t for t in tickets if t.number == number]
    if not match:
        raise NotFoundError("No ticket with this number is visible to you.")
    t = match[0]
    return {
        "ticket": _fmt("T", t.number),
        "subject": t.subject,
        "status": t.status,
        "description": t.description,
        "opened": t.created_at,
        "last_update": t.updated_at,
    }


ProposeHandler = Callable[[ProposeTicketArgs], None]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    run: Callable[[Session, Principal, Any], Any] | None  # None: handled by the service


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "list_my_accounts",
            "The customer accounts (companies) this customer may see, with account_id.",
            NoArgs,
            list_my_accounts,
        ),
        Tool("list_orders", "The customer's most recent orders.", NoArgs, list_orders),
        Tool(
            "get_order",
            "Status, lines, tracking and delivery of ONE order by its number.",
            OrderArgs,
            get_order,
        ),
        Tool(
            "list_invoices",
            "The customer's invoices; optionally only unpaid, overdue or paid ones.",
            InvoiceListArgs,
            list_invoices,
        ),
        Tool(
            "get_invoice",
            "Amount due, payments received and credit notes of ONE invoice by its number.",
            InvoiceArgs,
            get_invoice,
        ),
        Tool("list_tickets", "The customer's support tickets.", NoArgs, list_tickets),
        Tool("get_ticket", "One support ticket by its number.", TicketArgs, get_ticket),
        Tool(
            "propose_support_ticket",
            "PROPOSE handing the conversation over to a human: prepares a support ticket that "
            "the customer must confirm on screen. Nothing is created until they confirm. Use "
            "when you cannot help, for refunds, complaints, changes to orders or anything "
            "that needs a person. account_id must come from list_my_accounts.",
            ProposeTicketArgs,
            None,
        ),
    ]
}


def definitions() -> list[dict[str, Any]]:
    """Tool descriptions in the format the Messages API expects."""
    defs = []
    for tool in TOOLS.values():
        schema = tool.args.model_json_schema()
        schema.pop("title", None)
        schema["additionalProperties"] = False
        schema.setdefault("properties", {})
        defs.append({"name": tool.name, "description": tool.description, "input_schema": schema})
    return defs


def execute(
    session: Session,
    principal: Principal,
    name: str,
    raw_args: dict[str, Any],
    propose: ProposeHandler,
) -> ToolResult:
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult("refused", _json({"error": f"Unknown tool {name!r}."}))
    try:
        args = tool.args.model_validate(raw_args)
    except ValidationError:
        return ToolResult("invalid", _json({"error": "Invalid arguments for this tool."}))
    try:
        if tool.run is None:
            proposal = args if isinstance(args, ProposeTicketArgs) else None
            if proposal is None:  # pragma: no cover - only one service-handled tool
                return ToolResult("error", _json({"error": "Not available."}))
            if not accounts_api.is_readable_account(session, principal, proposal.account_id):
                raise NotFoundError("Account not found.")
            propose(proposal)
            return ToolResult(
                "ok",
                _json(
                    {
                        "status": "awaiting_customer_confirmation",
                        "note": "Tell the customer to review and confirm the ticket shown "
                        "below your answer. Do not say it has been created.",
                    }
                ),
            )
        return ToolResult("ok", _json(tool.run(session, principal, args)))
    except ValueError as exc:
        return ToolResult("invalid", _json({"error": str(exc)}))
    except NotFoundError:
        return ToolResult("not_found", _json({"error": "Not found or not visible to you."}))
    except DomainError:
        return ToolResult("refused", _json({"error": "Not allowed."}))
