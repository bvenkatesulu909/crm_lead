"""Dashboards - integration tests through the real API and PostgreSQL (rolled back).

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support, customer -> A1
tenant BETA:  admin, agent (owns B1)

Known records (relative to today) so every figure can be checked exactly:
  L1 agent1 new         created  2 days ago, no activity                  -> not idle yet
  L2 agent1 contacted   created 20 days ago, call 10 days ago             -> follow-up
  L3 agent1 converted   created  5 days ago, converted 1 day ago (A1)
  L4 agent2 qualified   created  3 days ago, meeting 1 day ago
  L5 (no owner) new     created 40 days ago (outside the default period)  -> follow-up
  BL beta lead          created  1 day ago
  O1 agent1 A1 proposal     1000.00 EUR, closes yesterday
  O2 agent2 A2 negotiation   500.50 EUR, no close date
  O3 agent1 A1 closed_won    999.00 EUR (not open)
  O4 agent2 A2 prospecting   no amount, USD
  OB beta                   7777.00 EUR
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Role, permissions_for
from app.core.config import Settings
from app.core.reporting import Filters, Period
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.contacts.models import Contact
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.leads.models import Lead, LeadActivity
from app.modules.sales.api import pipeline_metrics
from app.modules.sales.models import Opportunity
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for

PEOPLE = {
    "alpha.admin": ("alpha", "tenant_admin"),
    "alpha.manager": ("alpha", "sales_manager"),
    "alpha.agent1": ("alpha", "sales_agent"),
    "alpha.agent2": ("alpha", "sales_agent"),
    "alpha.support": ("alpha", "support_agent"),
    "alpha.customer": ("alpha", "customer"),
    "beta.admin": ("beta", "tenant_admin"),
    "beta.agent": ("beta", "sales_agent"),
}
Headers = Callable[[str], dict[str, str]]
NOW = datetime.now(UTC)
TODAY = NOW.date()
LINES = [
    {"description": "Widget", "quantity": "3", "unit_price": "19.99", "tax_rate": "19"},
    {"description": "Installation", "quantity": "1.5", "unit_price": "80.00", "tax_rate": "19"},
]  # fmt: skip  -> 214.16 incl. tax
URL = "/api/v1/dashboard"


def ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


class World:
    users: dict[str, User]
    accounts: dict[str, uuid.UUID]
    leads: dict[str, uuid.UUID]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        new_tenant = Tenant(slug=f"{slug}-dash", name=f"{slug.title()} Dashboard Test")
        db_session.add(new_tenant)
        db_session.flush()
        tenants[slug] = new_tenant.id
    w.users = {}
    for name, (slug, role) in PEOPLE.items():
        user = User(
            tenant_id=tenants[slug],
            idp_issuer=TEST_ISSUER,
            idp_subject=f"sub-{name}",
            email=f"{name}@example.test",
            display_name=name,
            user_type="customer" if role == "customer" else "staff",
            roles=[role],
        )
        db_session.add(user)
        w.users[name] = user
    db_session.flush()
    alpha, beta = tenants["alpha"], tenants["beta"]
    u = {name: user.id for name, user in w.users.items()}

    w.accounts = {}
    for key, account_tenant, account_owner, created in [
        ("A1", alpha, u["alpha.agent1"], NOW),
        ("A2", alpha, u["alpha.agent2"], ago(60)),
        ("B1", beta, u["beta.agent"], NOW),
    ]:
        account = Account(
            tenant_id=account_tenant,
            name=f"Dash Account {key}",
            owner_id=account_owner,
            created_at=created,
        )
        db_session.add(account)
        db_session.flush()
        w.accounts[key] = account.id
    db_session.add(
        PortalAccessGrant(tenant_id=alpha, user_id=u["alpha.customer"], account_id=w.accounts["A1"])
    )
    contact = Contact(tenant_id=alpha, last_name="Three", account_id=w.accounts["A1"])
    db_session.add(contact)
    db_session.flush()

    w.leads = {}
    for key, lead_tenant, lead_owner, status, created, extra in [
        ("L1", alpha, u["alpha.agent1"], "new", ago(2), {}),
        ("L2", alpha, u["alpha.agent1"], "contacted", ago(20), {}),
        (
            "L3",
            alpha,
            u["alpha.agent1"],
            "converted",
            ago(5),
            {
                "converted_at": ago(1),
                "converted_account_id": w.accounts["A1"],
                "converted_contact_id": contact.id,
            },
        ),
        ("L4", alpha, u["alpha.agent2"], "qualified", ago(3), {}),
        ("L5", alpha, None, "new", ago(40), {}),
        ("BL", beta, u["beta.agent"], "new", ago(1), {}),
    ]:
        lead = Lead(
            tenant_id=lead_tenant,
            last_name=f"Lead {key}",
            company_name=f"{key} GmbH",
            owner_id=lead_owner,
            status=status,
            created_at=created,
            **extra,
        )
        db_session.add(lead)
        db_session.flush()
        w.leads[key] = lead.id
    for key, kind, subject, actor, when in [
        ("L2", "call", "Intro call", "alpha.agent1", ago(10)),
        ("L4", "meeting", "Demo meeting", "alpha.agent2", ago(1)),
        ("BL", "call", "Beta call", "beta.agent", ago(1)),
    ]:
        db_session.add(
            LeadActivity(
                tenant_id=alpha if key != "BL" else beta,
                lead_id=w.leads[key],
                kind=kind,
                subject=subject,
                actor_user_id=u[actor],
                occurred_at=when,
            )
        )

    for name, opp_tenant, account_key, owner_name, stage, amount, currency, closes in [
        ("O1", alpha, "A1", "alpha.agent1", "proposal", "1000.00", "EUR", TODAY - timedelta(1)),
        ("O2", alpha, "A2", "alpha.agent2", "negotiation", "500.50", "EUR", None),
        ("O3", alpha, "A1", "alpha.agent1", "closed_won", "999.00", "EUR", None),
        ("O4", alpha, "A2", "alpha.agent2", "prospecting", None, "USD", None),
        ("OB", beta, "B1", "beta.agent", "proposal", "7777.00", "EUR", TODAY),
    ]:
        db_session.add(
            Opportunity(
                tenant_id=opp_tenant,
                name=name,
                account_id=w.accounts[account_key],
                owner_id=u[owner_name],
                stage=stage,
                amount=Decimal(amount) if amount else None,
                currency=currency,
                expected_close_date=closes,
                # Won/lost deals always have a close date (database rule since migration 0011).
                closed_at=ago(2) if stage.startswith("closed") else None,
            )
        )
    db_session.flush()
    return w


@pytest.fixture
def api(db_connection: Connection, token_factory: TokenFactory) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
    )
    app = create_app(settings, token_verifier=token_factory.verifier())
    app.state.session_factory = session_factory_for(db_connection)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth(token_factory: TokenFactory, world: World) -> Headers:
    return lambda name: bearer(token_factory.mint(f"sub-{name}", [PEOPLE[name][1]]))


def ok(response: Any, code: int = 200) -> dict[str, Any]:
    assert response.status_code == code, response.text
    result: dict[str, Any] = response.json()
    return result


def dashboard(api: TestClient, auth: Headers, user: str, **params: Any) -> dict[str, Any]:
    return ok(api.get(URL, params=params, headers=auth(user)))


def money(amounts: list[dict[str, str]]) -> dict[str, str]:
    return {m["currency"]: m["amount"] for m in amounts}


# --- Views and roles ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user", "view", "views"),
    [
        ("alpha.admin", "executive", ["executive", "manager", "representative"]),
        ("alpha.manager", "manager", ["manager", "representative"]),
        ("alpha.agent1", "representative", ["representative"]),
    ],
)
def test_each_role_gets_its_widest_view_by_default(api, auth, world, user, view, views) -> None:
    body = dashboard(api, auth, user)
    assert (body["view"], body["available_views"]) == (view, views)
    assert body["period"] == {"start": str(TODAY - timedelta(29)), "end": str(TODAY)}
    assert (body["team"] is not None) == (view != "representative")
    assert (body["revenue"] is not None) == (view == "executive")


@pytest.mark.parametrize("user", ["alpha.support", "alpha.customer"])
def test_roles_without_a_dashboard_are_refused(api, auth, world, user) -> None:
    assert api.get(URL, headers=auth(user)).status_code == 403


@pytest.mark.parametrize(
    ("user", "view"),
    [("alpha.manager", "executive"), ("alpha.agent1", "manager"), ("alpha.agent1", "executive")],
)
def test_a_wider_view_than_the_role_allows_is_refused(api, auth, world, user, view) -> None:
    response = api.get(URL, params={"view": view}, headers=auth(user))
    assert response.status_code == 403


def test_unknown_view_is_a_validation_error(api, auth, world) -> None:
    assert api.get(URL, params={"view": "god"}, headers=auth("alpha.admin")).status_code == 422


def test_without_a_token_the_dashboard_is_closed(api, world) -> None:
    assert api.get(URL).status_code == 401


# --- Exact figures --------------------------------------------------------------------------------


def test_manager_sees_the_whole_sales_team(api, auth, world) -> None:
    body = dashboard(api, auth, "alpha.manager")
    assert body["leads"] == {
        "created": 4,  # L1-L4; L5 is older than 30 days, BL belongs to another tenant
        "assigned": 4,
        "unassigned": 0,
        "new": 1,
        "contacted": 1,
        "qualified": 1,
        "unqualified": 0,
        "converted": 1,
        "converted_in_period": 1,
        "open_now": 4,  # L1, L2, L4, L5
        "conversion_rate": 0.25,
    }
    assert body["customers"] == {"total": 2, "active": 2, "new_in_period": 1}
    pipeline = body["pipeline"]
    assert (pipeline["open_count"], pipeline["without_amount"]) == (3, 1)
    assert money(pipeline["open_value"]) == {"EUR": "1500.50"}  # O4 has no amount: no USD 0.00
    assert [(s["stage"], s["count"]) for s in pipeline["by_stage"]] == [
        ("prospecting", 1),
        ("qualification", 0),
        ("proposal", 1),
        ("negotiation", 1),
    ]
    assert (pipeline["closing_in_period"], money(pipeline["closing_in_period_value"])) == (
        1,
        {"EUR": "1000.00"},
    )

    follow = body["follow_ups"]
    assert follow["total"] == 2
    assert [(f["name"], f["owner_name"], f["days_idle"]) for f in follow["items"]] == [
        ("Lead L5", None, 40),
        ("Lead L2", "alpha.agent1", 10),
    ]

    activities = body["recent_activities"]
    assert [(a["title"], a["actor_name"]) for a in activities] == [
        ("Meeting: Lead L4", "alpha.agent2"),
        ("Call: Lead L2", "alpha.agent1"),
    ]

    team = {row["name"]: row for row in body["team"]}
    assert set(team) == {"alpha.agent1", "alpha.agent2", "alpha.manager", "No owner"}
    assert team["alpha.agent1"] | {"open_value": money(team["alpha.agent1"]["open_value"])} == {
        "user_id": str(world.users["alpha.agent1"].id),
        "name": "alpha.agent1",
        "leads_created": 3,
        "qualified": 0,
        "converted_in_period": 1,
        "customers": 1,
        "open_opportunities": 1,
        "open_value": {"EUR": "1000.00"},
        "follow_ups": 1,
    }
    agent2 = team["alpha.agent2"]
    assert (agent2["leads_created"], agent2["qualified"], agent2["open_opportunities"]) == (1, 1, 2)
    assert money(agent2["open_value"]) == {"EUR": "500.50"}
    assert (team["No owner"]["user_id"], team["No owner"]["follow_ups"]) == (None, 1)
    assert team["alpha.manager"]["leads_created"] == 0


def test_representative_sees_only_own_records(api, auth, world) -> None:
    body = dashboard(api, auth, "alpha.agent1")
    assert (body["leads"]["created"], body["leads"]["open_now"]) == (3, 2)
    assert body["customers"]["total"] == 1
    assert body["pipeline"]["open_count"] == 1
    assert money(body["pipeline"]["open_value"]) == {"EUR": "1000.00"}
    assert [f["name"] for f in body["follow_ups"]["items"]] == ["Lead L2"]
    assert [a["title"] for a in body["recent_activities"]] == ["Call: Lead L2"]
    assert body["team"] is None
    assert body["owner_id"] is None


def test_representative_may_name_only_themself(api, auth, world) -> None:
    me = str(world.users["alpha.agent1"].id)
    other = str(world.users["alpha.agent2"].id)
    assert dashboard(api, auth, "alpha.agent1", owner_id=me)["leads"]["created"] == 3
    response = api.get(URL, params={"owner_id": other}, headers=auth("alpha.agent1"))
    assert response.status_code == 403


def test_manager_can_narrow_to_one_rep(api, auth, world) -> None:
    agent2 = str(world.users["alpha.agent2"].id)
    body = dashboard(api, auth, "alpha.manager", owner_id=agent2)
    assert body["owner_id"] == agent2
    assert (body["leads"]["created"], body["leads"]["qualified"]) == (1, 1)
    assert body["customers"]["total"] == 1
    assert body["pipeline"]["open_count"] == 2
    assert body["follow_ups"]["total"] == 0
    assert [row["name"] for row in body["team"]] == ["alpha.agent2"]
    assert [a["title"] for a in body["recent_activities"]] == ["Meeting: Lead L4"]


@pytest.mark.parametrize("who", ["beta.agent", "random"])
def test_rep_filter_must_be_staff_of_the_same_tenant(api, auth, world, who) -> None:
    owner = str(world.users[who].id) if who in world.users else str(uuid.uuid4())
    response = api.get(URL, params={"owner_id": owner}, headers=auth("alpha.manager"))
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_filter"


def test_a_customer_cannot_be_used_as_rep_filter(api, auth, world) -> None:
    owner = str(world.users["alpha.customer"].id)
    response = api.get(URL, params={"owner_id": owner}, headers=auth("alpha.manager"))
    assert response.status_code == 422


def test_other_tenant_sees_only_its_own_figures(api, auth, world) -> None:
    body = dashboard(api, auth, "beta.admin")
    assert body["leads"]["created"] == 1
    assert body["customers"]["total"] == 1
    assert money(body["pipeline"]["open_value"]) == {"EUR": "7777.00"}
    assert [a["title"] for a in body["recent_activities"]] == ["Call: Lead BL"]
    assert [row["name"] for row in body["team"]] == ["beta.agent"]


# --- Date filter ---------------------------------------------------------------------------------


def test_custom_period_changes_period_figures_only(api, auth, world) -> None:
    start, end = str(TODAY - timedelta(45)), str(TODAY - timedelta(35))
    body = dashboard(api, auth, "alpha.manager", start=start, end=end)
    assert body["period"] == {"start": start, "end": end}
    assert (body["leads"]["created"], body["leads"]["unassigned"]) == (1, 1)  # L5
    assert body["leads"]["open_now"] == 4  # "now" figures ignore the period
    assert body["customers"]["new_in_period"] == 0
    assert body["pipeline"]["closing_in_period"] == 0
    assert body["recent_activities"] == []


def test_single_day_period_includes_that_whole_day(api, auth, world) -> None:
    day = str(TODAY - timedelta(1))
    body = dashboard(api, auth, "alpha.manager", start=day, end=day)
    assert body["leads"]["converted_in_period"] == 1  # L3, converted yesterday
    assert body["pipeline"]["closing_in_period"] == 1  # O1 closes yesterday


@pytest.mark.parametrize(
    "params",
    [
        {"start": str(TODAY), "end": str(TODAY - timedelta(1))},  # end before start
        {"start": str(TODAY - timedelta(1200)), "end": str(TODAY)},  # more than 3 years
        {"start": "not-a-date"},
    ],
)
def test_invalid_periods_are_refused(api, auth, world, params) -> None:
    assert api.get(URL, params=params, headers=auth("alpha.manager")).status_code == 422


# --- Executive -----------------------------------------------------------------------------------


def test_executive_view_adds_revenue_orders_and_support(api, auth, world) -> None:
    a1 = str(world.accounts["A1"])
    admin = auth("alpha.admin")
    order = ok(
        api.post("/api/v1/orders", json={"account_id": a1, "lines": LINES}, headers=admin), 201
    )
    order = ok(
        api.post(
            f"/api/v1/orders/{order['id']}/status",
            json={"status": "confirmed", "version": order["version"]},
            headers=admin,
        )
    )
    draft = ok(api.post("/api/v1/invoices", json={"order_id": order["id"]}, headers=admin), 201)
    invoice = ok(
        api.post(
            f"/api/v1/invoices/{draft['id']}/issue",
            json={"version": draft["version"]},
            headers=admin,
        )
    )
    payment = {"amount": "100.00", "received_on": str(TODAY), "method": "bank_transfer"}
    ok(api.post(f"/api/v1/invoices/{invoice['id']}/payments", json=payment, headers=admin), 201)
    # A payment entered by mistake and reversed must not count as money received.
    mistake = ok(
        api.post(
            f"/api/v1/invoices/{invoice['id']}/payments",
            json=payment | {"amount": "50.00"},
            headers=admin,
        ),
        201,
    )
    ok(
        api.post(
            f"/api/v1/invoices/{invoice['id']}/payments/{mistake['payments'][-1]['id']}/reverse",
            json={"reason": "Entered twice"},
            headers=admin,
        ),
        201,
    )
    ticket = {"account_id": a1, "subject": "Broken widget", "description": "It squeaks."}
    ok(api.post("/api/v1/tickets", json=ticket, headers=admin), 201)

    body = dashboard(api, auth, "alpha.admin")
    revenue = body["revenue"]
    assert (revenue["issued_count"], money(revenue["issued_value"])) == (1, {"EUR": "214.16"})
    assert money(revenue["received"]) == {"EUR": "100.00"}
    assert (revenue["outstanding_count"], money(revenue["outstanding"])) == (1, {"EUR": "114.16"})
    assert (revenue["overdue_count"], revenue["overdue"]) == (0, [])
    assert body["orders"]["confirmed_in_period"] == 1
    assert money(body["orders"]["confirmed_value"]) == {"EUR": "214.16"}
    assert body["orders"]["in_progress_now"] == 1
    assert body["support"] == {
        "open_now": 1,
        "sla_overdue_now": 0,
        "opened_in_period": 1,
        "complaints_in_period": 0,
        "ratings_in_period": 0,
        "average_rating": None,
    }
    titles = [a["title"] for a in body["recent_activities"]]
    assert "Order confirmed" in " ".join(titles)
    assert any(t.startswith("Support ticket opened: T-") for t in titles)

    # The rep filter narrows these too: agent2 owns A2, which has no orders, invoices or tickets.
    agent2 = str(world.users["alpha.agent2"].id)
    narrowed = dashboard(api, auth, "alpha.admin", owner_id=agent2)
    assert (narrowed["revenue"]["issued_count"], narrowed["revenue"]["received"]) == (0, [])
    assert narrowed["orders"]["confirmed_in_period"] == 0
    assert narrowed["support"]["open_now"] == 0

    # ... and the other tenant sees none of it.
    beta = dashboard(api, auth, "beta.admin")
    assert (beta["revenue"]["issued_count"], beta["orders"]["in_progress_now"]) == (0, 0)
    assert beta["support"]["open_now"] == 0


def test_manager_choosing_the_representative_view_sees_only_own_records(api, auth, world) -> None:
    body = dashboard(api, auth, "alpha.manager", view="representative")
    assert body["view"] == "representative"
    assert (body["leads"]["created"], body["pipeline"]["open_count"]) == (0, 0)
    assert (body["follow_ups"]["total"], body["team"]) == (0, None)


def test_pipeline_figures_apply_the_opportunity_policy_on_their_own(
    db_session: Session, world: World
) -> None:
    """Defence in depth: even without a rep filter, an agent's figures cover only their own
    opportunities, and a role without opportunity access gets nothing."""

    def principal(name: str, role: Role) -> Principal:
        user = world.users[name]
        return Principal(
            subject=user.idp_subject,
            issuer=TEST_ISSUER,
            user_type="staff",
            roles=frozenset({role}),
            permissions=permissions_for(frozenset({role})),
            user_id=user.id,
            tenant_id=user.tenant_id,
        )

    filters = Filters(Period(TODAY - timedelta(29), TODAY))
    agent = pipeline_metrics(db_session, principal("alpha.agent2", Role.SALES_AGENT), filters)
    assert (agent.open_count, agent.without_amount) == (2, 1)
    support = pipeline_metrics(db_session, principal("alpha.support", Role.SUPPORT_AGENT), filters)
    assert support.open_count == 0
