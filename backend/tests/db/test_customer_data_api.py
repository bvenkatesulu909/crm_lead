"""Phase B - accounts (write), contacts and read-only opportunities, through the real API and
PostgreSQL (rolled back after each test).

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support, customer -> A1
tenant BETA:  admin, agent (owns B1)
"""

import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.identity.models import PortalAccessGrant, Tenant, User
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
ACCOUNTS = "/api/v1/accounts"
CONTACTS = "/api/v1/contacts"


class World:
    users: dict[str, User]
    accounts: dict[str, uuid.UUID]
    opportunities: dict[str, uuid.UUID]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        new_tenant = Tenant(slug=f"{slug}-custdata", name=f"{slug.title()} Customer Data Test")
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
    w.accounts = {}
    for key, slug, owner in [
        ("A1", "alpha", "alpha.agent1"),
        ("A2", "alpha", "alpha.agent2"),
        ("B1", "beta", "beta.agent"),
    ]:
        account = Account(
            tenant_id=tenants[slug], name=f"CustData {key}", owner_id=w.users[owner].id
        )
        db_session.add(account)
        db_session.flush()
        w.accounts[key] = account.id
    customer = w.users["alpha.customer"]
    db_session.add(
        PortalAccessGrant(
            tenant_id=customer.tenant_id, user_id=customer.id, account_id=w.accounts["A1"]
        )
    )
    w.opportunities = {}
    for key, opp_account, owner in [
        ("O1", "A1", "alpha.agent1"),
        ("O2", "A2", "alpha.agent2"),
        ("OB", "B1", "beta.agent"),
    ]:
        opp = Opportunity(
            tenant_id=w.users[owner].tenant_id,
            name=f"Deal {key}",
            account_id=w.accounts[opp_account],
            owner_id=w.users[owner].id,
            amount=Decimal("1000.00"),
            currency="EUR",
        )
        db_session.add(opp)
        db_session.flush()
        w.opportunities[key] = opp.id
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
    """The JSON body (an object or a list) after checking the status code."""
    assert response.status_code == code, response.text
    return response.json()


def code_of(response: Any) -> tuple[int, str | None]:
    body = response.json() if response.content else {}
    return response.status_code, body.get("code")


def new_account(api: TestClient, auth: Headers, user: str, **fields: Any) -> Any:
    return ok(api.post(ACCOUNTS, json={"name": "New Co", **fields}, headers=auth(user)), 201)


def new_contact(api: TestClient, auth: Headers, user: str, **fields: Any) -> Any:
    return ok(api.post(CONTACTS, json={"last_name": "Person", **fields}, headers=auth(user)), 201)


def uid(world: World, name: str) -> str:
    return str(world.users[name].id)


# === Accounts: create =============================================================================


def test_agent_creates_an_account_and_owns_it(api, auth, world) -> None:
    response = api.post(
        ACCOUNTS,
        json={
            "name": "  Fictional Widgets Ltd ",
            "website": "widgets.example",
            "segment": "small_business",
            "preferred_channel": "email",
            "phone": "+44 20 7946 0000",
        },
        headers=auth("alpha.agent1"),
    )
    body = ok(response, 201)
    assert response.headers["Location"] == f"{ACCOUNTS}/{body['id']}"
    assert body["name"] == "Fictional Widgets Ltd"
    assert body["website"] == "https://widgets.example"
    assert (body["owner_id"], body["status"], body["version"]) == (
        uid(world, "alpha.agent1"),
        "active",
        1,
    )
    timeline = ok(api.get(f"{ACCOUNTS}/{body['id']}/timeline", headers=auth("alpha.agent1")))
    assert [(t["title"], t["actor_name"]) for t in timeline] == [
        ("Account created", "alpha.agent1")
    ]
    assert timeline[0]["changes"]["segment"] == {"old": None, "new": "small_business"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": "   "},
        {"name": "X", "website": "javascript:alert(1)"},
        {"name": "X", "segment": "huge"},
        {"name": "X", "preferred_channel": "pigeon"},
        {"name": "X", "phone": "call me maybe"},
        {"name": "X", "tenant_id": str(uuid.uuid4())},  # server-controlled
        {"name": "X", "status": "inactive"},  # only via /status
        {"name": "X" * 256},
    ],
)
def test_account_input_is_validated(api, auth, world, body) -> None:
    assert api.post(ACCOUNTS, json=body, headers=auth("alpha.agent1")).status_code == 422


