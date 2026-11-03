"""AI cost per month for the pilot report (docs/pilot-report.md, step PR2b).

An estimate: the month's tokens recorded for the chosen agents, times the prices the environment
sets. ``agent_usage`` is stored per whole calendar month, so nothing finer can be said honestly.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.config import Settings
from app.modules.agents.catalogue import AGENTS
from app.modules.agents.cost import estimate_cost_usd
from app.modules.agents.models import AgentUsage


def estimated_cost_by_month(
    session: Session,
    principal: Principal,
    months: Sequence[date],
    agent_keys: Sequence[str],
    settings: Settings,
) -> dict[date, Decimal | None]:
    """Estimated dollars for these agents in each month (first days of months). ``None`` when no
    price is set, so "unknown" is never shown as "free". Only the person's own organisation."""
    if not months:
        return {}
    prices = {
        "input_price_per_million": settings.ai_input_price_per_million,
        "output_price_per_million": settings.ai_output_price_per_million,
    }
    if estimate_cost_usd(0, 0, uses_model=True, **prices) is None:
        return {m: None for m in months}  # no price set: unknown, not free
    rows = session.execute(
        select(
            AgentUsage.month,
            AgentUsage.agent_key,
            AgentUsage.input_tokens,
            AgentUsage.output_tokens,
        ).where(
            AgentUsage.tenant_id == principal.tenant_id,
            AgentUsage.agent_key.in_(agent_keys),
            AgentUsage.month.in_(months),
        )
    ).all()
    costs: dict[date, Decimal | None] = {m: Decimal("0.0000") for m in months}
    for month, key, tokens_in, tokens_out in rows:
        cost = estimate_cost_usd(tokens_in, tokens_out, uses_model=AGENTS[key].uses_model, **prices)
        costs[month] = (costs[month] or Decimal("0")) + (cost or Decimal("0"))
    return costs
