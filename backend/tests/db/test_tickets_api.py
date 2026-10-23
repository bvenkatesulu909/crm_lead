"""Support tickets - integration tests through the real API and PostgreSQL (rolled back).

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support,
              customer1 -> A1, customer2 -> A2
tenant BETA:  admin, support, customer -> B1
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.auth.rbac import Role, permissions_for
from app.core.config import Settings
from app.core.errors import ForbiddenError, NotFoundError
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.support.api import create_customer_ticket
from app.modules.support.models import Ticket
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import bind_principal, session_factory_for

PEOPLE = {
    "alpha.admin": ("alpha", "tenant_admin"),
    "alpha.manager": ("alpha", "sales_manager"),
    "alpha.agent1": ("alpha", "sales_agent"),
    "alpha.agent2": ("alpha", "sales_agent"),
    "alpha.support": ("alpha", "support_agent"),
    "alpha.customer1": ("alpha", "customer"),
    "alpha.customer2": ("alpha", "customer"),
    "beta.admin": ("beta", "tenant_admin"),
    "beta.support": ("beta", "support_agent"),
    "beta.customer": ("beta", "customer"),
}
Headers = Callable[[str], dict[str, str]]


class World:
    users: dict[str, User]
    accounts: dict[str, uuid.UUID]


@pytest.fixture
def world(committed_world: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        tenant = Tenant(slug=f"{slug}-tickets", name=f"{slug.title()} Tickets Test")
        committed_world.add(tenant)
        committed_world.flush()
        tenants[slug] = tenant.id
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
        committed_world.add(user)
        w.users[name] = user
    committed_world.flush()
    w.accounts = {}
    for key, slug, owner in [
        ("A1", "alpha", "alpha.agent1"),
        ("A2", "alpha", "alpha.agent2"),
        ("B1", "beta", "beta.admin"),
    ]:
        account = Account(
            tenant_id=tenants[slug], name=f"Tickets Account {key}", owner_id=w.users[owner].id
        )
        committed_world.add(account)
        committed_world.flush()
        w.accounts[key] = account.id
    for customer, key in [
        ("alpha.customer1", "A1"),
        ("alpha.customer2", "A2"),
        ("beta.customer", "B1"),
    ]:
        u = w.users[customer]
        committed_world.add(
            PortalAccessGrant(tenant_id=u.tenant_id, user_id=u.id, account_id=w.accounts[key])
        )
    committed_world.commit()
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


def portal_ticket(
    api: TestClient, auth: Headers, customer: str, account: uuid.UUID, **extra: Any
) -> dict[str, Any]:
    body = {
        "account_id": str(account),
        "subject": "Printer is on fire",
        "description": "Please help.",
        **extra,
    }
    response = api.post("/api/v1/portal/tickets", json=body, headers=auth(customer))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def principal_for(user: User, role: Role) -> Principal:
    return Principal(
        subject=user.idp_subject,
        issuer=TEST_ISSUER,
        user_type="customer" if role == Role.CUSTOMER else "staff",
        roles=frozenset({role}),
        permissions=permissions_for(frozenset({role})),
        user_id=user.id,
        tenant_id=user.tenant_id,
    )


# --- Customers: permitted -------------------------------------------------------------------


def test_customer_opens_ticket_for_own_account(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])

    assert ticket["number"] == 1
    assert ticket["status"] == "new"
    # Customer view: no assignee, SLA, channel or other internal fields.
    assert set(ticket) == {
        "id",
        "number",
        "account_id",
        "subject",
        "description",
        "status",
        "created_at",
        "updated_at",
        "resolved_at",
        # The customer's own category and satisfaction rating (no staff comment fields).
        "category",
        "satisfaction_rating",
        "rated_at",
    }
    staff = api.get(f"/api/v1/tickets/{ticket['id']}", headers=auth("alpha.support")).json()
    assert (staff["channel"], staff["requester_user_id"]) == (
        "portal",
        str(world.users["alpha.customer1"].id),
    )
    assert staff["sla_state"] == "on_track"


def test_ticket_numbers_count_per_tenant(api, auth, world) -> None:
    numbers = [
        portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])["number"]
        for _ in range(3)
    ]
    beta = portal_ticket(api, auth, "beta.customer", world.accounts["B1"])["number"]

    assert numbers == [1, 2, 3]
    assert beta == 1


def test_customer_sees_only_tickets_of_own_accounts(api, auth, world) -> None:
    mine = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    theirs = portal_ticket(api, auth, "alpha.customer2", world.accounts["A2"])

    listed = api.get("/api/v1/portal/tickets", headers=auth("alpha.customer1")).json()
    assert [t["id"] for t in listed] == [mine["id"]]
    assert (
        api.get(
            f"/api/v1/portal/tickets/{theirs['id']}", headers=auth("alpha.customer1")
        ).status_code
        == 404
    )


# --- Customers: forbidden ---------------------------------------------------------------------


@pytest.mark.parametrize("account", ["A2", "B1"])
def test_customer_cannot_open_ticket_for_someone_elses_account(api, auth, world, account) -> None:
    response = api.post(
        "/api/v1/portal/tickets",
        json={
            "account_id": str(world.accounts[account]),
            "subject": "Not mine",
            "description": "x",
        },
        headers=auth("alpha.customer1"),
    )

    assert response.status_code == 404


def test_customer_cannot_use_staff_ticket_api_and_staff_cannot_use_portal(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])

    assert api.get("/api/v1/tickets", headers=auth("alpha.customer1")).status_code == 403
    assert (
        api.get(f"/api/v1/tickets/{ticket['id']}", headers=auth("alpha.customer1")).status_code
        == 403
    )
    assert api.get("/api/v1/portal/tickets", headers=auth("alpha.support")).status_code == 403
    body = {"account_id": str(world.accounts["A1"]), "subject": "staff", "description": "x"}
    assert (
        api.post("/api/v1/portal/tickets", json=body, headers=auth("alpha.support")).status_code
        == 403
    )


def test_internal_notes_never_reach_the_customer(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}/comments"
    api.post(
        url,
        json={"body": "Customer is rude, escalate", "visibility": "internal"},
        headers=auth("alpha.support"),
    )
    api.post(
        url, json={"body": "We are on it.", "visibility": "public"}, headers=auth("alpha.support")
    )

    portal = api.get(
        f"/api/v1/portal/tickets/{ticket['id']}/comments", headers=auth("alpha.customer1")
    )
    staff = api.get(url, headers=auth("alpha.support")).json()

    assert [c["body"] for c in portal.json()] == ["We are on it."]
    assert "escalate" not in portal.text
    assert set(portal.json()[0]) == {"id", "body", "author_name", "author_type", "created_at"}
    assert [c["visibility"] for c in staff] == ["internal", "public"]


def test_customer_request_body_cannot_set_internal_fields(api, auth, world) -> None:
    for extra in (
        {"priority": "urgent"},
        {"assignee_id": str(world.users["alpha.support"].id)},
        {"channel": "staff"},
    ):
        body = {
            "account_id": str(world.accounts["A1"]),
            "subject": "Sneaky",
            "description": "x",
            **extra,
        }
        assert (
            api.post(
                "/api/v1/portal/tickets", json=body, headers=auth("alpha.customer1")
            ).status_code
            == 422
        )
    reply = {"body": "hi", "visibility": "internal"}
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    response = api.post(
        f"/api/v1/portal/tickets/{ticket['id']}/comments",
        json=reply,
        headers=auth("alpha.customer1"),
    )
    assert response.status_code == 422


# --- Staff scope ------------------------------------------------------------------------------


def test_staff_visibility_by_role_and_tenant(api, auth, world) -> None:
    t1 = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])["id"]
    t2 = portal_ticket(api, auth, "alpha.customer2", world.accounts["A2"])["id"]
    portal_ticket(api, auth, "beta.customer", world.accounts["B1"])

    def visible(user: str) -> set[str]:
        page = api.get("/api/v1/tickets", headers=auth(user)).json()
        assert page["total"] == len(page["items"])
        return {t["id"] for t in page["items"]}

    assert visible("alpha.support") == {t1, t2}
    assert visible("alpha.manager") == {t1, t2}
    assert visible("alpha.agent1") == {t1}  # only tickets on the agent's own account
    assert api.get(f"/api/v1/tickets/{t1}", headers=auth("beta.support")).status_code == 404


def test_read_only_roles_cannot_change_tickets(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}"

    for user in ("alpha.manager", "alpha.agent1"):
        assert (
            api.post(f"{url}/status", json={"status": "open"}, headers=auth(user)).status_code
            == 403
        )
        reply = {"body": "x", "visibility": "public"}
        assert api.post(f"{url}/comments", json=reply, headers=auth(user)).status_code == 403


def test_other_tenant_support_cannot_touch_ticket(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}"

    assert (
        api.post(f"{url}/status", json={"status": "open"}, headers=auth("beta.support")).status_code
        == 404
    )
    assign = {"assignee_id": str(world.users["beta.support"].id)}
    assert api.post(f"{url}/assign", json=assign, headers=auth("beta.support")).status_code == 404


# --- Workflow, SLA, assignment ----------------------------------------------------------------


def test_first_public_reply_opens_ticket_and_records_first_response(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}"

    api.post(
        f"{url}/comments",
        json={"body": "note", "visibility": "internal"},
        headers=auth("alpha.support"),
    )
    assert api.get(url, headers=auth("alpha.support")).json()["first_responded_at"] is None
    api.post(
        f"{url}/comments",
        json={"body": "Hello!", "visibility": "public"},
        headers=auth("alpha.support"),
    )

    after = api.get(url, headers=auth("alpha.support")).json()
    assert after["status"] == "open"
    assert after["first_responded_at"] is not None


@pytest.mark.parametrize("waiting_status", ["pending_customer", "resolved"])
def test_customer_reply_reopens_ticket(api, auth, world, waiting_status) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    api.post(
        f"/api/v1/tickets/{ticket['id']}/status",
        json={"status": waiting_status},
        headers=auth("alpha.support"),
    )

    reply = api.post(
        f"/api/v1/portal/tickets/{ticket['id']}/comments",
        json={"body": "Still broken"},
        headers=auth("alpha.customer1"),
    )

    assert reply.status_code == 201
    assert (
        api.get(f"/api/v1/portal/tickets/{ticket['id']}", headers=auth("alpha.customer1")).json()[
            "status"
        ]
        == "open"
    )


def test_closed_tickets_are_final(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}"
    assert (
        api.post(
            f"{url}/status",
            json={"status": "closed", "reason": "Duplicate"},
            headers=auth("alpha.support"),
        ).status_code
        == 200
    )

    again = api.post(f"{url}/status", json={"status": "open"}, headers=auth("alpha.support"))
    reply = api.post(
        f"/api/v1/portal/tickets/{ticket['id']}/comments",
        json={"body": "?"},
        headers=auth("alpha.customer1"),
    )

    assert again.status_code == reply.status_code == 409
    assert again.json()["code"] == reply.json()["code"] == "ticket_closed"


def test_invalid_transition_is_rejected(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}/status"
    api.post(url, json={"status": "resolved"}, headers=auth("alpha.support"))

    response = api.post(url, json={"status": "pending_customer"}, headers=auth("alpha.support"))

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_status_transition"


def test_tickets_go_only_to_support_staff_of_the_tenant(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}/assign"

    ok = api.post(
        url, json={"assignee_id": str(world.users["alpha.support"].id)}, headers=auth("alpha.admin")
    )
    assert ok.status_code == 200
    assert ok.json()["assignee_user_id"] == str(world.users["alpha.support"].id)
    for bad in ("alpha.agent1", "alpha.customer1", "beta.support"):
        response = api.post(
            url, json={"assignee_id": str(world.users[bad].id)}, headers=auth("alpha.admin")
        )
        assert response.status_code == 422, bad
        assert response.json()["code"] == "invalid_assignee"


def test_priority_change_recalculates_sla_and_checks_version(api, auth, world) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}"
    before = api.get(url, headers=auth("alpha.support")).json()

    urgent = api.patch(
        url,
        json={"version": before["version"], "priority": "urgent"},
        headers=auth("alpha.support"),
    ).json()
    stale = api.patch(
        url, json={"version": before["version"], "priority": "low"}, headers=auth("alpha.support")
    )

    assert urgent["resolution_due_at"] < before["resolution_due_at"]
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"


def test_overdue_filter_and_breached_state(api, auth, world, db_session) -> None:
    late = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"], subject="Fresh one")
    ticket = db_session.get(Ticket, uuid.UUID(late["id"]))
    ticket.first_response_due_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.flush()

    page = api.get("/api/v1/tickets?overdue=true", headers=auth("alpha.support")).json()

    assert [t["id"] for t in page["items"]] == [late["id"]]
    assert page["items"][0]["sla_state"] == "breached"


def test_search_by_number_and_subject(api, auth, world) -> None:
    portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"], subject="Login page broken")
    second = portal_ticket(
        api, auth, "alpha.customer1", world.accounts["A1"], subject="Invoice question"
    )

    by_number = api.get("/api/v1/tickets?q=T-2", headers=auth("alpha.support")).json()
    by_text = api.get("/api/v1/tickets?q=LOGIN", headers=auth("alpha.support")).json()

    assert [t["id"] for t in by_number["items"]] == [second["id"]]
    assert [t["subject"] for t in by_text["items"]] == ["Login page broken"]


def test_changes_are_audited(api, auth, world, db_session) -> None:
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    url = f"/api/v1/tickets/{ticket['id']}"
    api.post(
        f"{url}/assign",
        json={"assignee_id": str(world.users["alpha.support"].id)},
        headers=auth("alpha.support"),
    )
    api.post(f"{url}/status", json={"status": "resolved"}, headers=auth("alpha.support"))

    actions = db_session.scalars(
        select(AuditLog.action)
        .where(AuditLog.entity_id == uuid.UUID(ticket["id"]))
        .order_by(AuditLog.seq)
    ).all()
    assert actions == ["ticket.created", "ticket.assigned", "ticket.status_changed"]


@pytest.mark.parametrize(
    "statement", ["UPDATE ticket_comments SET body = 'x'", "DELETE FROM ticket_comments"]
)
def test_comments_are_append_only(app_engine, statement) -> None:
    with (
        app_engine.connect() as connection,
        pytest.raises(ProgrammingError, match="permission denied"),
    ):
        connection.execute(text(statement))


# --- Human handoff (used by the AI assistant later) --------------------------------------------


def test_assistant_handoff_creates_ticket_as_the_customer(world, db_session, api, auth) -> None:
    customer = principal_for(world.users["alpha.customer1"], Role.CUSTOMER)
    bind_principal(db_session, customer)  # the assistant runs inside the customer's request

    ticket = create_customer_ticket(
        db_session,
        customer,
        account_id=world.accounts["A1"],
        subject="Assistant handoff: refund question",
        description="Conversation summary: a refund question the assistant may not decide.",
        channel="assistant",
    )
    db_session.flush()

    staff = api.get(f"/api/v1/tickets/{ticket.id}", headers=auth("alpha.support")).json()
    assert staff["channel"] == "assistant"
    assert staff["requester_user_id"] == str(world.users["alpha.customer1"].id)
    mine = api.get("/api/v1/portal/tickets", headers=auth("alpha.customer1")).json()
    assert [t["id"] for t in mine] == [str(ticket.id)]


@pytest.mark.parametrize("account", ["A2", "B1"])
def test_assistant_handoff_cannot_target_another_customers_account(
    world, db_session, account
) -> None:
    customer = principal_for(world.users["alpha.customer1"], Role.CUSTOMER)

    with pytest.raises(NotFoundError):
        create_customer_ticket(
            db_session,
            customer,
            account_id=world.accounts[account],
            subject="Probe",
            description="x",
            channel="assistant",
        )


def test_assistant_handoff_only_acts_for_customers(world, db_session) -> None:
    staff = principal_for(world.users["alpha.support"], Role.SUPPORT_AGENT)

    with pytest.raises(ForbiddenError):
        create_customer_ticket(
            db_session,
            staff,
            account_id=world.accounts["A1"],
            subject="x",
            description="x",
            channel="assistant",
        )