def test_only_managers_choose_another_owner(api, auth, world) -> None:
    other = {"owner_id": uid(world, "alpha.agent2")}
    response = api.post(ACCOUNTS, json={"name": "X", **other}, headers=auth("alpha.agent1"))
    assert response.status_code == 403
    assert new_account(api, auth, "alpha.manager", **other)["owner_id"] == other["owner_id"]


@pytest.mark.parametrize("owner", ["alpha.support", "beta.agent", "alpha.customer", "random"])
def test_owner_must_be_a_sales_employee_of_the_tenant(api, auth, world, owner) -> None:
    owner_id = uid(world, owner) if owner in world.users else str(uuid.uuid4())
    response = api.post(
        ACCOUNTS, json={"name": "X", "owner_id": owner_id}, headers=auth("alpha.manager")
    )
    assert code_of(response) == (422, "invalid_owner")


def test_account_numbers_are_unique_per_tenant(api, auth, world) -> None:
    new_account(api, auth, "alpha.manager", account_number="ERP-1")
    again = api.post(
        ACCOUNTS, json={"name": "Y", "account_number": "ERP-1"}, headers=auth("alpha.agent1")
    )
    assert code_of(again) == (409, "account_number_taken")
    new_account(api, auth, "beta.admin", account_number="ERP-1")  # other tenant: fine


@pytest.mark.parametrize(("user", "parent"), [("alpha.agent1", "A2"), ("alpha.manager", "B1")])
def test_parent_must_be_an_account_you_can_see(api, auth, world, user, parent) -> None:
    body = {"name": "Child", "parent_account_id": str(world.accounts[parent])}
    assert code_of(api.post(ACCOUNTS, json=body, headers=auth(user))) == (404, "account_not_found")


# === Accounts: hierarchy ==========================================================================


def test_hierarchy_children_and_loops(api, auth, world) -> None:
    a1 = str(world.accounts["A1"])
    child = new_account(api, auth, "alpha.agent1", name="A1 Child", parent_account_id=a1)
    grandchild = new_account(
        api, auth, "alpha.agent1", name="A1 Grandchild", parent_account_id=child["id"]
    )
    children = ok(api.get(ACCOUNTS, params={"parent_account_id": a1}, headers=auth("alpha.agent1")))
    assert [a["name"] for a in children["items"]] == ["A1 Child"]
    parent_timeline = ok(api.get(f"{ACCOUNTS}/{a1}/timeline", headers=auth("alpha.agent1")))
    assert parent_timeline[0]["title"] == "Child account added"

    a1_version = ok(api.get(f"{ACCOUNTS}/{a1}", headers=auth("alpha.agent1")))["version"]
    for parent in (grandchild["id"], a1):  # a descendant, or itself
        response = api.patch(
            f"{ACCOUNTS}/{a1}",
            json={"version": a1_version, "parent_account_id": parent},
            headers=auth("alpha.agent1"),
        )
        assert code_of(response) == (422, "invalid_hierarchy")


# === Accounts: edit ===============================================================================


