"""Phase D - opportunity pipeline and activities/tasks, through the real API and PostgreSQL
(rolled back after each test).

tenant ALPHA: admin, manager, agent1 (owns A1, lead L1, contact C1 on A1), agent2 (owns A2,
              lead L2, contact C2 on A2), support, customer -> A1
tenant BETA:  admin, agent (owns B1)
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.contacts.models import Contact
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.leads.models import Lead
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
OPPS = "/api/v1/opportunities"
ACTS = "/api/v1/activities"
NOW = datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.isoformat()


class World:
    users: dict[str, User]
    ids: dict[str, uuid.UUID]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        new_tenant = Tenant(slug=f"{slug}-pipeline", name=f"{slug.title()} Pipeline Test")
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
    for key, owner in [("A1", "alpha.agent1"), ("A2", "alpha.agent2"), ("B1", "beta.agent")]:
        user = w.users[owner]
        account = Account(tenant_id=user.tenant_id, name=f"Pipe {key}", owner_id=user.id)
        db_session.add(account)
        db_session.flush()
        w.ids[key] = account.id
    for key, owner, account_key in [("C1", "alpha.agent1", "A1"), ("C2", "alpha.agent2", "A2")]:
        user = w.users[owner]
        contact = Contact(
            tenant_id=user.tenant_id,
            last_name=f"Contact {key}",
            account_id=w.ids[account_key],
            owner_id=user.id,
        )
        db_session.add(contact)
        db_session.flush()
        w.ids[key] = contact.id
    for key, owner in [("L1", "alpha.agent1"), ("L2", "alpha.agent2")]:
        user = w.users[owner]
        lead = Lead(tenant_id=user.tenant_id, last_name=f"Lead {key}", owner_id=user.id)
        db_session.add(lead)
        db_session.flush()
        w.ids[key] = lead.id
    customer = w.users["alpha.customer"]
    db_session.add(
        PortalAccessGrant(tenant_id=customer.tenant_id, user_id=customer.id, account_id=w.ids["A1"])
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


def new_opp(api: TestClient, auth: Headers, user: str, account: uuid.UUID, **fields: Any) -> Any:
    body = {"name": "Deal", "account_id": str(account), **fields}
    return ok(api.post(OPPS, json=body, headers=auth(user)), 201)


def new_act(api: TestClient, auth: Headers, user: str, **fields: Any) -> Any:
    return ok(
        api.post(ACTS, json={"kind": "task", "subject": "Do it", **fields}, headers=auth(user)), 201
    )


# === Opportunities ================================================================================


def test_agent_creates_an_opportunity_and_owns_it(api, auth, world) -> None:
    response = api.post(
        OPPS,
        json={
            "name": "50 licences",
            "account_id": str(world.ids["A1"]),
            "primary_contact_id": str(world.ids["C1"]),
            "amount": "1000.00",
            "currency": "EUR",
            "expected_close_date": str((NOW + timedelta(days=30)).date()),
            "next_step": "Send proposal",
        },
        headers=auth("alpha.agent1"),
    )
    body = ok(response, 201)
    assert response.headers["Location"] == f"{OPPS}/{body['id']}"
    assert (body["owner_id"], body["stage"], body["probability"]) == (
        uid(world, "alpha.agent1"),
        "prospecting",
        10,
    )
    assert (body["amount"], body["weighted_amount"], body["closed_at"]) == (
        "1000.00",
        "100.00",
        None,
    )
    history = ok(api.get(f"{OPPS}/{body['id']}/stages", headers=auth("alpha.agent1")))
    assert [(h["from_stage"], h["to_stage"], h["changed_by_name"]) for h in history] == [
        (None, "prospecting", "alpha.agent1")
    ]


@pytest.mark.parametrize(
    ("user", "fields", "expected"),
    [
        ("alpha.agent1", {"account": "A2"}, (404, "related_not_found")),  # colleague's account
        ("alpha.manager", {"account": "B1"}, (404, "related_not_found")),  # other tenant
        ("alpha.agent1", {"primary_contact_id": "C2"}, (404, "related_not_found")),  # hidden
        ("alpha.manager", {"primary_contact_id": "C2"}, (422, "invalid_opportunity")),  # other acct
    ],
)
def test_linked_records_must_be_visible_and_consistent(
    api, auth, world, user, fields, expected
) -> None:
    body: dict[str, Any] = {"name": "X", "account_id": str(world.ids[fields.get("account", "A1")])}
    if "primary_contact_id" in fields:
        body["primary_contact_id"] = str(world.ids[fields["primary_contact_id"]])
    assert code_of(api.post(OPPS, json=body, headers=auth(user))) == expected


@pytest.mark.parametrize(
    "extra",
    [
        {"amount": "-1"},
        {"amount": "1.234"},
        {"currency": "eur"},
        {"stage": "closed_won"},  # closing has its own endpoints
        {"closed_at": "2026-01-01T00:00:00Z"},  # server-controlled
        {"probability": 90},  # calculated from the stage
        {"tenant_id": str(uuid.uuid4())},
    ],
)
def test_opportunity_input_is_validated(api, auth, world, extra) -> None:
    body = {"name": "X", "account_id": str(world.ids["A1"]), **extra}
    assert api.post(OPPS, json=body, headers=auth("alpha.agent1")).status_code == 422


def test_deal_owner_rules(api, auth, world) -> None:
    a1 = world.ids["A1"]
    body = {"name": "X", "account_id": str(a1), "owner_id": uid(world, "alpha.agent2")}
    assert api.post(OPPS, json=body, headers=auth("alpha.agent1")).status_code == 403
    assert new_opp(api, auth, "alpha.manager", a1, owner_id=uid(world, "alpha.agent2"))["owner_id"]
    body["owner_id"] = uid(world, "alpha.support")
    assert code_of(api.post(OPPS, json=body, headers=auth("alpha.manager"))) == (
        422,
        "invalid_opportunity",
    )


def test_moving_through_the_pipeline(api, auth, world) -> None:
    opp = new_opp(api, auth, "alpha.agent1", world.ids["A1"], amount="200.00")
    url = f"{OPPS}/{opp['id']}"
    agent = auth("alpha.agent1")
    moved = ok(api.post(f"{url}/stage", json={"version": 1, "stage": "proposal"}, headers=agent))
    assert (moved["stage"], moved["probability"], moved["weighted_amount"]) == (
        "proposal",
        50,
        "100.00",
    )
    same = api.post(f"{url}/stage", json={"version": 2, "stage": "proposal"}, headers=agent)
    assert same.status_code == 409
    stale = api.post(f"{url}/stage", json={"version": 1, "stage": "negotiation"}, headers=agent)
    assert code_of(stale) == (409, "version_conflict")
    closing = api.post(f"{url}/stage", json={"version": 2, "stage": "closed_won"}, headers=agent)
    assert closing.status_code == 422  # won/lost have their own endpoints
    body = {"version": 2, "stage": "negotiation"}
    assert api.post(f"{url}/stage", json=body, headers=auth("alpha.agent2")).status_code == 404
    assert api.post(f"{url}/stage", json=body, headers=auth("beta.admin")).status_code == 404
    assert api.post(f"{url}/stage", json=body, headers=auth("alpha.support")).status_code == 403
    history = ok(api.get(f"{url}/stages", headers=agent))
    assert [(h["from_stage"], h["to_stage"]) for h in history] == [
        ("prospecting", "proposal"),
        (None, "prospecting"),
    ]


def test_won_needs_a_value_and_closes_the_deal(api, auth, world) -> None:
    opp = new_opp(api, auth, "alpha.agent1", world.ids["A1"])
    url = f"{OPPS}/{opp['id']}"
    agent = auth("alpha.agent1")
    no_value = api.post(f"{url}/won", json={"version": 1}, headers=agent)
    assert code_of(no_value) == (422, "invalid_opportunity")
    ok(api.patch(url, json={"version": 1, "amount": "750.00"}, headers=agent))
    won = ok(api.post(f"{url}/won", json={"version": 2, "note": "Signed"}, headers=agent))
    assert (won["stage"], won["probability"], won["weighted_amount"]) == (
        "closed_won",
        100,
        "750.00",
    )
    assert won["closed_at"] is not None

    for attempt in (
        api.patch(url, json={"version": 3, "amount": "1.00"}, headers=agent),
        api.post(f"{url}/stage", json={"version": 3, "stage": "proposal"}, headers=agent),
        api.post(f"{url}/lost", json={"version": 3, "reason": "x"}, headers=agent),
    ):
        assert code_of(attempt) == (409, "opportunity_closed")
    assert api.post(f"{url}/reopen", json={"version": 3}, headers=agent).status_code == 403
    reopened = ok(api.post(f"{url}/reopen", json={"version": 3}, headers=auth("alpha.manager")))
    assert (reopened["stage"], reopened["closed_at"]) == ("negotiation", None)


def test_lost_needs_a_reason(api, auth, world) -> None:
    opp = new_opp(api, auth, "alpha.agent1", world.ids["A1"], amount="10.00")
    url = f"{OPPS}/{opp['id']}"
    agent = auth("alpha.agent1")
    assert api.post(f"{url}/lost", json={"version": 1}, headers=agent).status_code == 422
    lost = ok(
        api.post(f"{url}/lost", json={"version": 1, "reason": "Too expensive"}, headers=agent)
    )
    assert (lost["stage"], lost["lost_reason"], lost["weighted_amount"]) == (
        "closed_lost",
        "Too expensive",
        "0.00",
    )
    reopened = ok(
        api.post(
            f"{url}/reopen", json={"version": 2, "stage": "proposal"}, headers=auth("alpha.manager")
        )
    )
    assert (reopened["stage"], reopened["lost_reason"]) == ("proposal", None)


def test_edit_rules(api, auth, world) -> None:
    opp = new_opp(api, auth, "alpha.agent1", world.ids["A1"])
    url = f"{OPPS}/{opp['id']}"
    agent = auth("alpha.agent1")
    changed = ok(
        api.patch(
            url,
            json={
                "version": 1,
                "next_step": "Call CFO",
                "primary_contact_id": str(world.ids["C1"]),
            },
            headers=agent,
        )
    )
    assert changed["next_step"] == "Call CFO"
    reassign = {"version": 2, "owner_id": uid(world, "alpha.agent2")}
    assert api.patch(url, json=reassign, headers=agent).status_code == 403
    ok(api.patch(url, json=reassign, headers=auth("alpha.manager")))
    assert api.get(url, headers=agent).status_code == 404  # no longer theirs
    for bad in ({"version": 3}, {"version": 3, "name": None}, {"version": 3, "stage": "proposal"}):
        assert api.patch(url, json=bad, headers=auth("alpha.manager")).status_code == 422


def test_board_columns_totals_and_scope(api, auth, world) -> None:
    a1, a2 = world.ids["A1"], world.ids["A2"]
    new_opp(api, auth, "alpha.agent1", a1, name="P1", stage="proposal", amount="1000.00")
    new_opp(api, auth, "alpha.agent1", a1, name="P2", stage="proposal", amount="500.50")
    new_opp(
        api, auth, "alpha.agent1", a1, name="P3", stage="proposal", amount="200.00", currency="USD"
    )
    new_opp(api, auth, "alpha.agent1", a1, name="P4", stage="proposal")  # no amount yet
    new_opp(api, auth, "alpha.agent2", a2, name="N1", stage="negotiation", amount="400.00")
    won = new_opp(api, auth, "alpha.agent2", a2, name="W1", amount="99.00")
    ok(api.post(f"{OPPS}/{won['id']}/won", json={"version": 1}, headers=auth("alpha.agent2")))
    new_opp(api, auth, "beta.agent", world.ids["B1"], name="B", stage="proposal", amount="5.00")

    def columns(user: str, **params: Any) -> dict[str, Any]:
        board = ok(api.get(f"{OPPS}/board", params=params, headers=auth(user)))
        return {c["stage"]: c for c in [*board["columns"], board["won"], board["lost"]]}

    def money(values: list[dict[str, str]]) -> dict[str, str]:
        return {v["currency"]: v["amount"] for v in values}

    manager = columns("alpha.manager")
    assert list(manager)[:4] == ["prospecting", "qualification", "proposal", "negotiation"]
    proposal = manager["proposal"]
    assert (proposal["count"], proposal["probability"]) == (4, 50)
    assert money(proposal["value"]) == {"EUR": "1500.50", "USD": "200.00"}
    assert money(proposal["weighted"]) == {"EUR": "750.25", "USD": "100.00"}
    assert [o["name"] for o in proposal["items"]] == ["P1", "P2", "P3", "P4"]
    assert (manager["negotiation"]["count"], manager["closed_won"]["count"]) == (1, 1)

    agent1 = columns("alpha.agent1")
    assert (agent1["proposal"]["count"], agent1["negotiation"]["count"]) == (4, 0)
    assert agent1["closed_won"]["count"] == 0
    narrowed = columns("alpha.manager", owner_id=uid(world, "alpha.agent2"))
    assert (narrowed["proposal"]["count"], narrowed["negotiation"]["count"]) == (0, 1)
    assert columns("beta.admin")["proposal"]["count"] == 1
    limited = columns("alpha.manager", limit=2)["proposal"]
    assert (limited["count"], len(limited["items"])) == (4, 2)  # totals cover every deal
    assert api.get(f"{OPPS}/board", headers=auth("alpha.support")).status_code == 403
    assert api.get(f"{OPPS}/board", headers=auth("alpha.customer")).status_code == 403


# === Activities and tasks =========================================================================


def test_agent_plans_a_follow_up_on_their_lead(api, auth, world) -> None:
    due = NOW + timedelta(days=1)
    task = new_act(
        api,
        auth,
        "alpha.agent1",
        kind="call",
        subject="Call back about pricing",
        lead_id=str(world.ids["L1"]),
        due_at=iso(due),
        reminder_at=iso(due - timedelta(hours=1)),
        priority="high",
    )
    assert (task["status"], task["assignee_id"], task["overdue"]) == (
        "open",
        uid(world, "alpha.agent1"),
        False,
    )
    assert (task["related_type"], task["related_id"]) == ("lead", str(world.ids["L1"]))
    mine = ok(api.get(ACTS, params={"mine": True, "status": "open"}, headers=auth("alpha.agent1")))
    assert [a["subject"] for a in mine["items"]] == ["Call back about pricing"]
    timeline = ok(
        api.get(ACTS, params={"lead_id": str(world.ids["L1"])}, headers=auth("alpha.agent1"))
    )
    assert timeline["total"] == 1


def test_logging_something_that_happened(api, auth, world) -> None:
    when = NOW - timedelta(hours=3)
    call = new_act(
        api,
        auth,
        "alpha.agent1",
        kind="call",
        subject="Intro call",
        status="done",
        occurred_at=iso(when),
        outcome="Interested",
        account_id=str(world.ids["A1"]),
    )
    assert call["status"] == "done"
    assert datetime.fromisoformat(call["completed_at"]) == when
    note = new_act(api, auth, "alpha.agent1", kind="note", subject="Prefers e-mail")
    assert (note["status"], note["completed_at"] is not None) == ("done", True)


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "note", "subject": "x", "status": "open"},
        {"kind": "task", "subject": ""},
        {"kind": "visit", "subject": "x"},
        {"kind": "task", "subject": "x", "due_at": "2026-10-20T09:00:00"},  # no time zone
        {
            "kind": "task",
            "subject": "x",
            "due_at": "2026-10-20T09:00:00Z",
            "reminder_at": "2026-10-21T09:00:00Z",
        },
        {"kind": "call", "subject": "x", "status": "done", "due_at": "2026-10-20T09:00:00Z"},
        {"kind": "call", "subject": "x", "status": "done", "occurred_at": "2999-01-01T00:00:00Z"},
        {"kind": "task", "subject": "x", "occurred_at": "2026-01-01T00:00:00Z"},
        {"kind": "task", "subject": "x", "completed_at": "2026-01-01T00:00:00Z"},
        {
            "kind": "task",
            "subject": "x",
            "lead_id": str(uuid.uuid4()),
            "account_id": str(uuid.uuid4()),
        },
    ],
)
def test_activity_input_is_validated(api, auth, world, body) -> None:
    assert api.post(ACTS, json=body, headers=auth("alpha.agent1")).status_code == 422


@pytest.mark.parametrize(
    ("link", "key"),
    [
        ("lead_id", "L2"),
        ("account_id", "A2"),
        ("contact_id", "C2"),
        ("account_id", "B1"),
        ("lead_id", "random"),
    ],
)
def test_linking_to_a_record_you_cannot_see_is_404(api, auth, world, link, key) -> None:
    record = str(world.ids.get(key, uuid.uuid4()))
    response = api.post(
        ACTS, json={"kind": "task", "subject": "x", link: record}, headers=auth("alpha.agent1")
    )
    assert code_of(response) == (404, "related_not_found")


def test_assigning_work_to_colleagues(api, auth, world) -> None:
    other = {"assignee_id": uid(world, "alpha.agent2")}
    response = api.post(
        ACTS, json={"kind": "task", "subject": "x", **other}, headers=auth("alpha.agent1")
    )
    assert response.status_code == 403
    task = new_act(api, auth, "alpha.manager", subject="Prepare demo", **other)
    assert task["assignee_id"] == other["assignee_id"]
    for outsider in ("alpha.customer", "beta.agent"):
        body = {"kind": "task", "subject": "x", "assignee_id": uid(world, outsider)}
        assert code_of(api.post(ACTS, json=body, headers=auth("alpha.manager"))) == (
            422,
            "invalid_activity",
        )


def test_who_sees_which_activities(api, auth, world) -> None:
    new_act(api, auth, "alpha.agent1", subject="Agent1 own")
    new_act(api, auth, "alpha.agent2", subject="Agent2 own")
    new_act(api, auth, "alpha.manager", subject="Manager on A1", account_id=str(world.ids["A1"]))
    new_act(api, auth, "alpha.manager", subject="Manager private")
    new_act(
        api, auth, "alpha.manager", subject="For agent2", assignee_id=uid(world, "alpha.agent2")
    )
    new_act(api, auth, "alpha.support", subject="Support own")
    new_act(api, auth, "beta.agent", subject="Beta")

    def seen(user: str) -> set[str]:
        return {a["subject"] for a in ok(api.get(ACTS, headers=auth(user)))["items"]}

    assert seen("alpha.agent1") == {"Agent1 own", "Manager on A1"}  # A1 is agent1's account
    assert seen("alpha.agent2") == {"Agent2 own", "For agent2"}
    assert seen("alpha.support") == {"Support own"}
    assert len(seen("alpha.manager")) == 6
    assert seen("beta.admin") == {"Beta"}
    assert api.get(ACTS, headers=auth("alpha.customer")).status_code == 403


def test_complete_cancel_reopen_and_edit_rules(api, auth, world) -> None:
    task = new_act(
        api, auth, "alpha.agent1", subject="Send quote", due_at=iso(NOW + timedelta(days=2))
    )
    url = f"{ACTS}/{task['id']}"
    agent = auth("alpha.agent1")
    edited = ok(api.patch(url, json={"version": 1, "priority": "high"}, headers=agent))
    assert edited["priority"] == "high"
    assert code_of(api.patch(url, json={"version": 1, "priority": "low"}, headers=agent)) == (
        409,
        "version_conflict",
    )
    assert (
        api.patch(
            url, json={"version": 2, "subject": "x"}, headers=auth("alpha.agent2")
        ).status_code
        == 404
    )
    assert (
        api.patch(url, json={"version": 2, "subject": "x"}, headers=auth("beta.admin")).status_code
        == 404
    )
    reassign = {"version": 2, "assignee_id": uid(world, "alpha.agent2")}
    assert api.patch(url, json=reassign, headers=agent).status_code == 403

    done = ok(api.post(f"{url}/complete", json={"version": 2, "outcome": "Sent"}, headers=agent))
    assert (done["status"], done["outcome"], done["completed_at"] is not None) == (
        "done",
        "Sent",
        True,
    )
    assert code_of(api.patch(url, json={"version": 3, "subject": "x"}, headers=agent)) == (
        409,
        "activity_state",
    )
    assert code_of(api.post(f"{url}/complete", json={"version": 3}, headers=agent)) == (
        409,
        "activity_state",
    )
    again = ok(api.post(f"{url}/reopen", json={"version": 3}, headers=agent))
    assert (again["status"], again["completed_at"], again["outcome"]) == ("open", None, None)
    cancelled = ok(
        api.post(f"{url}/cancel", json={"version": 4, "reason": "Not needed"}, headers=agent)
    )
    assert cancelled["status"] == "cancelled"

    note = new_act(api, auth, "alpha.agent1", kind="note", subject="n")
    assert code_of(api.post(f"{ACTS}/{note['id']}/reopen", json={"version": 1}, headers=agent)) == (
        409,
        "activity_state",
    )


def test_reminders_and_overdue(api, auth, world) -> None:
    new_act(api, auth, "alpha.agent1", subject="Late", due_at=iso(NOW - timedelta(hours=2)))
    new_act(api, auth, "alpha.agent1", subject="Soon", due_at=iso(NOW + timedelta(hours=3)))
    new_act(
        api,
        auth,
        "alpha.agent1",
        subject="Remind me",
        due_at=iso(NOW + timedelta(days=5)),
        reminder_at=iso(NOW - timedelta(minutes=10)),
    )
    new_act(api, auth, "alpha.agent1", subject="Later", due_at=iso(NOW + timedelta(days=9)))
    new_act(api, auth, "alpha.agent2", subject="Not mine", due_at=iso(NOW - timedelta(hours=1)))
    reminders = ok(api.get(f"{ACTS}/reminders", headers=auth("alpha.agent1")))
    assert (reminders["overdue"], reminders["due_next_24h"], reminders["reminders_due"]) == (
        1,
        1,
        1,
    )
    assert [a["subject"] for a in reminders["items"]] == ["Late", "Soon", "Remind me"]
    assert reminders["attention"] == 3
    assert reminders["items"][0]["overdue"] is True
    late = ok(api.get(ACTS, params={"overdue": True, "mine": True}, headers=auth("alpha.agent1")))
    assert [a["subject"] for a in late["items"]] == ["Late"]
    # An item that is overdue AND past its reminder counts once in "attention".
    new_act(
        api,
        auth,
        "alpha.agent1",
        subject="Late and reminded",
        due_at=iso(NOW - timedelta(hours=1)),
        reminder_at=iso(NOW - timedelta(hours=2)),
    )
    again = ok(api.get(f"{ACTS}/reminders", headers=auth("alpha.agent1")))
    assert (again["overdue"], again["reminders_due"], again["attention"]) == (2, 2, 4)


def test_calendar_range(api, auth, world) -> None:
    base = datetime(2030, 3, 10, 9, tzinfo=UTC)
    for days, subject in [(0, "Mon"), (3, "Thu"), (8, "Next week")]:
        new_act(api, auth, "alpha.agent1", subject=subject, due_at=iso(base + timedelta(days=days)))
    week = ok(
        api.get(
            ACTS,
            params={"due_from": "2030-03-10T00:00:00Z", "due_to": "2030-03-17T00:00:00Z"},
            headers=auth("alpha.agent1"),
        )
    )
    assert [a["subject"] for a in week["items"]] == ["Mon", "Thu"]
    naive = api.get(ACTS, params={"due_from": "2030-03-10T00:00:00"}, headers=auth("alpha.agent1"))
    assert code_of(naive) == (422, "invalid_filter")


def test_opportunity_timeline_shows_its_activities(api, auth, world) -> None:
    opp = new_opp(api, auth, "alpha.agent1", world.ids["A1"])
    link = {"opportunity_id": opp["id"]}
    new_act(api, auth, "alpha.agent1", kind="meeting", subject="Demo", status="done",
            occurred_at=iso(NOW - timedelta(days=2)), **link)  # fmt: skip
    new_act(
        api,
        auth,
        "alpha.agent1",
        subject="Send proposal",
        due_at=iso(NOW + timedelta(days=1)),
        **link,
    )
    timeline = ok(
        api.get(
            ACTS,
            params={"opportunity_id": opp["id"], "sort": "-when"},
            headers=auth("alpha.agent1"),
        )
    )
    assert [a["subject"] for a in timeline["items"]] == ["Send proposal", "Demo"]
    # agent2 can't see agent1's deal, so neither its activities.
    hidden = ok(api.get(ACTS, params={"opportunity_id": opp["id"]}, headers=auth("alpha.agent2")))
    assert hidden["total"] == 0


def test_board_won_column_covers_only_recent_deals(api, auth, world, db_session) -> None:
    from sqlalchemy import update

    from app.modules.sales.models import Opportunity

    old = new_opp(api, auth, "alpha.agent1", world.ids["A1"], name="Old win", amount="1.00")
    ok(api.post(f"{OPPS}/{old['id']}/won", json={"version": 1}, headers=auth("alpha.agent1")))
    db_session.execute(
        update(Opportunity)
        .where(Opportunity.id == uuid.UUID(old["id"]))
        .values(closed_at=NOW - timedelta(days=60))
    )
    db_session.flush()

    def won(**params: Any) -> list[str]:
        board = ok(api.get(f"{OPPS}/board", params=params, headers=auth("alpha.agent1")))
        return [o["name"] for o in board["won"]["items"]]

    assert won() == []
    assert won(closed_days=90) == ["Old win"]


def test_opportunity_write_policy_on_its_own(world) -> None:
    """Defence in depth: someone who could READ all deals but WRITE only their own (no such
    role today) must still be refused on a colleague's deal."""
    from app.core.auth.principal import Principal
    from app.core.auth.rbac import Permission
    from app.modules.sales.models import Opportunity
    from app.modules.sales.policies import can_write

    agent = world.users["alpha.agent1"]
    principal = Principal(
        subject=agent.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset(),
        permissions=frozenset({Permission.OPPORTUNITY_READ_ALL, Permission.OPPORTUNITY_WRITE_OWN}),
        user_id=agent.id,
        tenant_id=agent.tenant_id,
    )
    mine = Opportunity(
        tenant_id=agent.tenant_id, name="m", account_id=world.ids["A1"], owner_id=agent.id
    )
    theirs = Opportunity(
        tenant_id=agent.tenant_id,
        name="t",
        account_id=world.ids["A2"],
        owner_id=world.users["alpha.agent2"].id,
    )
    assert (can_write(principal, mine), can_write(principal, theirs)) == (True, False)
