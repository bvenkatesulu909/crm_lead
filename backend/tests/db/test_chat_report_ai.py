# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The "Website chat" report, second half (docs/pilot-report.md, step PR2b).

Two more sections: what people did with the Qualifier's suggestions (approvals) and the AI cost of
the chat and the Qualifier per web lead (agents + leads, whole months, an estimate).
Aggregates only.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.agents import api as agents_api
from app.modules.approvals.models import AgentAction
from tests.db.test_chat_report import (
    INSIDE,
    PARAMS,
    URL,
    alpha,
    beta,
    report,
    web_lead,
)
from tests.db.test_quotes_api import World, api, auth, code_of, world  # noqa: F401

SUGGESTIONS = 2
COST = 3
NOVEMBER = datetime(2026, 11, 5, tzinfo=UTC)
WHY = "Secret reason text that must never be in a report"


def proposal(
    db: Session,
    world: World,
    *,
    status: str = "pending",
    agent: str = "qualifier",
    created: datetime = INSIDE,
    minutes: int = 5,
    tenant: uuid.UUID | None = None,
) -> AgentAction:
    tenant_id = tenant or alpha(world)
    asker = world.users["alpha.agent1" if tenant is None else "beta.agent"].id
    manager = world.users["alpha.manager" if tenant is None else "beta.admin"].id
    bind_tenant(db, tenant_id)
    by_person = status in ("approved", "rejected")
    row = AgentAction(
        tenant_id=tenant_id,
        kind="lead.set_status",
        target_type="lead",
        target_id=uuid.uuid4(),
        payload={"status": "qualified"},
        reason=WHY,
        agent=agent,
        via_client="crm-mcp" if agent == "mcp_client" else None,
        requested_by_user_id=asker,
        status=status,
        expires_at=created + timedelta(days=7),
        decided_by_user_id=manager if by_person else None,
        # The database says: decided_at is set exactly when the proposal is no longer pending.
        decided_at=None if status == "pending" else created + timedelta(minutes=minutes),
        created_at=created,
    )
    db.add(row)
    db.flush()
    return row


def use(
    db: Session,
    world: World,
    key: str,
    tokens_in: int,
    tokens_out: int,
    *,
    when: datetime = NOVEMBER,
    tenant: uuid.UUID | None = None,
) -> None:
    tenant_id = tenant or alpha(world)
    bind_tenant(db, tenant_id)
    agents_api.record_usage(
        db,
        tenant_id,
        key,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        limits=agents_api.Limits.default(),
        now=when,
    )
    db.flush()


def priced(api, input_price: float = 3.0, output_price: float = 15.0) -> None:
    api.app.state.settings = api.app.state.settings.model_copy(
        update={
            "ai_input_price_per_million": input_price,
            "ai_output_price_per_million": output_price,
        }
    )


def row_of(body: dict[str, Any], index: int) -> dict[str, Any]:
    row: dict[str, Any] = body["sections"][index]["rows"][0]
    return row


# --- who gets the sections ------------------------------------------------------------------------


def test_managers_and_administrators_get_four_sections(api, auth, world) -> None:
    for who in ("alpha.manager", "alpha.admin"):
        assert len(report(api, auth, who)["sections"]) == 4


def test_the_other_roles_still_get_no_report(api, auth, world) -> None:
    assert code_of(api.get(URL, params=PARAMS, headers=auth("alpha.agent1")))[0] == 404
    assert api.get(URL, params=PARAMS, headers=auth("alpha.customer")).status_code == 403


# --- the Qualifier's suggestions ------------------------------------------------------------------


def test_suggestions_are_counted_by_what_happened_to_them(api, auth, world, db_session) -> None:
    proposal(db_session, world, status="approved", minutes=10)
    proposal(db_session, world, status="approved", minutes=30)
    proposal(db_session, world, status="rejected", minutes=20)
    proposal(db_session, world, status="expired")
    proposal(db_session, world, status="failed")
    proposal(db_session, world, status="pending")
    row = row_of(report(api, auth), SUGGESTIONS)
    assert (row["proposed"], row["approved"], row["rejected"]) == (6, 2, 1)
    assert (row["expired"], row["failed"], row["waiting"]) == (1, 1, 1)


def test_the_approved_share_counts_only_what_a_person_decided(api, auth, world, db_session) -> None:
    for _ in range(3):
        proposal(db_session, world, status="approved")
    proposal(db_session, world, status="rejected")
    for _ in range(10):  # nobody looked at these: they say nothing about the suggestions
        proposal(db_session, world, status="expired")
    assert row_of(report(api, auth), SUGGESTIONS)["approved_share"] == "75.0"


def test_the_median_time_to_a_decision_is_in_minutes(api, auth, world, db_session) -> None:
    for minutes in (10, 30, 20):
        proposal(db_session, world, status="approved", minutes=minutes)
    proposal(db_session, world, status="expired", minutes=9999)  # not a decision by a person
    assert row_of(report(api, auth), SUGGESTIONS)["median_minutes_to_decision"] == "20.0"


def test_nothing_decided_gives_no_share_and_no_time(api, auth, world, db_session) -> None:
    proposal(db_session, world, status="pending")
    row = row_of(report(api, auth), SUGGESTIONS)
    assert row["proposed"] == 1
    assert row["approved_share"] is None and row["median_minutes_to_decision"] is None


def test_only_the_qualifiers_proposals_count(api, auth, world, db_session) -> None:
    proposal(db_session, world, agent="staff_assistant", status="approved")
    proposal(db_session, world, agent="mcp_client", status="approved")
    assert row_of(report(api, auth), SUGGESTIONS)["proposed"] == 0