def test_owner_edits_details_with_optimistic_locking(api, auth, world) -> None:
    url = f"{ACCOUNTS}/{world.accounts['A1']}"
    updated = ok(
        api.patch(
            url,
            json={"version": 1, "industry": "Manufacturing", "segment": "enterprise"},
            headers=auth("alpha.agent1"),
        )
    )
    assert (updated["industry"], updated["segment"], updated["version"]) == (
        "Manufacturing",
        "enterprise",
        2,
    )
    stale = api.patch(url, json={"version": 1, "industry": "Retail"}, headers=auth("alpha.agent1"))
    assert code_of(stale) == (409, "version_conflict")
    cleared = ok(api.patch(url, json={"version": 2, "segment": None}, headers=auth("alpha.agent1")))
    assert cleared["segment"] is None
    timeline = ok(api.get(f"{url}/timeline", headers=auth("alpha.agent1")))
    assert [t["title"] for t in timeline] == ["Details changed", "Details changed"]
    assert timeline[1]["changes"] == {
        "industry": {"old": None, "new": "Manufacturing"},
        "segment": {"old": None, "new": "enterprise"},
    }


@pytest.mark.parametrize(
    "body", [{"version": 1}, {"version": 1, "name": None}, {"version": 0, "name": "X"}]
)
def test_account_update_validation(api, auth, world, body) -> None:
    url = f"{ACCOUNTS}/{world.accounts['A1']}"
    assert api.patch(url, json=body, headers=auth("alpha.agent1")).status_code == 422


@pytest.mark.parametrize(
    ("user", "account", "expected"),
    [
        ("alpha.agent1", "A2", 404),  # colleague's account: invisible
        ("beta.admin", "A1", 404),  # other tenant: invisible
        ("alpha.support", "A1", 403),  # can read, may not write
        ("alpha.customer", "A1", 403),  # portal users never use the staff API
    ],
)
def test_who_may_not_edit_an_account(api, auth, world, user, account, expected) -> None:
    url = f"{ACCOUNTS}/{world.accounts[account]}"
    response = api.patch(url, json={"version": 1, "industry": "X"}, headers=auth(user))
    assert response.status_code == expected


def test_only_managers_reassign_and_the_old_owner_loses_access(api, auth, world) -> None:
    url = f"{ACCOUNTS}/{world.accounts['A1']}"
    to_agent2 = {"version": 1, "owner_id": uid(world, "alpha.agent2")}
    assert api.patch(url, json=to_agent2, headers=auth("alpha.agent1")).status_code == 403
    ok(api.patch(url, json=to_agent2, headers=auth("alpha.manager")))
    assert api.get(url, headers=auth("alpha.agent1")).status_code == 404
    assert api.get(url, headers=auth("alpha.agent2")).status_code == 200


# === Accounts: status, archive, restore ===========================================================


def test_deactivate_archive_and_restore(api, auth, world) -> None:
    url = f"{ACCOUNTS}/{world.accounts['A1']}"
    manager = auth("alpha.manager")
    early = api.post(f"{url}/archive", json={"version": 1, "reason": "Closed"}, headers=manager)
    assert code_of(early) == (409, "account_state")  # must be inactive first

    inactive = ok(
        api.post(
            f"{url}/status",
            json={"version": 1, "status": "inactive", "reason": "No longer trading"},
            headers=auth("alpha.agent1"),
        )
    )
    assert inactive["status"] == "inactive"
    again = api.post(
        f"{url}/status", json={"version": 2, "status": "inactive"}, headers=auth("alpha.agent1")
    )
    assert code_of(again) == (409, "account_state")

    body = {"version": 2, "reason": "Company closed"}
    assert api.post(f"{url}/archive", json=body, headers=auth("alpha.agent1")).status_code == 403
    archived = ok(api.post(f"{url}/archive", json=body, headers=manager))
    assert archived["deleted_at"] is not None

    assert api.get(url, headers=manager).status_code == 404
    listed = ok(api.get(ACCOUNTS, params={"q": "CustData A1"}, headers=manager))
    assert listed["total"] == 0
    shelf = ok(api.get(ACCOUNTS, params={"archived": True}, headers=manager))
    assert [a["name"] for a in shelf["items"]] == ["CustData A1"]
    agent_shelf = api.get(ACCOUNTS, params={"archived": True}, headers=auth("alpha.agent1"))
    assert agent_shelf.status_code == 403
    beta_shelf = ok(api.get(ACCOUNTS, params={"archived": True}, headers=auth("beta.admin")))
    assert beta_shelf["total"] == 0

    restored = ok(api.post(f"{url}/restore", json={"version": 3}, headers=manager))
    assert restored["deleted_at"] is None
    timeline = ok(api.get(f"{url}/timeline", headers=manager))
    assert [t["title"] for t in timeline] == [
        "Account restored",
        "Account archived",
        "Account deactivated",
    ]
    assert timeline[2]["changes"]["reason"] == "No longer trading"


