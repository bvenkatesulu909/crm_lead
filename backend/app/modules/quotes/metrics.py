"""Quote figures for reports. Applies ``readable_quotes``."""

from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.reporting import Cell, Column, Filters, Table, percent
from app.modules.quotes.models import Quote
from app.modules.quotes.policies import readable_quotes


def _scope(principal: Principal, filters: Filters) -> ColumnElement[bool]:
    condition = readable_quotes(principal)
    if filters.owner_id is not None:
        condition = and_(condition, Quote.owner_id == filters.owner_id)
    return condition


def quote_table(session: Session, principal: Principal, filters: Filters) -> Table:
    """Per sales rep: quotes sent in the period, answers received, acceptance rate and the
    average largest discount of the quotes sent."""
    period = filters.period
    sent = and_(Quote.sent_at >= period.start, Quote.sent_at < period.end)
    decided = and_(Quote.decided_at >= period.start, Quote.decided_at < period.end)
    rows = session.execute(
        select(
            Quote.owner_id,
            func.count().filter(sent),
            func.count().filter(decided, Quote.status == "accepted"),
            func.count().filter(decided, Quote.status == "declined"),
            func.avg(Quote.max_discount_percent).filter(sent),
        )
        .where(_scope(principal, filters))
        .group_by(Quote.owner_id)
    ).all()
    out: list[dict[str, Cell]] = [
        {
            "owner_id": owner,
            "sent": n_sent,
            "accepted": accepted,
            "declined": declined,
            "acceptance_rate": percent(accepted, accepted + declined),
            "avg_discount": Decimal(str(discount)).quantize(Decimal("0.1"))
            if discount is not None
            else None,
        }
        for owner, n_sent, accepted, declined, discount in sorted(rows, key=lambda r: -int(r[1]))
        if n_sent or accepted or declined
    ]
    return Table(
        "Quotes",
        (
            Column("owner_id", "Sales rep", "user"),
            Column("sent", "Sent", "number"),
            Column("accepted", "Accepted", "number"),
            Column("declined", "Declined", "number"),
            Column("acceptance_rate", "Acceptance %", "percent"),
            Column("avg_discount", "Avg. largest discount %", "number"),
        ),
        out,
    )
