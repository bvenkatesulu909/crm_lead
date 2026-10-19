"""Invoice rules. Pure functions, unit-tested.

Life of an invoice:
    draft ──issue──► issued (gets its number; frozen from now on)
      └──discard──► discarded (never had a number; the order can be invoiced again)

What is still owed (balance_due) = total - payments received - credit notes.
The PAYMENT STATE shown to people is calculated, never stored:
    draft / discarded            - not a real invoice (yet)
    open                         - issued, nothing received, not yet due
    partially_paid               - something received or credited, the rest not yet due
    overdue                      - money still owed after the due date
    paid                         - nothing owed, and money was received
    credited                     - nothing owed, fully settled by credit notes
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from app.core.errors import ConflictError, DomainError

PaymentState = Literal[
    "draft", "discarded", "open", "partially_paid", "overdue", "paid", "credited"
]
# Orders in these statuses may be invoiced (not drafts, not cancelled).
INVOICEABLE_ORDER_STATUSES = frozenset({"confirmed", "in_fulfilment", "shipped", "delivered"})
DEFAULT_PAYMENT_TERMS_DAYS = 14
MAX_PAYMENT_TERMS_DAYS = 365


class InvalidAmountError(DomainError):
    status_code = 422
    code = "invalid_amount"


class InvoiceNotIssuedError(ConflictError):
    code = "invoice_not_issued"


def payment_state(
    *,
    status: str,
    total: Decimal,
    amount_paid: Decimal,
    amount_credited: Decimal,
    balance_due: Decimal,
    due_date: date | None,
    today: date,
) -> PaymentState:
    if status == "draft":
        return "draft"
    if status == "discarded":
        return "discarded"
    if balance_due == 0:
        return "paid" if amount_paid > 0 or total == 0 else "credited"
    if due_date is not None and due_date < today:
        return "overdue"
    if amount_paid > 0 or amount_credited > 0:
        return "partially_paid"
    return "open"


def check_payment_amount(amount: Decimal, balance_due: Decimal) -> None:
    """A payment may settle the balance but not exceed it (overpayments/refunds come later)."""
    if amount <= 0:
        raise InvalidAmountError("A payment must be more than 0.")
    if amount > balance_due:
        raise InvalidAmountError(
            f"The payment ({amount}) is more than the amount still owed ({balance_due})."
        )


def check_credit_amount(total: Decimal, balance_due: Decimal) -> None:
    """A credit note may reduce only what is still unpaid. To refund a paid invoice, reverse
    the payment first (and refund outside the CRM) - this keeps the balance never negative."""
    if total <= 0:
        raise InvalidAmountError("A credit note must be more than 0.")
    if total > balance_due:
        raise InvalidAmountError(
            f"The credit note ({total}) is more than the amount still owed ({balance_due})."
        )


def check_due_date(issue_date: date, due_date: date) -> None:
    days = (due_date - issue_date).days
    if days < 0:
        raise InvalidAmountError("The due date cannot be before the issue date.")
    if days > MAX_PAYMENT_TERMS_DAYS:
        raise InvalidAmountError(
            f"The due date can be at most {MAX_PAYMENT_TERMS_DAYS} days after the issue date."
        )


def check_received_on(received_on: date, today: date) -> None:
    if received_on > today:
        raise InvalidAmountError("A payment cannot be received in the future.")