def test_an_account_with_children_cannot_be_archived(api, auth, world) -> None:
    a1 = str(world.accounts["A1"])
    new_account(api, auth, "alpha.agent1", name="Child", parent_account_id=a1)
    manager = auth("alpha.manager")
    ok(
        api.post(
            f"{ACCOUNTS}/{a1}/status", json={"version": 1, "status": "inactive"}, headers=manager
        )
    )
    response = api.post(
        f"{ACCOUNTS}/{a1}/archive", json={"version": 2, "reason": "X"}, headers=manager
    )
    assert code_of(response) == (409, "account_state")


def test_restoring_needs_the_archived_account_of_your_tenant(api, auth, world) -> None:
    url = f"{ACCOUNTS}/{world.accounts['A1']}/restore"
    assert api.post(url, json={"version": 1}, headers=auth("alpha.manager")).status_code == 404
    assert api.post(url, json={"version": 1}, headers=auth("beta.admin")).status_code == 404


def test_timeline_of_an_invisible_account_is_404(api, auth, world) -> None:
    url = f"{ACCOUNTS}/{world.accounts['A1']}/timeline"
    assert api.get(url, headers=auth("alpha.agent2")).status_code == 404
    assert api.get(url, headers=auth("beta.admin")).status_code == 404


def test_account_filters(api, auth, world) -> None:
    new_account(api, auth, "alpha.manager", name="Seg Co", segment="public_sector")
    manager = auth("alpha.manager")
    by_segment = ok(api.get(ACCOUNTS, params={"segment": "public_sector"}, headers=manager))
    assert [a["name"] for a in by_segment["items"]] == ["Seg Co"]
    by_owner = ok(
        api.get(ACCOUNTS, params={"owner_id": uid(world, "alpha.agent2")}, headers=manager)
    )
    assert [a["name"] for a in by_owner["items"]] == ["CustData A2"]
    assert api.get(ACCOUNTS, params={"segment": "x"}, headers=manager).status_code == 422


# === Contacts =====================================================================================


def test_agent_creates_a_contact_on_their_account(api, auth, world) -> None:
    a1 = str(world.accounts["A1"])
    response = api.post(
        CONTACTS,
        json={
            "first_name": "Sam",
            "last_name": "Sample",
            "email": "Sam@Example.TEST",
            "mobile": "+44 7700 900000",
            "job_title": "Head of IT",
            "department": "IT",
            "account_id": a1,
            "preferred_channel": "mobile",
        },
        headers=auth("alpha.agent1"),
    )
    body = ok(response, 201)
    assert response.headers["Location"] == f"{CONTACTS}/{body['id']}"
    assert body["email"] == "Sam@example.test"
    assert (body["owner_id"], body["account_id"], body["is_primary"]) == (
        uid(world, "alpha.agent1"),
        a1,
        False,
    )
    assert (body["email_consent"], body["email_consent_at"], body["do_not_call"]) == (
        "unknown",
        None,
        False,
    )
    timeline = ok(api.get(f"{ACCOUNTS}/{a1}/timeline", headers=auth("alpha.agent1")))
    assert (timeline[0]["title"], timeline[0]["changes"]["contact_name"]) == (
        "Contact added",
        "Sam Sample",
    )
    history = ok(api.get(f"{CONTACTS}/{body['id']}/history", headers=auth("alpha.agent1")))
    assert [h["title"] for h in history] == ["Contact created"]


