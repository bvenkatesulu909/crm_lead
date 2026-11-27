# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""The deal risk honesty check against the real database and the Reports API (ADR 0037, DR6).

Happy path, a forecast made AFTER closing ignored, deals outside the period left out, role denial,
record-level reading as the asker, tenant isolation, and the report's gate.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.deal_risk import api as deal_risk
from app.modules.deal_risk.models import DealRiskSnapshot
from app.modules.sales.models import Opportunity
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world

NOW = datetime.now(UTC)
START, END = NOW - timedelta(days=30), NOW + timedelta(days=1)


def as_manager(db_session: Session, world: World):  # noqa: ANN201
    principal = principal_for(world.users["alpha.manager"], ROLES["alpha.manager"])
    bind_principal(db_session, principal)
    return principal


def closed_deal(
    db_session: Session,
    world: World,
    *,
    won: bool,
    forecast: str | None,
    closed_days_ago: int = 2,
    expected_days_ago: int = -5,
    forecast_after_closing: bool = False,
) -> uuid.UUID:
    """A closed deal of alpha, optionally with a snapshot before (or after) it closed."""
    manager = as_manager(db_session, world)
    tenant = world.users["alpha.agent1"].tenant_id
    closed_at = NOW - timedelta(days=closed_days_ago)
    deal = Opportunity(
        tenant_id=tenant,
        name=f"Backtest {uuid.uuid4().hex[:6]}",
        account_id=world.ids["A1"],
        owner_id=world.users["alpha.agent1"].id,
        currency="INR",
        stage="closed_won" if won else "closed_lost",
        lost_reason=None if won else "price",
        closed_at=closed_at,
        expected_close_date=(NOW - timedelta(days=expected_days_ago)).date(),
        created_at=NOW - timedelta(days=60),
    )
    db_session.add(deal)
    db_session.flush()
    if forecast:
        at = closed_at + (timedelta(days=1) if forecast_after_closing else -timedelta(days=3))
        db_session.add(
            DealRiskSnapshot(
                tenant_id=tenant,
                opportunity_id=deal.id,
                level=forecast,
                score={"low": 10, "medium": 40, "high": 70}[forecast],
                rules_version=1,
                source="on_demand",
                requested_by_user_id=manager.user_id,
                factors=[],
                unknown=[],
                created_at=at,
            )
        )
        db_session.flush()
    return deal.id


def rows_of(summary) -> dict[str, tuple[int, int, int, int]]:  # noqa: ANN001
    return {r.level: (r.deals, r.won_on_time, r.won_late, r.lost) for r in summary.rows}


def test_closed_deals_are_grouped_by_their_last_forecast_before_closing(world, db_session) -> None:
    closed_deal(db_session, world, won=False, forecast="high")
    closed_deal(db_session, world, won=True, forecast="high", expected_days_ago=10)  # late
    closed_deal(db_session, world, won=True, forecast="low")
    closed_deal(db_session, world, won=True, forecast=None)
    manager = as_manager(db_session, world)
    rows = rows_of(deal_risk.backtest_summary(db_session, manager, START, END))
    assert rows["high"] == (2, 0, 1, 1)
    assert rows["low"] == (1, 1, 0, 0)
    assert rows["none"][0] >= 1


def test_a_forecast_made_after_the_deal_closed_does_not_count(world, db_session) -> None:
    closed_deal(db_session, world, won=False, forecast="high", forecast_after_closing=True)
    manager = as_manager(db_session, world)
    rows = rows_of(deal_risk.backtest_summary(db_session, manager, START, END))
    assert rows["high"][0] == 0


def test_deals_closed_outside_the_period_are_left_out(world, db_session) -> None:
    closed_deal(db_session, world, won=False, forecast="high", closed_days_ago=90)
    manager = as_manager(db_session, world)
    rows = rows_of(deal_risk.backtest_summary(db_session, manager, START, END))
    assert rows["high"][0] == 0


def test_another_organisation_sees_none_of_alphas_deals(world, db_session) -> None:
    closed_deal(db_session, world, won=False, forecast="high")
    beta = principal_for(world.users["beta.admin"], ROLES["beta.admin"])
    bind_principal(db_session, beta)
    rows = rows_of(deal_risk.backtest_summary(db_session, beta, START, END))
    assert rows["high"][0] == 0


def test_the_report_is_for_managers_and_administrators(api, auth, world) -> None:
    body = ok(api.get("/api/v1/reports/deal_risk", headers=auth("alpha.manager")))
    section = body["sections"][0]
    assert section["title"].startswith("Forecast vs. outcome - Too early to measure")
    labels = [row["level"] for row in section["rows"]]
    assert labels == ["High risk", "Medium risk", "Low risk", "No forecast before closing"]
    ok(api.get("/api/v1/reports/deal_risk", headers=auth("alpha.admin")))
    for who in ("alpha.agent1", "alpha.support"):
        assert code_of(api.get("/api/v1/reports/deal_risk", headers=auth(who)))[0] in (403, 404)
    catalogue = ok(api.get("/api/v1/reports", headers=auth("alpha.agent1")))
    assert "deal_risk" not in {r["key"] for r in catalogue["reports"]}
