"""Phase B2 - segmentation, duplicate detection, ownership transfer, customer health, lead
scoring and customer feedback, through the real API and PostgreSQL (rolled back).

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support, customer -> A1
tenant BETA:  admin, agent (owns B1)
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Role, permissions_for
from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.activities.models import Activity
from app.modules.contacts.models import Contact
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.leads import scoring
from app.modules.leads.models import Lead, LeadActivity
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
    "alpha.customer2": ("alpha", "customer"),
    "beta.admin": ("beta", "tenant_admin"),
    "beta.agent": ("beta", "sales_agent"),
}
Headers = Callable[[str], dict[str, str]]
ACCOUNTS = "/api/v1/accounts"
CONTACTS = "/api/v1/contacts"
NOW = datetime.now(UTC)
LINES = [{"description": "Widget", "quantity": "1", "unit_price": "100.00", "tax_rate": "0"}]


class World:
    users: dict[str, User]
    ids: dict[str, uuid.UUID]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        new_tenant = Tenant(slug=f"{slug}-rel", name=f"{slug.title()} Relationship Test")
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
    w.ids = {}
    a1_fields = {
        "website": "https://www.example-one.test",
        "phone": "+44 20 7946 0001",
        "country": "GB",
        "lifecycle_stage": "active_customer",
        "industry": "Retail",
    }
    a2_fields = {
        "name": "Hidden Gadgets Limited",
        "country": "DE",
        "lifecycle_stage": "prospect",
        "account_type": "branch",
    }
    for key, owner, extra in [
        ("A1", "alpha.agent1", a1_fields),
        ("A2", "alpha.agent2", a2_fields),
        ("B1", "beta.agent", {"name": "Example One Ltd"}),
    ]:
        user = w.users[owner]
        account = Account(
            tenant_id=user.tenant_id,
            name=extra.pop("name", "Example One Ltd" if key == "A1" else key),
            owner_id=user.id,
            **extra,
        )
        db_session.add(account)
        db_session.flush()
        w.ids[key] = account.id
    for customer in ("alpha.customer", "alpha.customer2"):
        u = w.users[customer]
        db_session.add(
            PortalAccessGrant(tenant_id=u.tenant_id, user_id=u.id, account_id=w.ids["A1"])
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


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def code_of(response: Any) -> tuple[int, str | None]:
    body = response.json() if response.content else {}
    return response.status_code, body.get("code")


def uid(world: World, name: str) -> str:
    return str(world.users[name].id)


def names(page: Any) -> list[str]:
    return [item["name"] for item in page["items"]]


# === Segmentation =================================================================================


def test_new_customer_fields_are_stored_and_validated(api, auth, world) -> None:
    body = {
        "name": "Segmented Co",
        "country": "IN",
        "region": "Karnataka",
        "city": "Bengaluru",
        "lifecycle_stage": "onboarding",
        "account_type": "headquarters",
        "preferred_language": "kn",
    }
    created = ok(api.post(ACCOUNTS, json=body, headers=auth("alpha.agent1")), 201)
    assert {k: created[k] for k in body} == body
    default = ok(api.post(ACCOUNTS, json={"name": "Plain Co"}, headers=auth("alpha.agent1")), 201)
    assert (default["account_type"], default["lifecycle_stage"]) == ("company", None)
    for bad in (
        {"country": "in"},
        {"country": "IND"},
        {"preferred_language": "EN"},
        {"lifecycle_stage": "vip"},
        {"account_type": "store"},
    ):
        response = api.post(ACCOUNTS, json={"name": "X", **bad}, headers=auth("alpha.agent1"))
        assert response.status_code == 422, bad
    url = f"{ACCOUNTS}/{created['id']}"
    changed = ok(
        api.patch(
            url,
            json={"version": 1, "lifecycle_stage": "active_customer"},
            headers=auth("alpha.agent1"),
        )
    )
    assert changed["lifecycle_stage"] == "active_customer"
    assert (
        api.patch(
            url, json={"version": 2, "account_type": None}, headers=auth("alpha.agent1")
        ).status_code
        == 422
    )


def test_segmentation_filters(api, auth, world) -> None:
    manager = auth("alpha.manager")

    def find(**params: Any) -> list[str]:
        return names(ok(api.get(ACCOUNTS, params=params, headers=manager)))

    assert find(country="GB") == ["Example One Ltd"]
    assert find(lifecycle_stage="prospect") == ["Hidden Gadgets Limited"]
    assert find(account_type="branch") == ["Hidden Gadgets Limited"]
    assert find(industry="reta") == ["Example One Ltd"]
    assert find(owner_id=uid(world, "alpha.agent2")) == ["Hidden Gadgets Limited"]
    assert find(country="GB", lifecycle_stage="prospect") == []
    assert api.get(ACCOUNTS, params={"country": "gb"}, headers=manager).status_code == 422
    # Agents still only see their own accounts, whatever the filter.
    assert (
        names(ok(api.get(ACCOUNTS, params={"country": "DE"}, headers=auth("alpha.agent1")))) == []
    )


def test_customer_value_filter_uses_issued_invoices(api, auth, world) -> None:
    admin = auth("alpha.admin")
    a1 = str(world.ids["A1"])
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

    def valued(minimum: str, currency: str = "EUR") -> list[str]:
        params = {"min_value": minimum, "value_currency": currency}
        return names(ok(api.get(ACCOUNTS, params=params, headers=admin)))

    draft = ok(api.post("/api/v1/invoices", json={"order_id": order["id"]}, headers=admin), 201)
    assert valued("50") == []  # a draft is not customer value yet
    ok(
        api.post(
            f"/api/v1/invoices/{draft['id']}/issue",
            json={"version": draft["version"]},
            headers=admin,
        )
    )
    assert valued("50") == ["Example One Ltd"]
    assert valued("100.00") == ["Example One Ltd"]
    assert valued("100.01") == []
    assert valued("50", "USD") == []  # currencies are never mixed
    assert api.get(ACCOUNTS, params={"min_value": "5"}, headers=admin).status_code == 422
    health = ok(api.get(f"{ACCOUNTS}/{a1}/health", headers=admin))
    assert health["lifetime_value"] == [{"currency": "EUR", "amount": "100.00"}]


# === Duplicate detection ==========================================================================


def test_account_duplicates_by_name_website_and_phone(api, auth, world) -> None:
    def check(user: str, **params: Any) -> Any:
        return ok(api.get(f"{ACCOUNTS}/duplicates", params=params, headers=auth(user)))

    by_name = check("alpha.manager", name="example one limited")
    assert [(c["name"], c["reasons"]) for c in by_name["candidates"]] == [
        ("Example One Ltd", ["Same company name"])
    ]  # B1 (same name, other tenant) is never counted
    assert by_name["hidden_matches"] == 0
    by_site = check("alpha.manager", website="http://example-one.test/contact")
    assert by_site["candidates"][0]["reasons"] == ["Same website"]
    by_phone = check("alpha.manager", phone="020 7946 0001", name="Totally Different")
    assert by_phone["candidates"][0]["reasons"] == ["Same phone number"]
    assert check("alpha.manager", name="Nothing Alike")["candidates"] == []
    excluded = check("alpha.manager", name="Example One", exclude_id=str(world.ids["A1"]))
    assert excluded["candidates"] == []

    # Agent1 can't see agent2's account: it is counted, never named.
    hidden = check("alpha.agent1", name="hidden gadgets")
    assert (hidden["candidates"], hidden["hidden_matches"]) == ([], 1)


def test_contact_duplicates(api, auth, world, db_session) -> None:
    a1, a2 = world.ids["A1"], world.ids["A2"]
    for first, last, email, mobile, account, owner in [
        ("Sam", "Sample", "Sam@Example.test", "+44 7700 900123", a1, "alpha.agent1"),
        ("Pat", "Private", "pat@example.test", None, a2, "alpha.agent2"),
    ]:
        user = world.users[owner]
        db_session.add(
            Contact(
                tenant_id=user.tenant_id,
                first_name=first,
                last_name=last,
                email=email,
                mobile=mobile,
                account_id=account,
                owner_id=user.id,
            )
        )
    db_session.flush()

    def check(user: str, **params: Any) -> Any:
        return ok(api.get(f"{CONTACTS}/duplicates", params=params, headers=auth(user)))

    assert check("alpha.agent1", email="sam@example.TEST")["candidates"][0]["reasons"] == [
        "Same e-mail"
    ]
    assert check("alpha.agent1", phone="07700 900123")["candidates"][0]["reasons"] == [
        "Same phone number"
    ]
    named = check("alpha.agent1", first_name="sam", last_name="SAMPLE")
    assert named["candidates"][0]["name"] == "Sam Sample"
    hidden = check("alpha.agent1", email="pat@example.test")
    assert (hidden["candidates"], hidden["hidden_matches"]) == ([], 1)
    assert check("beta.admin", email="sam@example.test") == {"candidates": [], "hidden_matches": 0}


# === Ownership transfer ===========================================================================


def _relationship(db_session: Session, world: World) -> dict[str, uuid.UUID]:
    """A1 (agent1) with contacts, deals and tasks owned by different people."""
    agent1, manager = world.users["alpha.agent1"], world.users["alpha.manager"]
    tenant = agent1.tenant_id
    a1 = world.ids["A1"]
    ids: dict[str, uuid.UUID] = {}
    for key, owner in [("c_agent", agent1), ("c_manager", manager)]:
        contact = Contact(tenant_id=tenant, last_name=key, account_id=a1, owner_id=owner.id)
        db_session.add(contact)
        db_session.flush()
        ids[key] = contact.id
    for key, stage in [("open_deal", "proposal"), ("won_deal", "closed_won")]:
        deal = Opportunity(
            tenant_id=tenant,
            name=key,
            account_id=a1,
            owner_id=agent1.id,
            stage=stage,
            amount=Decimal("10.00"),
            currency="EUR",
            closed_at=NOW if stage == "closed_won" else None,
        )
        db_session.add(deal)
        db_session.flush()
        ids[key] = deal.id
    for key, assignee, status, link in [
        ("task_on_account", agent1, "open", {"account_id": a1}),
        ("task_on_contact", agent1, "open", {"contact_id": ids["c_agent"]}),
        ("task_on_deal", agent1, "open", {"opportunity_id": ids["open_deal"]}),
        ("task_of_manager", manager, "open", {"account_id": a1}),
        ("done_task", agent1, "done", {"account_id": a1}),
    ]:
        task = Activity(
            tenant_id=tenant,
            kind="task",
            subject=key,
            status=status,
            completed_at=NOW if status == "done" else None,
            assignee_id=assignee.id,
            created_by_user_id=assignee.id,
            **link,
        )
        db_session.add(task)
        db_session.flush()
        ids[key] = task.id
    return ids


def test_manager_transfers_a_customer_with_its_related_work(api, auth, world, db_session) -> None:
    ids = _relationship(db_session, world)
    url = f"{ACCOUNTS}/{world.ids['A1']}/transfer"
    body = {"version": 1, "new_owner_id": uid(world, "alpha.agent2"), "reason": "Territory change"}
    result = ok(api.post(url, json=body, headers=auth("alpha.manager")))
    assert (result["contacts_moved"], result["opportunities_moved"], result["tasks_moved"]) == (
        1,
        1,
        3,
    )
    assert result["previous_owner_id"] == uid(world, "alpha.agent1")

    def owner(model: Any, key: str) -> uuid.UUID | None:
        db_session.expire_all()
        row = db_session.get(model, ids[key])
        value: uuid.UUID | None = row.assignee_id if model is Activity else row.owner_id
        return value

    agent1, agent2, manager = (
        world.users[n].id for n in ("alpha.agent1", "alpha.agent2", "alpha.manager")
    )
    assert owner(Contact, "c_agent") == agent2
    assert owner(Contact, "c_manager") == manager  # someone else's contact stays theirs
    assert owner(Opportunity, "open_deal") == agent2
    assert owner(Opportunity, "won_deal") == agent1  # closed deals keep who won them
    for task in ("task_on_account", "task_on_contact", "task_on_deal"):
        assert owner(Activity, task) == agent2
    assert owner(Activity, "task_of_manager") == manager
    assert owner(Activity, "done_task") == agent1

    timeline = ok(api.get(f"{ACCOUNTS}/{world.ids['A1']}/timeline", headers=auth("alpha.manager")))
    transferred = [t for t in timeline if t["action"] == "account.owner_transferred"]
    assert any(t["changes"].get("reason") == "Territory change" for t in transferred)
    assert any(
        t["changes"].get("moved") == {"contacts": 1, "opportunities": 1, "tasks": 3}
        for t in transferred
    )
    # The old owner no longer sees the customer; the new owner does.
    assert api.get(f"{ACCOUNTS}/{world.ids['A1']}", headers=auth("alpha.agent1")).status_code == 404
    assert api.get(f"{ACCOUNTS}/{world.ids['A1']}", headers=auth("alpha.agent2")).status_code == 200


def test_transfer_can_leave_related_records_alone(api, auth, world, db_session) -> None:
    ids = _relationship(db_session, world)
    body = {
        "version": 1,
        "new_owner_id": uid(world, "alpha.agent2"),
        "reason": "Account only",
        "include_contacts": False,
        "include_open_opportunities": False,
        "include_open_tasks": False,
    }
    result = ok(
        api.post(f"{ACCOUNTS}/{world.ids['A1']}/transfer", json=body, headers=auth("alpha.manager"))
    )
    assert (result["contacts_moved"], result["opportunities_moved"], result["tasks_moved"]) == (
        0,
        0,
        0,
    )
    db_session.expire_all()
    assert db_session.get(Contact, ids["c_agent"]).owner_id == world.users["alpha.agent1"].id


@pytest.mark.parametrize(
    ("user", "new_owner", "version", "expected"),
    [
        ("alpha.agent1", "alpha.agent2", 1, (403, None)),  # agents can't transfer
        ("alpha.support", "alpha.agent2", 1, (403, None)),
        ("beta.admin", "beta.agent", 1, (404, "account_not_found")),  # other tenant
        ("alpha.manager", "alpha.agent2", 7, (409, "version_conflict")),
        ("alpha.manager", "alpha.agent1", 1, (409, "account_state")),  # already the owner
        ("alpha.manager", "alpha.support", 1, (422, "invalid_owner")),
        ("alpha.manager", "beta.agent", 1, (422, "invalid_owner")),
    ],
)
def test_transfer_rules(api, auth, world, user, new_owner, version, expected) -> None:
    body = {"version": version, "new_owner_id": uid(world, new_owner), "reason": "x"}
    response = api.post(f"{ACCOUNTS}/{world.ids['A1']}/transfer", json=body, headers=auth(user))
    status, code = code_of(response)
    assert status == expected[0]
    if expected[1]:
        assert code == expected[1]


def test_transfer_needs_a_reason(api, auth, world) -> None:
    body = {"version": 1, "new_owner_id": uid(world, "alpha.agent2")}
    url = f"{ACCOUNTS}/{world.ids['A1']}/transfer"
    assert api.post(url, json=body, headers=auth("alpha.manager")).status_code == 422


# === Customer health ==============================================================================


def test_account_health_follows_real_interactions(api, auth, world, db_session) -> None:
    url = f"{ACCOUNTS}/{world.ids['A1']}/health"
    first = ok(api.get(url, headers=auth("alpha.agent1")))
    assert (first["score"], first["label"], first["inactive"]) == (80, "healthy", True)
    assert [f["label"] for f in first["factors"]] == ["No recorded interaction yet"]

    agent = world.users["alpha.agent1"]
    db_session.add(
        Activity(
            tenant_id=agent.tenant_id,
            kind="call",
            subject="Old call",
            status="done",
            completed_at=NOW - timedelta(days=120),
            assignee_id=agent.id,
            account_id=world.ids["A1"],
        )
    )
    db_session.flush()
    quiet = ok(api.get(url, headers=auth("alpha.agent1")))
    assert (quiet["score"], quiet["label"], quiet["days_inactive"], quiet["inactive"]) == (
        70,
        "watch",
        120,
        True,
    )

    complaint = {"account_id": str(world.ids["A1"]), "subject": "Broken", "description": "Again",
                 "category": "complaint"}  # fmt: skip
    ok(api.post("/api/v1/portal/tickets", json=complaint, headers=auth("alpha.customer")), 201)
    with_ticket = ok(api.get(url, headers=auth("alpha.agent1")))
    # The new ticket counts as an interaction today, but the open complaint costs 10 points.
    assert (with_ticket["score"], with_ticket["inactive"]) == (90, False)
    assert {"label": "1 open complaint(s)", "impact": -10} in with_ticket["factors"]

    assert api.get(url, headers=auth("alpha.agent2")).status_code == 404
    assert api.get(url, headers=auth("beta.admin")).status_code == 404
    assert api.get(url, headers=auth("alpha.customer")).status_code == 403


def test_health_overview_lists_least_healthy_first(api, auth, world, db_session) -> None:
    account = db_session.get(Account, world.ids["A2"])
    account.lifecycle_stage = "churned"
    db_session.flush()
    overview = ok(api.get("/api/v1/customer-health", headers=auth("alpha.manager")))
    assert [r["name"] for r in overview["items"]] == ["Hidden Gadgets Limited", "Example One Ltd"]
    assert overview["items"][0]["top_factor"] == "Marked as churned"
    assert (overview["assessed"], overview["at_risk"], overview["inactive"]) == (2, 1, 2)
    mine = ok(api.get("/api/v1/customer-health", headers=auth("alpha.agent1")))
    assert [r["name"] for r in mine["items"]] == ["Example One Ltd"]
    assert ok(api.get("/api/v1/customer-health", headers=auth("beta.admin")))["assessed"] == 1


# === Lead scoring =================================================================================


HOT = {
    "email": "h@example.test",
    "phone": "123456",
    "company_name": "Hot Co",
    "job_title": "Chief Technology Officer",
    "source": "referral",
    "status": "qualified",
}
WARM = {
    "email": "w@example.test",
    "company_name": "Warm Co",
    "job_title": "Engineer",
    "source": "web",
    "status": "contacted",
}
OUT = {
    "email": "o@example.test",
    "phone": "1",
    "company_name": "Out Co",
    "source": "referral",
    "status": "unqualified",
}
# name, fields, activities (days ago)
LEADS = [
    ("Hot", HOT, [1, 3, 5]),
    ("Warm", WARM, [40]),
    ("Cold", {"source": "cold_call"}, []),
    ("Out", OUT, [1]),
]


def _scored_leads(db_session: Session, world: World) -> dict[str, uuid.UUID]:
    agent = world.users["alpha.agent1"]
    ids = {}
    for name, fields, activity_days in LEADS:
        lead = Lead(tenant_id=agent.tenant_id, last_name=name, owner_id=agent.id, **fields)
        db_session.add(lead)
        db_session.flush()
        ids[name] = lead.id
        for days in activity_days:
            db_session.add(
                LeadActivity(
                    tenant_id=agent.tenant_id,
                    lead_id=lead.id,
                    kind="call",
                    subject="Call",
                    actor_user_id=agent.id,
                    occurred_at=NOW - timedelta(days=days),
                )
            )
    db_session.flush()
    return ids


def test_lead_scores_priorities_and_factors(api, auth, world, db_session) -> None:
    ids = _scored_leads(db_session, world)
    agent = auth("alpha.agent1")
    page = ok(api.get("/api/v1/leads", params={"sort": "-score"}, headers=agent))
    ranked = [(lead["last_name"], lead["score"], lead["priority"]) for lead in page["items"]]
    # Hot: 15+10+10+15+20+20+15+9 = 114 -> 100. Warm: 15+10+5+10+5-10+3 = 38. Cold: 0.
    assert ranked[:2] == [("Hot", 100, "hot"), ("Warm", 38, "cold")]
    # Cold and Out both score 0, so their order between themselves is not defined.
    assert sorted(ranked[2:]) == [("Cold", 0, "cold"), ("Out", 0, "cold")]
    hot = ok(api.get("/api/v1/leads", params={"priority": "hot"}, headers=agent))
    assert [lead["last_name"] for lead in hot["items"]] == ["Hot"]
    detail = ok(api.get(f"/api/v1/leads/{ids['Warm']}/score", headers=agent))
    assert (detail["score"], detail["priority"]) == (38, "cold")
    assert {"label": "No engagement for over 30 days", "points": -10} in detail["factors"]
    one = ok(api.get(f"/api/v1/leads/{ids['Hot']}", headers=agent))
    assert (one["score"], one["priority"]) == (100, "hot")
    assert (
        api.get(f"/api/v1/leads/{ids['Hot']}/score", headers=auth("alpha.agent2")).status_code
        == 404
    )
    assert (
        api.get("/api/v1/leads", params={"priority": "boiling"}, headers=agent).status_code == 422
    )


def test_sql_and_python_scores_agree(world, db_session) -> None:
    """The list (SQL) and the explanation (Python) must never disagree."""
    ids = _scored_leads(db_session, world)
    agent = world.users["alpha.agent1"]
    principal = Principal(
        subject=agent.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset({Role.SALES_AGENT}),
        permissions=permissions_for(frozenset({Role.SALES_AGENT})),
        user_id=agent.id,
        tenant_id=agent.tenant_id,
    )
    from app.modules.leads import repository

    sql = repository.scores(db_session, principal, list(ids.values()))
    for lead_id in ids.values():
        lead = db_session.get(Lead, lead_id)
        count, last = repository.activity_stats(db_session, lead)
        python_score, _, _ = scoring.explain(lead, count, last, datetime.now(UTC))
        assert sql[lead_id] == python_score, lead.last_name


# === Customer feedback ============================================================================


def _ticket(api: TestClient, auth: Headers, world: World, **extra: Any) -> Any:
    body = {"account_id": str(world.ids["A1"]), "subject": "Help", "description": "Please", **extra}
    return ok(api.post("/api/v1/portal/tickets", json=body, headers=auth("alpha.customer")), 201)


def test_customer_rates_a_resolved_ticket_once(api, auth, world) -> None:
    ticket = _ticket(api, auth, world)
    assert ticket["category"] == "question"
    rate = f"/api/v1/portal/tickets/{ticket['id']}/rating"
    customer = auth("alpha.customer")
    assert code_of(api.post(rate, json={"rating": 5}, headers=customer)) == (
        409,
        "ticket_not_resolved",
    )
    ok(
        api.post(
            f"/api/v1/tickets/{ticket['id']}/status",
            json={"status": "resolved"},
            headers=auth("alpha.support"),
        )
    )
    for bad in ({"rating": 0}, {"rating": 6}, {"rating": 4, "rated_at": "2020-01-01T00:00:00Z"}):
        assert api.post(rate, json=bad, headers=customer).status_code == 422
    rated = ok(api.post(rate, json={"rating": 4, "comment": "Quick and kind"}, headers=customer))
    assert (rated["satisfaction_rating"], rated["rated_at"] is not None) == (4, True)
    assert code_of(api.post(rate, json={"rating": 1}, headers=customer)) == (409, "already_rated")
    staff_view = ok(api.get(f"/api/v1/tickets/{ticket['id']}", headers=auth("alpha.support")))
    assert (staff_view["satisfaction_rating"], staff_view["satisfaction_comment"]) == (
        4,
        "Quick and kind",
    )
    # Staff can't rate on the customer's behalf; other tenants can't see the ticket.
    assert api.post(rate, json={"rating": 5}, headers=auth("alpha.support")).status_code == 403
    assert api.post(rate, json={"rating": 5}, headers=auth("beta.admin")).status_code == 403


def test_complaints_are_categorised_and_counted(api, auth, world) -> None:
    complaint = _ticket(api, auth, world, category="complaint")
    _ticket(api, auth, world, category="request")
    staff = auth("alpha.support")
    listed = ok(api.get("/api/v1/tickets", params={"category": "complaint"}, headers=staff))
    assert [t["id"] for t in listed["items"]] == [complaint["id"]]
    bad = {
        "account_id": str(world.ids["A1"]),
        "subject": "x y z",
        "description": "x",
        "category": "rant",
    }
    response = api.post("/api/v1/portal/tickets", json=bad, headers=auth("alpha.customer"))
    assert response.status_code == 422
    # Staff can re-categorise (audited) without touching the priority.
    ticket = ok(api.get(f"/api/v1/tickets/{complaint['id']}", headers=staff))
    changed = ok(api.patch(f"/api/v1/tickets/{complaint['id']}", json={"version": ticket["version"],
                 "category": "problem"}, headers=staff))  # fmt: skip
    assert (changed["category"], changed["priority"]) == ("problem", ticket["priority"])
    empty = api.patch(
        f"/api/v1/tickets/{complaint['id']}", json={"version": changed["version"]}, headers=staff
    )
    assert empty.status_code == 422

    ok(
        api.post(
            f"/api/v1/tickets/{complaint['id']}/status", json={"status": "resolved"}, headers=staff
        )
    )
    ok(
        api.post(
            f"/api/v1/portal/tickets/{complaint['id']}/rating",
            json={"rating": 2},
            headers=auth("alpha.customer"),
        )
    )
    figures = ok(api.get("/api/v1/dashboard", headers=auth("alpha.admin")))["support"]
    assert (
        figures["complaints_in_period"],
        figures["ratings_in_period"],
        figures["average_rating"],
    ) == (0, 1, 2.0)


def test_converted_deals_start_their_stage_history(api, auth, world, db_session) -> None:
    lead = ok(api.post("/api/v1/leads", json={"last_name": "Convert", "company_name": "Conv Co"},
              headers=auth("alpha.agent1")), 201)  # fmt: skip
    ok(api.post(f"/api/v1/leads/{lead['id']}/qualify", json={}, headers=auth("alpha.agent1")))
    result = ok(api.post(f"/api/v1/leads/{lead['id']}/convert",
                json={"opportunity": {"amount": "500.00", "currency": "EUR"}},
                headers=auth("alpha.agent1")), 201)  # fmt: skip
    history = ok(
        api.get(
            f"/api/v1/opportunities/{result['opportunity_id']}/stages", headers=auth("alpha.agent1")
        )
    )
    assert [(h["from_stage"], h["to_stage"], h["note"], h["changed_by_name"]) for h in history] == [
        (None, "prospecting", "Created from a converted lead", "alpha.agent1")
    ]
    assert db_session.scalar(
        select(Opportunity.stage).where(Opportunity.id == uuid.UUID(result["opportunity_id"]))
    )


def test_scores_agree_for_mid_range_leads_too(world, db_session) -> None:
    """Capped (100) and zero scores hide small differences; check leads in between."""
    agent = world.users["alpha.agent1"]
    mid = [
        {"phone": "020 7946 0000", "company_name": "Mid Co", "source": "web"},
        {"email": "m@example.test", "job_title": "Head of Sales", "source": "event"},
        {"phone": "12345678", "status": "contacted", "source": "partner"},
    ]
    ids = []
    for n, fields in enumerate(mid):
        lead = Lead(tenant_id=agent.tenant_id, last_name=f"Mid{n}", owner_id=agent.id, **fields)
        db_session.add(lead)
        db_session.flush()
        ids.append(lead.id)
    principal = Principal(
        subject=agent.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset({Role.SALES_AGENT}),
        permissions=permissions_for(frozenset({Role.SALES_AGENT})),
        user_id=agent.id,
        tenant_id=agent.tenant_id,
    )
    from app.modules.leads import repository

    sql = repository.scores(db_session, principal, ids)
    for lead_id in ids:
        lead = db_session.get(Lead, lead_id)
        count, last = repository.activity_stats(db_session, lead)
        expected, _, _ = scoring.explain(lead, count, last, datetime.now(UTC))
        assert 0 < expected < 100
        assert sql[lead_id] == expected, lead.last_name


def test_only_managers_transfer_even_inside_the_service(world, db_session) -> None:
    """Defence in depth: the endpoint already refuses agents; the rule itself does too."""
    from app.core.errors import ForbiddenError
    from app.modules.accounts.service import transfer_owner

    agent = world.users["alpha.agent1"]
    principal = Principal(
        subject=agent.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset({Role.SALES_AGENT}),
        permissions=permissions_for(frozenset({Role.SALES_AGENT})),
        user_id=agent.id,
        tenant_id=agent.tenant_id,
    )
    with pytest.raises(ForbiddenError, match="transfer customers"):
        transfer_owner(
            db_session,
            principal,
            world.ids["A1"],
            version=1,
            new_owner_id=world.users["alpha.agent2"].id,
            reason="x",
        )