@pytest.mark.parametrize("account", ["A2", "B1", "random"])
def test_contact_on_an_account_you_cannot_see_is_404(api, auth, world, account) -> None:
    account_id = str(world.accounts.get(account, uuid.uuid4()))
    response = api.post(
        CONTACTS, json={"last_name": "X", "account_id": account_id}, headers=auth("alpha.agent1")
    )
    assert code_of(response) == (404, "account_not_found")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"last_name": "X", "email": "not-an-email"},
        {"last_name": "X", "email_consent": "maybe"},
        {"last_name": "X", "email_consent_at": "2020-01-01T00:00:00Z"},  # server-controlled
        {"last_name": "X", "tenant_id": str(uuid.uuid4())},
        {"last_name": "X", "is_primary": True},  # primary needs an account
    ],
)
def test_contact_input_is_validated(api, auth, world, body) -> None:
    assert api.post(CONTACTS, json=body, headers=auth("alpha.agent1")).status_code == 422


def test_agents_see_their_contacts_and_those_of_their_accounts(api, auth, world) -> None:
    a1 = str(world.accounts["A1"])
    on_a1 = new_contact(api, auth, "alpha.manager", last_name="OnA1", account_id=a1)
    loose = new_contact(api, auth, "alpha.agent2", last_name="Loose")  # owned by agent2

    def names(user: str) -> list[str]:
        page = ok(api.get(CONTACTS, headers=auth(user)))
        return [c["last_name"] for c in page["items"]]

    assert names("alpha.agent1") == ["OnA1"]  # on my account, though owned by the manager
    assert names("alpha.agent2") == ["Loose"]
    assert names("alpha.manager") == ["Loose", "OnA1"]
    assert names("alpha.support") == ["Loose", "OnA1"]  # support reads all
    assert names("beta.admin") == []
    assert api.get(f"{CONTACTS}/{on_a1['id']}", headers=auth("alpha.agent2")).status_code == 404
    assert api.get(f"{CONTACTS}/{loose['id']}", headers=auth("beta.admin")).status_code == 404
    assert api.get(CONTACTS, headers=auth("alpha.customer")).status_code == 403


def test_support_reads_contacts_but_cannot_change_them(api, auth, world) -> None:
    contact = new_contact(api, auth, "alpha.agent1")
    support = auth("alpha.support")
    assert api.post(CONTACTS, json={"last_name": "X"}, headers=support).status_code == 403
    url = f"{CONTACTS}/{contact['id']}"
    assert api.patch(url, json={"version": 1, "phone": "123"}, headers=support).status_code == 403


def test_one_primary_contact_per_account(api, auth, world) -> None:
    a1 = str(world.accounts["A1"])
    first = new_contact(
        api, auth, "alpha.agent1", last_name="First", account_id=a1, is_primary=True
    )
    second = new_contact(api, auth, "alpha.agent1", last_name="Second", account_id=a1)
    promoted = ok(
        api.patch(
            f"{CONTACTS}/{second['id']}",
            json={"version": second["version"], "is_primary": True},
            headers=auth("alpha.agent1"),
        )
    )
    assert promoted["is_primary"] is True
    first_now = ok(api.get(f"{CONTACTS}/{first['id']}", headers=auth("alpha.agent1")))
    assert (first_now["is_primary"], first_now["version"]) == (False, first["version"] + 1)
    primaries = ok(
        api.get(
            CONTACTS, params={"account_id": a1, "primary_only": True}, headers=auth("alpha.agent1")
        )
    )
    assert [c["last_name"] for c in primaries["items"]] == ["Second"]
    history = ok(api.get(f"{CONTACTS}/{first['id']}/history", headers=auth("alpha.agent1")))
    assert history[0]["changes"] == {"is_primary": {"old": True, "new": False}}
    timeline = ok(api.get(f"{ACCOUNTS}/{a1}/timeline", headers=auth("alpha.agent1")))
    assert [t["changes"].get("contact_name") for t in timeline if "Primary" in t["title"]] == [
        "Second",
        "First",
    ]