def test_the_period_is_matched_on_when_the_suggestion_was_made(
    api, auth, world, db_session
) -> None:
    proposal(db_session, world, created=datetime(2026, 11, 10, 0, 0, tzinfo=UTC))  # first moment
    proposal(db_session, world, created=datetime(2026, 11, 16, 23, 59, tzinfo=UTC))  # last minute
    proposal(db_session, world, created=datetime(2026, 11, 9, 23, 59, tzinfo=UTC))
    proposal(db_session, world, created=datetime(2026, 11, 17, 0, 0, tzinfo=UTC))
    assert row_of(report(api, auth), SUGGESTIONS)["proposed"] == 2


def test_another_organisations_suggestions_never_count(api, auth, world, db_session) -> None:
    proposal(db_session, world, tenant=beta(world), status="approved")
    assert row_of(report(api, auth), SUGGESTIONS)["proposed"] == 0


def test_the_report_holds_no_reason_no_record_and_no_person(api, auth, world, db_session) -> None:
    action = proposal(db_session, world, status="approved")
    text = api.get(URL, params=PARAMS, headers=auth("alpha.manager")).text
    for secret in (WHY, str(action.target_id), str(action.requested_by_user_id)):
        assert secret not in text


# --- the AI cost per web lead ---------------------------------------------------------------------


def make_leads(db: Session, world: World) -> None:
    web_lead(db, world, last_name="One", created=datetime(2026, 11, 1, 0, 0, tzinfo=UTC))
    web_lead(db, world, last_name="Two", created=datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    web_lead(db, world, last_name="Three", created=datetime(2026, 11, 30, 23, 59, tzinfo=UTC))
    web_lead(db, world, last_name="Oct", created=datetime(2026, 10, 31, 23, 59, tzinfo=UTC))
    web_lead(db, world, last_name="Dec", created=datetime(2026, 12, 1, 0, 0, tzinfo=UTC))
    web_lead(db, world, last_name="Call", created=INSIDE, source="phone")  # not from the website


def test_the_cost_per_lead_uses_the_whole_month(api, auth, world, db_session) -> None:
    priced(api)
    make_leads(db_session, world)
    use(db_session, world, "public_chat", 1_000_000, 100_000)  # 3.00 + 1.50
    use(db_session, world, "qualifier", 200_000, 20_000)  # 0.60 + 0.30
    row = row_of(report(api, auth), COST)
    assert row["month"] == "2026-11-01"
    assert row["web_leads"] == 3  # the period is 10-16 November, the leads are the whole month's
    assert Decimal(row["estimated_cost_usd"]) == Decimal("5.4")
    assert Decimal(row["cost_per_lead_usd"]) == Decimal("1.8")


def test_other_agents_do_not_count_as_the_chats_cost(api, auth, world, db_session) -> None:
    priced(api)
    make_leads(db_session, world)
    use(db_session, world, "staff_assistant", 9_000_000, 9_000_000)
    use(db_session, world, "knowledge_answers", 9_000_000, 9_000_000)
    use(db_session, world, "public_chat", 1_000_000, 0)
    assert Decimal(row_of(report(api, auth), COST)["estimated_cost_usd"]) == Decimal("3")


def test_another_organisations_usage_never_counts(api, auth, world, db_session) -> None:
    priced(api)
    make_leads(db_session, world)
    use(db_session, world, "public_chat", 1_000_000, 0, tenant=beta(world))
    assert Decimal(row_of(report(api, auth), COST)["estimated_cost_usd"]) == Decimal("0")


def test_without_a_price_the_cost_is_blank_not_zero(api, auth, world, db_session) -> None:
    make_leads(db_session, world)  # the test settings carry no price
    use(db_session, world, "public_chat", 1_000_000, 100_000)
    row = row_of(report(api, auth), COST)
    assert row["web_leads"] == 3
    assert row["estimated_cost_usd"] is None and row["cost_per_lead_usd"] is None


def test_a_month_without_leads_has_no_cost_per_lead(api, auth, world, db_session) -> None:
    priced(api)
    use(db_session, world, "public_chat", 1_000_000, 0)
    row = row_of(report(api, auth), COST)
    assert row["web_leads"] == 0 and Decimal(row["estimated_cost_usd"]) == Decimal("3")
    assert row["cost_per_lead_usd"] is None


def test_a_period_across_two_months_gets_a_row_for_each(api, auth, world, db_session) -> None:
    priced(api)
    make_leads(db_session, world)
    use(db_session, world, "public_chat", 1_000_000, 0, when=datetime(2026, 10, 15, tzinfo=UTC))
    use(db_session, world, "public_chat", 2_000_000, 0)
    body = report(api, auth, start="2026-10-28", end="2026-11-03")
    rows = body["sections"][COST]["rows"]
    assert [r["month"] for r in rows] == ["2026-10-01", "2026-11-01"]
    assert [r["web_leads"] for r in rows] == [1, 3]
    assert [Decimal(r["estimated_cost_usd"]) for r in rows] == [Decimal("3"), Decimal("6")]


def test_the_new_sections_are_in_the_csv(api, auth, world, db_session) -> None:
    priced(api)
    make_leads(db_session, world)
    use(db_session, world, "public_chat", 1_000_000, 0)
    response = api.get(f"{URL}/csv", params=PARAMS, headers=auth("alpha.manager"))
    assert response.status_code == 200
    assert "AI cost per web lead" in response.text and "Qualifier suggestions" in response.text
