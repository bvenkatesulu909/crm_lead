"""Lead Management API - integration tests (real API + real PostgreSQL, rolled back per test).

tenant ALPHA: admin (tenant_admin), manager (sales_manager), agent1, agent2 (sales_agent),
              support (support_agent), inactive (sales_agent, disabled), customer (customer)
tenant BETA:  admin (tenant_admin), agent (sales_agent)
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.orm import Session

import app.modules.sales.api as sales_api
from app.core.audit import AuditLog
from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.contacts.models import Contact
from app.modules.identity.models import Tenant, User
from app.modules.leads.models import Lead
from app.modules.sales.models import Opportunity
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for

PEOPLE = {
    "alpha.admin": ("alpha", "staff", "tenant_admin"),
    "alpha.manager": ("alpha", "staff", "sales_manager"),
    "alpha.agent1": ("alpha", "staff", "sales_agent"),
    "alpha.agent2": ("alpha", "staff", "sales_agent"),
    "alpha.support": ("alpha", "staff", "support_agent"),
    "alpha.inactive": ("alpha", "staff", "sales_agent"),
    "alpha.customer": ("alpha", "customer", "customer"),
    "beta.admin": ("beta", "staff", "tenant_admin"),
    "beta.agent": ("beta", "staff", "sales_agent"),
}

Headers = Callable[[str], dict[str, str]]


@pytest.fixture
def people(db_session: Session) -> dict[str, User]:
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        tenant = Tenant(slug=f"{slug}-leads", name=f"{slug} leads test")
        db_session.add(tenant)
        db_session.flush()
        tenants[slug] = tenant.id
    users: dict[str, User] = {}
    for name, (tenant_slug, user_type, role) in PEOPLE.items():
        user = User(
            tenant_id=tenants[tenant_slug],
            idp_issuer=TEST_ISSUER,
            idp_subject=f"sub-{name}",
            email=f"{name}@example.test",
            display_name=name,
            user_type=user_type,
            roles=[role],
            is_active=name != "alpha.inactive",
        )
        db_session.add(user)
        users[name] = user
    db_session.flush()
    return users


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
def auth(token_factory: TokenFactory, people: dict[str, User]) -> Headers:
    def headers(name: str) -> dict[str, str]:
        return bearer(token_factory.mint(f"sub-{name}", [PEOPLE[name][2]]))

    return headers


def create(api: TestClient, auth: Headers, user: str, **fields: Any) -> dict[str, Any]:
    response = api.post(
        "/api/v1/leads", json={"last_name": "Prospect", **fields}, headers=auth(user)
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def qualified_lead(api: TestClient, auth: Headers, user: str, **fields: Any) -> dict[str, Any]:
    lead = create(api, auth, user, **fields)
    response = api.post(f"/api/v1/leads/{lead['id']}/qualify", json={}, headers=auth(user))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def audit_rows(session: Session, lead_id: str) -> list[AuditLog]:
    return list(
        session.scalars(
            select(AuditLog).where(AuditLog.entity_id == uuid.UUID(lead_id)).order_by(AuditLog.seq)
        )
    )


def count(session: Session, model: Any, tenant_id: uuid.UUID) -> int:
    statement = select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
    return session.scalar(statement) or 0


# --- Create -----------------------------------------------------------------------------


def test_agent_creates_lead_and_becomes_owner(api, auth, people, db_session) -> None:
    response = api.post(
        "/api/v1/leads",
        json={"first_name": "Jamie", "last_name": "Example", "email": "Jamie@Example.TEST"},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 201
    lead = response.json()
    assert response.headers["location"] == f"/api/v1/leads/{lead['id']}"
    assert lead["owner_id"] == str(people["alpha.agent1"].id)
    assert lead["status"] == "new"
    assert lead["email"] == "Jamie@example.test"
    assert lead["version"] == 1
    db_lead = db_session.get(Lead, uuid.UUID(lead["id"]))
    assert db_lead.tenant_id == people["alpha.agent1"].tenant_id  # tenant from the token's user
    assert [row.action for row in audit_rows(db_session, lead["id"])] == ["lead.created"]


def test_client_cannot_choose_tenant_or_status(api, auth) -> None:
    for extra in ({"tenant_id": str(uuid.uuid4())}, {"status": "qualified"}, {"version": 7}):
        response = api.post(
            "/api/v1/leads", json={"last_name": "X", **extra}, headers=auth("alpha.agent1")
        )
        assert response.status_code == 422


def test_invalid_input_returns_problem_details_with_field_errors(api, auth) -> None:
    response = api.post(
        "/api/v1/leads", json={"last_name": "X", "email": "nope"}, headers=auth("alpha.agent1")
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["errors"][0]["location"] == ["body", "email"]


def test_agent_cannot_create_lead_for_someone_else(api, auth, people) -> None:
    response = api.post(
        "/api/v1/leads",
        json={"last_name": "X", "owner_id": str(people["alpha.agent2"].id)},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 403


def test_manager_can_create_lead_for_an_agent(api, auth, people) -> None:
    lead = create(api, auth, "alpha.manager", owner_id=str(people["alpha.agent2"].id))

    assert lead["owner_id"] == str(people["alpha.agent2"].id)


@pytest.mark.parametrize(
    "assignee", ["alpha.support", "alpha.customer", "alpha.inactive", "beta.agent", "alpha.admin"]
)
def test_leads_can_only_go_to_active_sales_staff_of_same_tenant(
    api, auth, people, assignee
) -> None:
    response = api.post(
        "/api/v1/leads",
        json={"last_name": "X", "owner_id": str(people[assignee].id)},
        headers=auth("alpha.manager"),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_assignee"


def test_tenant_admin_lead_starts_unassigned(api, auth) -> None:
    assert create(api, auth, "alpha.admin")["owner_id"] is None


@pytest.mark.parametrize("user", ["alpha.support", "alpha.customer"])
def test_support_and_customers_have_no_lead_access(api, auth, user) -> None:
    assert api.get("/api/v1/leads", headers=auth(user)).status_code == 403
    response = api.post("/api/v1/leads", json={"last_name": "X"}, headers=auth(user))
    assert response.status_code == 403


def test_no_token_means_401(api) -> None:
    assert api.get("/api/v1/leads").status_code == 401


# --- Read, list, search, filter, paginate -----------------------------------------------


def test_visibility_by_role_and_tenant(api, auth) -> None:
    mine = create(api, auth, "alpha.agent1", last_name="Agent1Lead")
    theirs = create(api, auth, "alpha.agent2", last_name="Agent2Lead")
    beta = create(api, auth, "beta.agent", last_name="BetaLead")

    def visible(user: str) -> set[str]:
        page = api.get("/api/v1/leads", headers=auth(user)).json()
        assert page["total"] == len(page["items"])
        return {lead["id"] for lead in page["items"]}

    assert visible("alpha.agent1") == {mine["id"]}
    assert visible("alpha.agent2") == {theirs["id"]}
    assert visible("alpha.manager") == {mine["id"], theirs["id"]}
    assert visible("alpha.admin") == {mine["id"], theirs["id"]}
    assert visible("beta.admin") == {beta["id"]}


@pytest.mark.parametrize("user", ["alpha.agent2", "beta.admin", "beta.agent"])
def test_other_peoples_and_other_tenants_leads_are_404(api, auth, user) -> None:
    lead = create(api, auth, "alpha.agent1")

    for path in ("", "/activities", "/assignments"):
        assert api.get(f"/api/v1/leads/{lead['id']}{path}", headers=auth(user)).status_code == 404
    patch = api.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": 1, "last_name": "Hacked"},
        headers=auth(user),
    )
    assert patch.status_code == 404


def test_cross_tenant_admin_cannot_touch_lead_by_id(api, auth, people) -> None:
    lead = qualified_lead(api, auth, "alpha.manager")
    lead_url = f"/api/v1/leads/{lead['id']}"
    beta = auth("beta.admin")

    assert api.post(f"{lead_url}/convert", json={}, headers=beta).status_code == 404
    assign = api.post(
        f"{lead_url}/assign", json={"owner_id": str(people["beta.agent"].id)}, headers=beta
    )
    assert assign.status_code == 404
    status = api.post(f"{lead_url}/status", json={"status": "contacted"}, headers=beta)
    assert status.status_code == 404


def test_search_filter_sort_and_paginate(api, auth, people) -> None:
    create(
        api, auth, "alpha.manager", last_name="Alvarez", company_name="Acme Robotics", source="web"
    )
    create(
        api, auth, "alpha.manager", last_name="Brown", email="b@globex.example.test", source="event"
    )
    create(api, auth, "alpha.manager", last_name="Chen", company_name="100% Solar", source="web")
    headers = auth("alpha.manager")

    def names(query: str) -> list[str]:
        return [
            lead["last_name"]
            for lead in api.get(f"/api/v1/leads?{query}", headers=headers).json()["items"]
        ]

    assert names("q=acme") == ["Alvarez"]  # company, case-insensitive
    assert names("q=GLOBEX") == ["Brown"]  # e-mail
    assert names("q=100%25") == ["Chen"]  # '%' is literal, not a wildcard
    assert names("q=%25") == ["Chen"]
    assert names("source=web&sort=last_name") == ["Alvarez", "Chen"]
    assert names("sort=-last_name") == ["Chen", "Brown", "Alvarez"]
    page = api.get("/api/v1/leads?sort=last_name&limit=2&offset=2", headers=headers).json()
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 2)
    assert [lead["last_name"] for lead in page["items"]] == ["Chen"]
    assert names(f"owner_id={people['alpha.manager'].id}&status=new&sort=last_name") == [
        "Alvarez",
        "Brown",
        "Chen",
    ]


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=201", "offset=-1", "status=bogus", "sort=password", "q="]
)
def test_invalid_list_parameters_return_422(api, auth, query) -> None:
    assert api.get(f"/api/v1/leads?{query}", headers=auth("alpha.manager")).status_code == 422


# --- Update -----------------------------------------------------------------------------


def test_update_with_current_version_succeeds_and_is_audited(api, auth, db_session) -> None:
    lead = create(api, auth, "alpha.agent1", phone="+1 555 0100")

    response = api.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": 1, "phone": "+1 555 0199", "job_title": "CTO"},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    update = [row for row in audit_rows(db_session, lead["id"]) if row.action == "lead.updated"]
    assert update[0].changes == {
        "phone": {"old": "+1 555 0100", "new": "+1 555 0199"},
        "job_title": {"old": None, "new": "CTO"},
    }


def test_stale_version_is_rejected_with_409(api, auth) -> None:
    lead = create(api, auth, "alpha.agent1")
    url = f"/api/v1/leads/{lead['id']}"
    api.patch(url, json={"version": 1, "last_name": "First"}, headers=auth("alpha.agent1"))

    response = api.patch(
        url, json={"version": 1, "last_name": "Second"}, headers=auth("alpha.agent1")
    )

    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"


# --- Assignment -------------------------------------------------------------------------


def test_manager_reassigns_lead_with_history_and_audit(api, auth, people, db_session) -> None:
    lead = create(api, auth, "alpha.agent1")
    url = f"/api/v1/leads/{lead['id']}"

    response = api.post(
        f"{url}/assign",
        json={"owner_id": str(people["alpha.agent2"].id), "reason": "Territory change"},
        headers=auth("alpha.manager"),
    )

    assert response.status_code == 200
    assert api.get(url, headers=auth("alpha.agent1")).status_code == 404  # lost access
    assert api.get(url, headers=auth("alpha.agent2")).status_code == 200  # gained access
    history = api.get(f"{url}/assignments", headers=auth("alpha.manager")).json()
    assert [(h["from_user_id"], h["to_user_id"], h["reason"]) for h in history] == [
        (str(people["alpha.agent1"].id), str(people["alpha.agent2"].id), "Territory change"),
        (None, str(people["alpha.agent1"].id), "Initial owner"),
    ]
    assert history[0]["assigned_by_user_id"] == str(people["alpha.manager"].id)
    assert "lead.assigned" in [row.action for row in audit_rows(db_session, lead["id"])]


def test_agent_cannot_reassign_own_lead(api, auth, people) -> None:
    lead = create(api, auth, "alpha.agent1")

    response = api.post(
        f"/api/v1/leads/{lead['id']}/assign",
        json={"owner_id": str(people["alpha.agent2"].id)},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 403


def test_assigning_to_current_owner_is_a_conflict(api, auth, people) -> None:
    lead = create(api, auth, "alpha.agent1")

    response = api.post(
        f"/api/v1/leads/{lead['id']}/assign",
        json={"owner_id": str(people["alpha.agent1"].id)},
        headers=auth("alpha.manager"),
    )

    assert response.status_code == 409


# --- Status changes ---------------------------------------------------------------------


def test_status_flow_is_recorded_on_the_timeline(api, auth, db_session) -> None:
    lead = create(api, auth, "alpha.agent1")
    url = f"/api/v1/leads/{lead['id']}"
    headers = auth("alpha.agent1")

    assert (
        api.post(f"{url}/status", json={"status": "contacted"}, headers=headers).status_code == 200
    )
    disqualified = api.post(f"{url}/disqualify", json={"reason": "No budget"}, headers=headers)
    assert disqualified.json()["status"] == "unqualified"
    reopened = api.post(f"{url}/status", json={"status": "contacted"}, headers=headers)
    assert reopened.json()["status"] == "contacted"
    assert api.post(f"{url}/qualify", json={}, headers=headers).json()["status"] == "qualified"

    timeline = api.get(f"{url}/activities", headers=headers).json()
    changes = [a["subject"] for a in timeline if a["kind"] == "status_changed"]
    assert changes == [
        "Status changed from contacted to qualified",
        "Status changed from unqualified to contacted",
        "Status changed from contacted to unqualified",
        "Status changed from new to contacted",
    ]
    assert any(a["body"] == "No budget" for a in timeline)
    actions = [row.action for row in audit_rows(db_session, lead["id"])]
    assert actions.count("lead.status_changed") == 4


@pytest.mark.parametrize(
    ("setup", "endpoint", "body"),
    [
        ([], "status", {"status": "qualified"}),  # allowed from new - control case below
        (["disqualify"], "qualify", {}),  # unqualified -> qualified: not allowed
        (["qualify"], "qualify", {}),  # qualified -> qualified: not a transition
        (["disqualify"], "disqualify", {"reason": "again"}),
    ],
)
def test_invalid_transitions_return_409(api, auth, setup, endpoint, body) -> None:
    lead = create(api, auth, "alpha.agent1")
    url = f"/api/v1/leads/{lead['id']}"
    headers = auth("alpha.agent1")
    for step in setup:
        payload = {"reason": "setup"} if step == "disqualify" else {}
        assert api.post(f"{url}/{step}", json=payload, headers=headers).status_code == 200

    response = api.post(f"{url}/{endpoint}", json=body, headers=headers)

    if not setup:
        assert response.status_code == 200
    else:
        assert response.status_code == 409
        assert response.json()["code"] == "invalid_status_transition"


def test_status_endpoint_cannot_set_converted(api, auth) -> None:
    lead = qualified_lead(api, auth, "alpha.agent1")

    response = api.post(
        f"/api/v1/leads/{lead['id']}/status",
        json={"status": "converted"},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 422


# --- Conversion -------------------------------------------------------------------------


def test_conversion_creates_account_contact_and_opportunity(api, auth, people, db_session) -> None:
    lead = qualified_lead(
        api, auth, "alpha.agent1", first_name="Jamie", company_name="Example Industries",
        email="jamie@example.test",
    )  # fmt: skip

    response = api.post(
        f"/api/v1/leads/{lead['id']}/convert",
        json={"opportunity": {"amount": "25000.00", "currency": "EUR"}},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 201
    result = response.json()
    assert result["already_converted"] is False
    agent = people["alpha.agent1"]
    account = db_session.get(Account, uuid.UUID(result["account_id"]))
    contact = db_session.get(Contact, uuid.UUID(result["contact_id"]))
    opportunity = db_session.get(Opportunity, uuid.UUID(result["opportunity_id"]))
    assert (account.name, account.tenant_id, account.owner_id) == (
        "Example Industries", agent.tenant_id, agent.id,
    )  # fmt: skip
    assert (contact.first_name, contact.email, contact.account_id) == (
        "Jamie", "jamie@example.test", account.id,
    )  # fmt: skip
    assert (opportunity.account_id, opportunity.primary_contact_id, str(opportunity.amount)) == (
        account.id, contact.id, "25000.00",
    )  # fmt: skip
    converted = api.get(f"/api/v1/leads/{lead['id']}", headers=auth("alpha.agent1")).json()
    assert converted["status"] == "converted"
    assert converted["converted_opportunity_id"] == result["opportunity_id"]
    assert "lead.converted" in [row.action for row in audit_rows(db_session, lead["id"])]


def test_conversion_is_idempotent(api, auth, people, db_session) -> None:
    lead = qualified_lead(api, auth, "alpha.agent1", company_name="Once Only Ltd")
    url = f"/api/v1/leads/{lead['id']}/convert"
    tenant = people["alpha.agent1"].tenant_id

    first = api.post(url, json={}, headers=auth("alpha.agent1"))
    counts = (count(db_session, Account, tenant), count(db_session, Contact, tenant))
    second = api.post(url, json={}, headers=auth("alpha.agent1"))
    third = api.post(url, json={"account": {"name": "Different"}}, headers=auth("alpha.manager"))

    assert first.status_code == 201
    assert second.status_code == third.status_code == 200
    assert second.json()["already_converted"] is True
    for key in ("account_id", "contact_id", "opportunity_id", "converted_at"):
        assert first.json()[key] == second.json()[key] == third.json()[key]
    assert (count(db_session, Account, tenant), count(db_session, Contact, tenant)) == counts
    actions = [row.action for row in audit_rows(db_session, lead["id"])]
    assert actions.count("lead.converted") == 1


def test_only_qualified_leads_can_be_converted(api, auth) -> None:
    lead = create(api, auth, "alpha.agent1")

    response = api.post(
        f"/api/v1/leads/{lead['id']}/convert", json={}, headers=auth("alpha.agent1")
    )

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_status_transition"


def test_converted_lead_is_read_only(api, auth, people) -> None:
    lead = qualified_lead(api, auth, "alpha.manager")
    url = f"/api/v1/leads/{lead['id']}"
    headers = auth("alpha.manager")
    api.post(f"{url}/convert", json={}, headers=headers)

    attempts = [
        api.patch(url, json={"version": 3, "last_name": "Changed"}, headers=headers),
        api.post(f"{url}/status", json={"status": "contacted"}, headers=headers),
        api.post(f"{url}/disqualify", json={"reason": "late"}, headers=headers),
        api.post(
            f"{url}/assign", json={"owner_id": str(people["alpha.agent2"].id)}, headers=headers
        ),
    ]
    for response in attempts:
        assert response.status_code == 409
        assert response.json()["code"] == "lead_converted"


def test_conversion_can_link_an_existing_visible_account(api, auth, people, db_session) -> None:
    agent = people["alpha.agent1"]
    existing = Account(tenant_id=agent.tenant_id, name="Existing Customer", owner_id=agent.id)
    db_session.add(existing)
    db_session.flush()
    lead = qualified_lead(api, auth, "alpha.agent1")
    before = count(db_session, Account, agent.tenant_id)

    response = api.post(
        f"/api/v1/leads/{lead['id']}/convert",
        json={"account": {"existing_account_id": str(existing.id)}},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 201
    assert response.json()["account_id"] == str(existing.id)
    assert count(db_session, Account, agent.tenant_id) == before


@pytest.mark.parametrize("owner", ["beta.agent", "alpha.agent2"])
def test_conversion_cannot_link_an_account_you_cannot_see(
    api, auth, people, db_session, owner
) -> None:
    other = people[owner]
    hidden = Account(tenant_id=other.tenant_id, name="Not yours", owner_id=other.id)
    db_session.add(hidden)
    db_session.flush()
    lead = qualified_lead(api, auth, "alpha.agent1")
    tenant = people["alpha.agent1"].tenant_id
    before = (count(db_session, Contact, tenant), count(db_session, Opportunity, tenant))

    response = api.post(
        f"/api/v1/leads/{lead['id']}/convert",
        json={
            "account": {"existing_account_id": str(hidden.id)},
            "opportunity": {"currency": "EUR"},
        },
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 404
    assert (count(db_session, Contact, tenant), count(db_session, Opportunity, tenant)) == before
    assert (
        api.get(f"/api/v1/leads/{lead['id']}", headers=auth("alpha.agent1")).json()["status"]
        == "qualified"
    )


def test_conversion_is_atomic_when_a_step_fails(api, auth, people, db_session, monkeypatch) -> None:
    lead = qualified_lead(api, auth, "alpha.agent1", company_name="Half Done Ltd")
    tenant = people["alpha.agent1"].tenant_id
    before = (count(db_session, Account, tenant), count(db_session, Contact, tenant))

    def failing_create_opportunity(*args: Any, **kwargs: Any) -> uuid.UUID:
        raise RuntimeError("simulated failure after account and contact were inserted")

    monkeypatch.setattr(sales_api, "create_opportunity", failing_create_opportunity)
    response = api.post(
        f"/api/v1/leads/{lead['id']}/convert",
        json={"opportunity": {"currency": "EUR"}},
        headers=auth("alpha.agent1"),
    )

    assert response.status_code == 500
    assert "simulated" not in response.text
    # Nothing from the failed attempt survived: no account, no contact, lead unchanged.
    assert (count(db_session, Account, tenant), count(db_session, Contact, tenant)) == before
    lead_now = api.get(f"/api/v1/leads/{lead['id']}", headers=auth("alpha.agent1")).json()
    assert lead_now["status"] == "qualified"
    assert lead_now["converted_account_id"] is None


# --- Activities -------------------------------------------------------------------------


def test_record_and_list_activities(api, auth, people) -> None:
    lead = create(api, auth, "alpha.agent1")
    url = f"/api/v1/leads/{lead['id']}/activities"

    response = api.post(
        url,
        json={"kind": "call", "subject": "Intro call", "body": "Interested in a demo",
              "occurred_at": "2026-10-17T09:30:00+02:00"},
        headers=auth("alpha.agent1"),
    )  # fmt: skip

    assert response.status_code == 201
    assert response.json()["actor_user_id"] == str(people["alpha.agent1"].id)
    kinds = [a["kind"] for a in api.get(url, headers=auth("alpha.manager")).json()]
    assert sorted(kinds) == ["assigned", "call", "created"]


def test_activities_are_private_to_authorized_users(api, auth) -> None:
    lead = create(api, auth, "alpha.agent1")
    url = f"/api/v1/leads/{lead['id']}/activities"
    note = {"kind": "note", "subject": "x"}

    assert api.post(url, json=note, headers=auth("alpha.agent2")).status_code == 404
    assert api.post(url, json=note, headers=auth("alpha.customer")).status_code == 403
    assert api.get(url, headers=auth("beta.admin")).status_code == 404


# --- Audit log is append-only -----------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "UPDATE lead_assignments SET reason = 'tampered'",
        "DELETE FROM lead_assignments",
    ],
)
def test_app_role_cannot_rewrite_history(app_engine, statement) -> None:
    from sqlalchemy.exc import ProgrammingError

    with (
        app_engine.connect() as connection,
        pytest.raises(ProgrammingError, match="permission denied"),
    ):
        connection.execute(text(statement))


# --- Colleague directory (used by the web app for owner names and assignment) -----------


def test_directory_lists_active_staff_of_own_tenant_only(api, auth, people) -> None:
    response = api.get("/api/v1/users", headers=auth("alpha.agent1"))

    assert response.status_code == 200
    names = {u["display_name"]: u["assignable"] for u in response.json()}
    assert names == {
        "alpha.admin": False,
        "alpha.manager": True,
        "alpha.agent1": True,
        "alpha.agent2": True,
        "alpha.support": False,
    }  # no inactive user, no customer, no beta user
    assert set(response.json()[0]) == {"id", "display_name", "assignable", "support"}  # names only


def test_directory_assignable_filter(api, auth) -> None:
    response = api.get("/api/v1/users?assignable=true", headers=auth("alpha.manager"))

    assert [u["display_name"] for u in response.json()] == [
        "alpha.agent1",
        "alpha.agent2",
        "alpha.manager",
    ]


def test_customers_cannot_see_the_directory(api, auth) -> None:
    assert api.get("/api/v1/users", headers=auth("alpha.customer")).status_code == 403


def test_leads_can_be_filtered_by_converted_account(api, auth) -> None:
    lead = qualified_lead(api, auth, "alpha.manager", company_name="History Ltd")
    other = create(api, auth, "alpha.manager")
    result = api.post(f"/api/v1/leads/{lead['id']}/convert", json={}, headers=auth("alpha.manager"))
    account_id = result.json()["account_id"]

    page = api.get(f"/api/v1/leads?account_id={account_id}", headers=auth("alpha.manager")).json()

    assert [item["id"] for item in page["items"]] == [lead["id"]]
    assert other["id"] not in [item["id"] for item in page["items"]]
    # Another tenant filtering by this account sees nothing.
    beta = api.get(f"/api/v1/leads?account_id={account_id}", headers=auth("beta.admin")).json()
    assert beta["total"] == 0


def test_directory_support_filter(api, auth) -> None:
    response = api.get("/api/v1/users?support=true", headers=auth("alpha.agent1"))

    assert [u["display_name"] for u in response.json()] == ["alpha.admin", "alpha.support"]
    assert all(u["support"] for u in response.json())