def test_consent_is_dated_by_the_server(api, auth, world) -> None:
    contact = new_contact(api, auth, "alpha.agent1", email="c@example.test")
    url = f"{CONTACTS}/{contact['id']}"
    granted = ok(
        api.patch(
            url, json={"version": 1, "email_consent": "granted"}, headers=auth("alpha.agent1")
        )
    )
    assert granted["email_consent_at"] is not None
    withdrawn = ok(
        api.patch(
            url,
            json={"version": 2, "email_consent": "withdrawn", "do_not_call": True},
            headers=auth("alpha.agent1"),
        )
    )
    assert withdrawn["email_consent_at"] >= granted["email_consent_at"]
    assert withdrawn["do_not_call"] is True
    unknown = ok(
        api.patch(
            url, json={"version": 3, "email_consent": "unknown"}, headers=auth("alpha.agent1")
        )
    )
    assert unknown["email_consent_at"] is None
    for bad in ({"version": 4, "email_consent": None}, {"version": 4, "do_not_call": None}):
        assert api.patch(url, json=bad, headers=auth("alpha.agent1")).status_code == 422
    filtered = ok(
        api.get(CONTACTS, params={"email_consent": "unknown"}, headers=auth("alpha.agent1"))
    )
    assert contact["id"] in [c["id"] for c in filtered["items"]]


def test_moving_a_contact_between_accounts(api, auth, world) -> None:
    a1, a2 = str(world.accounts["A1"]), str(world.accounts["A2"])
    contact = new_contact(api, auth, "alpha.agent1", account_id=a1, is_primary=True)
    url = f"{CONTACTS}/{contact['id']}"
    hidden = api.patch(url, json={"version": 1, "account_id": a2}, headers=auth("alpha.agent1"))
    assert code_of(hidden) == (404, "account_not_found")  # agent1 can't see A2

    moved = ok(api.patch(url, json={"version": 1, "account_id": a2}, headers=auth("alpha.manager")))
    assert (moved["account_id"], moved["is_primary"]) == (a2, False)
    a1_events = ok(api.get(f"{ACCOUNTS}/{a1}/timeline", headers=auth("alpha.manager")))
    a2_events = ok(api.get(f"{ACCOUNTS}/{a2}/timeline", headers=auth("alpha.manager")))
    assert a1_events[0]["title"] == "Contact removed"
    assert a2_events[0]["title"] == "Contact added"
    # Agent1 still sees it: they own the contact, even though it moved to agent2's account.
    assert api.get(url, headers=auth("alpha.agent1")).status_code == 200


def test_who_may_not_edit_a_contact(api, auth, world) -> None:
    contact = new_contact(api, auth, "alpha.agent1")
    url = f"{CONTACTS}/{contact['id']}"
    change = {"version": 1, "job_title": "CEO"}
    assert api.patch(url, json=change, headers=auth("alpha.agent2")).status_code == 404
    assert api.patch(url, json=change, headers=auth("beta.admin")).status_code == 404
    reassign = {"version": 1, "owner_id": uid(world, "alpha.agent2")}
    assert api.patch(url, json=reassign, headers=auth("alpha.agent1")).status_code == 403
    stale = api.patch(url, json={"version": 9, "job_title": "X"}, headers=auth("alpha.agent1"))
    assert code_of(stale) == (409, "version_conflict")


def test_archiving_a_contact(api, auth, world) -> None:
    a1 = str(world.accounts["A1"])
    contact = new_contact(api, auth, "alpha.agent1", account_id=a1)
    url = f"{CONTACTS}/{contact['id']}"
    response = api.post(
        f"{url}/archive",
        json={"version": 1, "reason": "Left the company"},
        headers=auth("alpha.agent1"),
    )
    assert response.status_code == 204
    assert api.get(url, headers=auth("alpha.agent1")).status_code == 404
    assert ok(api.get(CONTACTS, headers=auth("alpha.agent1")))["total"] == 0
    timeline = ok(api.get(f"{ACCOUNTS}/{a1}/timeline", headers=auth("alpha.agent1")))
    assert timeline[0]["title"] == "Contact removed"


