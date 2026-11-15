# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The deal desk's fact sheets, gathered for real (ADR 0024, step DD1).

The sheets are read AS THE PERSON ASKING through the other modules' api.py: a deal they may not
read is "not found", a quote of another deal never appears, an account they may not read gives no
health facts. Happy path, record-level denial, tenant isolation, role denial and ID tampering.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.modules.activities.models import Activity
from app.modules.contracts.models import Contract
from app.modules.deal_desk import api as deal_desk
from app.modules.sales.models import Opportunity
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import (  # noqa: F401
    Headers,
    World,
    api,
    auth,
    lines,
    new_quote,
    world,
)

NOW = datetime.now(UTC)


def sheets_for(
    db_session: Session, world: World, who: str, deal: uuid.UUID
) -> deal_desk.DealSheets:
    principal = principal_for(world.users[who], ROLES[who])
    bind_principal(db_session, principal)
    return deal_desk.build_sheets(db_session, principal, deal, NOW)


def big_discount_quote(api, auth, world, user="alpha.agent1", account="A1", deal="O1") -> str:  # noqa: ANN001, ANN201
    quote = new_quote(
        api,
        auth,
        world,
        user=user,
        account=account,
        opportunity_id=str(world.ids[deal]),
        lines=lines(world, ("P1", "3", "12")),
    )
    return str(quote["id"])


def test_the_owner_gets_three_sheets_built_from_the_deal(api, auth, world, db_session) -> None:
    quote_id = uuid.UUID(big_discount_quote(api, auth, world))
    sheets = sheets_for(db_session, world, "alpha.agent1", world.ids["O1"])
    assert sheets.opportunity_id == world.ids["O1"]

    assert "deal_amount_missing" in sheets.pricing.codes
    over = [f for f in sheets.pricing.facts if f.code == "discount_over_limit"]
    assert [f.record_id for f in over] == [quote_id]
    assert "12.00 %" in over[0].text and "10.00 %" in next(
        f.text for f in sheets.pricing.facts if f.code == "quote"
    )

    assert sheets.account.codes[0] == "health"
    assert sheets.account.record_ids == {world.ids["A1"]}

    assert {"stage_age", "no_next_step", "no_activity_logged", "no_primary_contact"} <= set(
        sheets.momentum.codes
    )
    assert sheets.momentum.record_ids == {world.ids["O1"]}


def test_a_manager_sees_the_same_deal(api, auth, world, db_session) -> None:
    big_discount_quote(api, auth, world)
    sheets = sheets_for(db_session, world, "alpha.manager", world.ids["O1"])
    assert "discount_over_limit" in sheets.pricing.codes


def test_a_colleagues_deal_is_not_found(world, db_session) -> None:
    with pytest.raises(deal_desk.DealNotFoundError):
        sheets_for(db_session, world, "alpha.agent2", world.ids["O1"])


def test_another_organisations_deal_is_not_found(world, db_session) -> None:
    with pytest.raises(deal_desk.DealNotFoundError):
        sheets_for(db_session, world, "beta.agent", world.ids["O1"])


@pytest.mark.parametrize("who", ["alpha.customer", "alpha.support"])
def test_people_without_deal_access_get_not_found(world, db_session, who: str) -> None:
    with pytest.raises(deal_desk.DealNotFoundError):
        sheets_for(db_session, world, who, world.ids["O1"])


def test_a_made_up_deal_id_is_not_found(world, db_session) -> None:
    with pytest.raises(deal_desk.DealNotFoundError):
        sheets_for(db_session, world, "alpha.manager", uuid.uuid4())


def test_a_quote_of_another_deal_never_appears(api, auth, world, db_session) -> None:
    other = uuid.UUID(big_discount_quote(api, auth, world, "alpha.agent2", "A2", "O2"))
    sheets = sheets_for(db_session, world, "alpha.manager", world.ids["O1"])
    every_id = sheets.pricing.record_ids | sheets.account.record_ids | sheets.momentum.record_ids
    assert other not in every_id
    assert "no_quote" in sheets.pricing.codes


def test_an_account_the_asker_may_not_read_gives_no_health(world, db_session) -> None:
    # agent1 owns a deal on an account owned by agent2: the deal is readable, its account is not.
    manager = principal_for(world.users["alpha.manager"], ROLES["alpha.manager"])
    bind_principal(db_session, manager)
    deal = Opportunity(
        tenant_id=world.users["alpha.agent1"].tenant_id,
        name="Own deal on a colleague's account",
        account_id=world.ids["A2"],
        owner_id=world.users["alpha.agent1"].id,
        currency="EUR",
    )
    db_session.add(deal)
    db_session.flush()

    sheets = sheets_for(db_session, world, "alpha.agent1", deal.id)
    assert sheets.account.codes == ["account_not_visible"]
    assert all("health" not in code for code in sheets.account.codes)

    # A manager may read the account and so gets its health.
    assert sheets_for(db_session, world, "alpha.manager", deal.id).account.codes[0] == "health"


def test_done_work_overdue_tasks_and_a_renewal_soon_are_read(world, db_session) -> None:
    manager = principal_for(world.users["alpha.manager"], ROLES["alpha.manager"])
    bind_principal(db_session, manager)
    tenant, agent = world.users["alpha.agent1"].tenant_id, world.users["alpha.agent1"].id
    deal = world.ids["O1"]
    db_session.add_all(
        [
            Activity(
                tenant_id=tenant,
                kind="call",
                subject="Called",
                status="done",
                completed_at=NOW - timedelta(days=2),
                assignee_id=agent,
                opportunity_id=deal,
            ),
            Activity(
                tenant_id=tenant,
                kind="task",
                subject="Send the plan",
                status="open",
                due_at=NOW - timedelta(days=1),
                assignee_id=agent,
                opportunity_id=deal,
            ),
            # Another deal's task never counts.
            Activity(
                tenant_id=tenant,
                kind="task",
                subject="Elsewhere",
                status="open",
                due_at=NOW - timedelta(days=1),
                assignee_id=agent,
                opportunity_id=world.ids["O2"],
            ),
            Contract(
                tenant_id=tenant,
                number=901,
                title="Service",
                status="active",
                account_id=world.ids["A1"],
                owner_id=agent,
                start_date=(NOW - timedelta(days=300)).date(),
                end_date=(NOW + timedelta(days=20)).date(),
            ),
        ]
    )
    db_session.flush()

    momentum = sheets_for(db_session, world, "alpha.agent1", deal).momentum
    assert "no_activity_logged" not in momentum.codes
    overdue = next(f for f in momentum.facts if f.code == "overdue_tasks")
    assert overdue.text.startswith("1 task")
    account = sheets_for(db_session, world, "alpha.agent1", deal).account
    assert "contract_renewal_soon" in account.codes
    # A contract of ANOTHER account that ends sooner never stands in for this one.
    bind_principal(db_session, manager)
    db_session.add(
        Contract(
            tenant_id=tenant,
            number=902,
            title="Other account",
            status="active",
            account_id=world.ids["A2"],
            owner_id=world.users["alpha.agent2"].id,
            start_date=(NOW - timedelta(days=300)).date(),
            end_date=(NOW + timedelta(days=5)).date(),
        )
    )
    db_session.flush()
    seen = sheets_for(db_session, world, "alpha.manager", deal).account
    renewal = next(f for f in seen.facts if f.code == "contract_renewal_soon")
    assert "(in 20 days)" in renewal.text