def test_contact_search(api, auth, world) -> None:
    new_contact(api, auth, "alpha.agent1", last_name="Findme", email="unique@example.test")
    new_contact(api, auth, "alpha.agent1", last_name="Other", phone="+1 555 0100")
    agent = auth("alpha.agent1")

    def found(q: str) -> list[str]:
        return [
            c["last_name"] for c in ok(api.get(CONTACTS, params={"q": q}, headers=agent))["items"]
        ]

    assert found("UNIQUE@") == ["Findme"]
    assert found("555 01") == ["Other"]
    assert found("%") == []  # LIKE wildcards are matched literally
    assert api.get(CONTACTS, params={"sort": "evil"}, headers=agent).status_code == 422


# === Opportunities (read-only) ====================================================================


def test_opportunities_follow_the_opportunity_policy(api, auth, world) -> None:
    url = "/api/v1/opportunities"

    def names(user: str, **params: Any) -> list[str]:
        return [o["name"] for o in ok(api.get(url, params=params, headers=auth(user)))["items"]]

    assert names("alpha.agent1") == ["Deal O1"]
    assert sorted(names("alpha.manager")) == ["Deal O1", "Deal O2"]
    assert names("alpha.manager", account_id=str(world.accounts["A2"])) == ["Deal O2"]
    assert names("beta.admin") == ["Deal OB"]
    one = ok(api.get(f"{url}/{world.opportunities['O1']}", headers=auth("alpha.agent1")))
    assert (one["amount"], one["currency"]) == ("1000.00", "EUR")
    assert (
        api.get(f"{url}/{world.opportunities['O2']}", headers=auth("alpha.agent1")).status_code
        == 404
    )
    assert (
        api.get(f"{url}/{world.opportunities['O1']}", headers=auth("beta.admin")).status_code == 404
    )
    assert api.get(url, headers=auth("alpha.support")).status_code == 403
    assert api.get(url, headers=auth("alpha.customer")).status_code == 403


def test_a_child_cannot_be_restored_under_an_archived_parent(api, auth, world) -> None:
    manager = auth("alpha.manager")
    parent = new_account(api, auth, "alpha.manager", name="Parent Co")
    child = new_account(api, auth, "alpha.manager", name="Child Co", parent_account_id=parent["id"])
    for account in (child, parent):  # children first: a parent with live children can't go
        url = f"{ACCOUNTS}/{account['id']}"
        ok(api.post(f"{url}/status", json={"version": 1, "status": "inactive"}, headers=manager))
        ok(api.post(f"{url}/archive", json={"version": 2, "reason": "Closed"}, headers=manager))
    response = api.post(f"{ACCOUNTS}/{child['id']}/restore", json={"version": 3}, headers=manager)
    assert code_of(response) == (409, "account_state")
    ok(api.post(f"{ACCOUNTS}/{parent['id']}/restore", json={"version": 3}, headers=manager))
    ok(api.post(f"{ACCOUNTS}/{child['id']}/restore", json={"version": 3}, headers=manager))


def test_account_write_policy_on_its_own(world) -> None:
    """Defence in depth: a role that could READ every account but WRITE only its own (none
    exists today) must still be refused on someone else's account."""
    from app.core.auth.principal import Principal
    from app.core.auth.rbac import Permission
    from app.modules.accounts.policies import can_write

    agent = world.users["alpha.agent1"]
    principal = Principal(
        subject=agent.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset(),
        permissions=frozenset({Permission.ACCOUNT_READ_ALL, Permission.ACCOUNT_WRITE_OWN}),
        user_id=agent.id,
        tenant_id=agent.tenant_id,
    )
    mine = Account(tenant_id=agent.tenant_id, name="Mine", owner_id=agent.id)
    theirs = Account(
        tenant_id=agent.tenant_id, name="Theirs", owner_id=world.users["alpha.agent2"].id
    )
    assert (can_write(principal, mine), can_write(principal, theirs)) == (True, False)
