"""Orders - integration tests through the real API and PostgreSQL (rolled back).

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support,
              customer1 -> A1, customer2 -> A2
tenant BETA:  admin, customer -> B1
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission, Role, permissions_for
from app.core.config import Settings
from app.core.errors import ForbiddenError, NotFoundError
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.orders import service as order_service
from app.modules.orders.api import customer_order, customer_orders
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for

PEOPLE = {
    "alpha.admin": ("alpha", "tenant_admin"),
    "alpha.manager": ("alpha", "sales_manager"),
    "alpha.agent1": ("alpha", "sales_agent"),
    "alpha.agent2": ("alpha", "sales_agent"),
    "alpha.support": ("alpha", "support_agent"),
    "alpha.customer1": ("alpha", "customer"),
    "alpha.customer2": ("alpha", "customer"),
    "beta.admin": ("beta", "tenant_admin"),
    "beta.customer": ("beta", "customer"),
}
Headers = Callable[[str], dict[str, str]]
LINES = [
    {"product_code": "WID-1", "description": "Widget", "quantity": "3", "unit_price": "19.99",
     "tax_rate": "19"},
    {"description": "Installation", "quantity": "1.5", "unit_price": "80.00", "tax_rate": "19"},
]  # fmt: skip


class World:
    users: dict[str, User]
    accounts: dict[str, uuid.UUID]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        tenant = Tenant(slug=f"{slug}-orders", name=f"{slug.title()} Orders Test")
        db_session.add(tenant)
        db_session.flush()
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
        db_session.add(user)
        w.users[name] = user
    db_session.flush()
    w.accounts = {}
    for key, slug, owner in [
        ("A1", "alpha", "alpha.agent1"),
        ("A2", "alpha", "alpha.agent2"),
        ("B1", "beta", "beta.admin"),
    ]:
        account = Account(
            tenant_id=tenants[slug], name=f"Orders Account {key}", owner_id=w.users[owner].id
        )
        db_session.add(account)
        db_session.flush()
        w.accounts[key] = account.id
    for customer, key in [
        ("alpha.customer1", "A1"),
        ("alpha.customer2", "A2"),
        ("beta.customer", "B1"),
    ]:
        u = w.users[customer]
        db_session.add(
            PortalAccessGrant(tenant_id=u.tenant_id, user_id=u.id, account_id=w.accounts[key])
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


def new_order(
    api: TestClient, auth: Headers, user: str, account: uuid.UUID, **extra: Any
) -> dict[str, Any]:
    body = {"account_id": str(account), "lines": LINES, **extra}
    response = api.post("/api/v1/orders", json=body, headers=auth(user))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def move(
    api: TestClient, auth: Headers, user: str, order: dict[str, Any], status: str, **extra: Any
) -> Any:
    """Change the status with the order's current version; returns the response."""
    current = api.get(f"/api/v1/orders/{order['id']}", headers=auth("alpha.admin")).json()
    body = {"status": status, "version": current["version"], **extra}
    return api.post(f"/api/v1/orders/{order['id']}/status", json=body, headers=auth(user))


def confirmed_order(api: TestClient, auth: Headers, account: uuid.UUID) -> dict[str, Any]:
    order = new_order(api, auth, "alpha.admin", account)
    response = move(api, auth, "alpha.admin", order, "confirmed")
    assert response.status_code == 200, response.text
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


# --- Create and totals ---------------------------------------------------------------------


def test_agent_creates_draft_order_with_server_calculated_totals(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"], customer_reference="PO-778")

    assert (order["number"], order["status"], order["currency"]) == (1, "draft", "EUR")
    # 3 x 19.99 = 59.97 (+11.39 tax); 1.5 x 80 = 120.00 (+22.80 tax)
    assert [line["line_total"] for line in order["lines"]] == ["71.36", "142.80"]
    assert (order["subtotal"], order["tax_total"], order["total"]) == ("179.97", "34.19", "214.16")
    assert order["created_by_user_id"] == str(world.users["alpha.agent1"].id)
    assert [e["to_status"] for e in order["events"]] == ["draft"]
    assert order["version"] == 1


def test_client_cannot_set_server_controlled_fields(api, auth, world) -> None:
    for extra in (
        {"status": "confirmed"},
        {"total": "0.01"},
        {"number": 99},
        {"created_by_user_id": str(world.users["alpha.admin"].id)},
        {"tenant_id": str(uuid.uuid4())},
    ):
        body = {"account_id": str(world.accounts["A1"]), "lines": LINES, **extra}
        response = api.post("/api/v1/orders", json=body, headers=auth("alpha.agent1"))
        assert response.status_code == 422, extra
    line_with_total = [{**LINES[0], "line_total": "1.00"}]
    body = {"account_id": str(world.accounts["A1"]), "lines": line_with_total}
    assert api.post("/api/v1/orders", json=body, headers=auth("alpha.agent1")).status_code == 422


@pytest.mark.parametrize(
    "bad_line",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"unit_price": "-0.01"},
        {"unit_price": "1.001"},  # more than 2 decimals
        {"tax_rate": "101"},
        {"description": "  "},
    ],
)
def test_line_validation(api, auth, world, bad_line) -> None:
    body = {"account_id": str(world.accounts["A1"]), "lines": [{**LINES[0], **bad_line}]}
    response = api.post("/api/v1/orders", json=body, headers=auth("alpha.agent1"))
    assert response.status_code == 422


def test_invalid_currency_is_rejected(api, auth, world) -> None:
    body = {"account_id": str(world.accounts["A1"]), "currency": "euro", "lines": LINES}
    assert api.post("/api/v1/orders", json=body, headers=auth("alpha.admin")).status_code == 422


def test_order_numbers_count_per_tenant(api, auth, world) -> None:
    numbers = [new_order(api, auth, "alpha.admin", world.accounts["A1"])["number"] for _ in "abc"]
    beta = new_order(api, auth, "beta.admin", world.accounts["B1"])["number"]

    assert numbers == [1, 2, 3]
    assert beta == 1


# --- Who may create / see / change ---------------------------------------------------------


@pytest.mark.parametrize("account", ["A2", "B1"])
def test_agent_cannot_order_for_an_account_they_do_not_own(api, auth, world, account) -> None:
    body = {"account_id": str(world.accounts[account]), "lines": LINES}
    assert api.post("/api/v1/orders", json=body, headers=auth("alpha.agent1")).status_code == 404


def test_admin_cannot_order_for_another_tenants_account(api, auth, world) -> None:
    body = {"account_id": str(world.accounts["B1"]), "lines": LINES}
    assert api.post("/api/v1/orders", json=body, headers=auth("alpha.admin")).status_code == 404


def test_staff_visibility_by_role_and_tenant(api, auth, world) -> None:
    o1 = new_order(api, auth, "alpha.agent1", world.accounts["A1"])["id"]
    o2 = new_order(api, auth, "alpha.agent2", world.accounts["A2"])["id"]
    new_order(api, auth, "beta.admin", world.accounts["B1"])

    def visible(user: str) -> set[str]:
        page = api.get("/api/v1/orders", headers=auth(user)).json()
        assert page["total"] == len(page["items"])
        return {o["id"] for o in page["items"]}

    assert visible("alpha.admin") == {o1, o2}
    assert visible("alpha.manager") == {o1, o2}
    assert visible("alpha.support") == {o1, o2}  # support can look orders up for customers
    assert visible("alpha.agent1") == {o1}
    assert api.get(f"/api/v1/orders/{o2}", headers=auth("alpha.agent1")).status_code == 404
    assert api.get(f"/api/v1/orders/{o1}", headers=auth("beta.admin")).status_code == 404


def test_support_can_read_but_not_change_orders(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.admin", world.accounts["A1"])

    body = {"account_id": str(world.accounts["A1"]), "lines": LINES}
    assert (
        api.get(f"/api/v1/orders/{order['id']}", headers=auth("alpha.support")).status_code
        == 200
    )
    assert api.post("/api/v1/orders", json=body, headers=auth("alpha.support")).status_code == 403
    assert move(api, auth, "alpha.support", order, "confirmed").status_code == 403


def test_agent_cannot_change_another_agents_order(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent2", world.accounts["A2"])
    update = {"version": order["version"], "currency": "EUR", "lines": LINES[:1]}

    assert (
        api.put(f"/api/v1/orders/{order['id']}", json=update, headers=auth("alpha.agent1"))
    ).status_code == 404
    assert move(api, auth, "alpha.agent1", order, "cancelled", reason="probe").status_code == 404


def test_other_tenant_cannot_change_order(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.admin", world.accounts["A1"])

    assert move(api, auth, "beta.admin", order, "confirmed").status_code == 404


def test_super_admin_sees_no_orders(api, token_factory, world) -> None:
    headers = bearer(token_factory.mint("sub-platform-orders", ["super_admin"]))
    assert api.get("/api/v1/orders", headers=headers).status_code in (401, 403)


# --- Editing drafts ------------------------------------------------------------------------


def test_draft_can_be_replaced_and_totals_recalculated(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"])
    update = {
        "version": order["version"],
        "currency": "USD",
        "customer_reference": "PO-1",
        "internal_note": "Rush order",
        "lines": [{"description": "Consulting", "quantity": "2", "unit_price": "100.00"}],
    }

    response = api.put(f"/api/v1/orders/{order['id']}", json=update, headers=auth("alpha.agent1"))

    assert response.status_code == 200, response.text
    updated = response.json()
    assert (updated["currency"], updated["total"], len(updated["lines"])) == ("USD", "200.00", 1)
    assert updated["version"] == order["version"] + 1


def test_stale_version_is_rejected(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"])
    update = {"version": order["version"], "currency": "EUR", "lines": LINES[:1]}
    url = f"/api/v1/orders/{order['id']}"
    assert api.put(url, json=update, headers=auth("alpha.agent1")).status_code == 200

    stale = api.put(url, json=update, headers=auth("alpha.agent1"))

    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"


def test_confirmed_order_is_frozen(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    update = {"version": order["version"], "currency": "EUR", "lines": LINES[:1]}

    response = api.put(f"/api/v1/orders/{order['id']}", json=update, headers=auth("alpha.admin"))

    assert response.status_code == 409
    assert response.json()["code"] == "order_not_editable"


def test_empty_order_cannot_be_confirmed(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"], lines=[])

    response = move(api, auth, "alpha.agent1", order, "confirmed")

    assert response.status_code == 409
    assert response.json()["code"] == "order_has_no_lines"


# --- Status lifecycle ----------------------------------------------------------------------


def test_full_lifecycle_with_history_and_audit(api, auth, world, db_session) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"])
    assert move(api, auth, "alpha.agent1", order, "confirmed").status_code == 200
    assert (
        move(api, auth, "alpha.manager", order, "in_fulfilment", note="Picked").status_code == 200
    )
    shipped = move(
        api, auth, "alpha.manager", order, "shipped", tracking_reference="DHL 123456"
    ).json()
    delivered = move(api, auth, "alpha.manager", order, "delivered").json()

    assert shipped["tracking_reference"] == "DHL 123456"
    assert delivered["status"] == "delivered"
    assert all(delivered[k] for k in ("confirmed_at", "shipped_at", "delivered_at"))
    assert [(e["to_status"], e["actor_name"]) for e in delivered["events"]] == [
        ("draft", "alpha.agent1"),
        ("confirmed", "alpha.agent1"),
        ("in_fulfilment", "alpha.manager"),
        ("shipped", "alpha.manager"),
        ("delivered", "alpha.manager"),
    ]
    assert delivered["events"][2]["note"] == "Picked"
    actions = db_session.scalars(
        select(AuditLog.action)
        .where(AuditLog.entity_id == uuid.UUID(order["id"]))
        .order_by(AuditLog.seq)
    ).all()
    assert actions == ["order.created"] + ["order.status_changed"] * 4


@pytest.mark.parametrize("target", ["cancelled", "confirmed", "shipped"])
def test_delivered_is_final(api, auth, world, target) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    move(api, auth, "alpha.admin", order, "shipped")
    move(api, auth, "alpha.admin", order, "delivered")

    extra = {"reason": "Too late"} if target == "cancelled" else {}
    response = move(api, auth, "alpha.admin", order, target, **extra)

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_status_transition"


def test_shipped_order_cannot_be_cancelled(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    move(api, auth, "alpha.admin", order, "shipped")

    assert move(api, auth, "alpha.admin", order, "cancelled", reason="Oops").status_code == 409


def test_cancellation_needs_a_reason_the_customer_sees(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    assert move(api, auth, "alpha.agent1", order, "cancelled").status_code == 422

    cancelled = move(api, auth, "alpha.agent1", order, "cancelled", reason="Customer request")

    assert cancelled.status_code == 200
    portal = api.get(f"/api/v1/portal/orders/{order['id']}", headers=auth("alpha.customer1"))
    assert (portal.json()["status"], portal.json()["cancellation_reason"]) == (
        "cancelled",
        "Customer request",
    )


def test_draft_can_be_cancelled(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"])

    response = move(api, auth, "alpha.agent1", order, "cancelled", reason="Duplicate")

    assert response.status_code == 200
    assert response.json()["confirmed_at"] is None


def test_fields_must_match_the_target_status(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.admin", world.accounts["A1"])
    for extra in ({"reason": "x y z"}, {"tracking_reference": "T1"}):
        assert move(api, auth, "alpha.admin", order, "confirmed", **extra).status_code == 422


def test_agents_cannot_run_fulfilment(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"])
    move(api, auth, "alpha.agent1", order, "confirmed")

    for target in ("in_fulfilment", "shipped"):
        assert move(api, auth, "alpha.agent1", order, target).status_code == 403


def test_order_in_fulfilment_is_cancelled_only_by_fulfilment(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.agent1", world.accounts["A1"])
    move(api, auth, "alpha.agent1", order, "confirmed")
    move(api, auth, "alpha.manager", order, "in_fulfilment")

    assert (
        move(api, auth, "alpha.agent1", order, "cancelled", reason="Changed mind").status_code
        == 403
    )
    by_manager = move(api, auth, "alpha.manager", order, "cancelled", reason="Out of stock")
    assert by_manager.status_code == 200


def test_stale_version_on_status_change(api, auth, world) -> None:
    order = new_order(api, auth, "alpha.admin", world.accounts["A1"])
    body = {"status": "confirmed", "version": order["version"] + 5}

    response = api.post(
        f"/api/v1/orders/{order['id']}/status", json=body, headers=auth("alpha.admin")
    )

    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"


# --- Customer portal -----------------------------------------------------------------------


def test_customer_sees_own_confirmed_orders_without_internal_data(api, auth, world) -> None:
    draft = new_order(api, auth, "alpha.agent1", world.accounts["A1"])
    order = new_order(
        api, auth, "alpha.agent1", world.accounts["A1"], internal_note="Margin is thin"
    )
    move(api, auth, "alpha.agent1", order, "confirmed", note="Secret staff note")

    listed = api.get("/api/v1/portal/orders", headers=auth("alpha.customer1")).json()
    detail = api.get(f"/api/v1/portal/orders/{order['id']}", headers=auth("alpha.customer1"))

    assert [o["id"] for o in listed] == [order["id"]]  # never drafts
    assert api.get(
        f"/api/v1/portal/orders/{draft['id']}", headers=auth("alpha.customer1")
    ).status_code == 404  # fmt: skip
    body = detail.json()
    assert body["total"] == "214.16"
    assert [s["status"] for s in body["timeline"]] == ["confirmed"]
    for hidden in ("internal_note", "created_by_user_id", "events", "version"):
        assert hidden not in body
    assert "Margin is thin" not in detail.text
    assert "Secret staff note" not in detail.text


def test_customer_sees_only_orders_of_own_accounts(api, auth, world) -> None:
    mine = confirmed_order(api, auth, world.accounts["A1"])
    theirs = confirmed_order(api, auth, world.accounts["A2"])

    listed = api.get("/api/v1/portal/orders", headers=auth("alpha.customer1")).json()

    assert [o["id"] for o in listed] == [mine["id"]]
    for user in ("alpha.customer1", "beta.customer"):
        url = f"/api/v1/portal/orders/{theirs['id']}"
        assert api.get(url, headers=auth(user)).status_code == 404
    other_account = api.get(
        f"/api/v1/portal/orders?account_id={world.accounts['A2']}",
        headers=auth("alpha.customer1"),
    )
    assert other_account.json() == []


def test_customer_and_staff_apis_reject_each_other(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])

    assert api.get("/api/v1/orders", headers=auth("alpha.customer1")).status_code == 403
    assert (
        api.get(f"/api/v1/orders/{order['id']}", headers=auth("alpha.customer1")).status_code == 403
    )
    assert move(api, auth, "alpha.customer1", order, "cancelled", reason="x y z").status_code == 403
    assert api.get("/api/v1/portal/orders", headers=auth("alpha.admin")).status_code == 403


# --- Database guarantees -------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    ["UPDATE order_status_events SET note = 'x'", "DELETE FROM order_status_events"],
)
def test_status_history_is_append_only(app_engine, statement) -> None:
    with (
        app_engine.connect() as connection,
        pytest.raises(ProgrammingError, match="permission denied"),
    ):
        connection.execute(text(statement))


def test_database_rejects_inconsistent_totals(api, auth, world, db_session) -> None:
    order = new_order(api, auth, "alpha.admin", world.accounts["A1"])

    with pytest.raises(IntegrityError, match="totals_consistent"), db_session.begin_nested():
        db_session.execute(
            text("UPDATE orders SET total = total + 1 WHERE id = :id"), {"id": order["id"]}
        )


# --- Assistant interface -------------------------------------------------------------------


def test_assistant_reads_orders_as_the_customer(world, db_session, api, auth) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    confirmed_order(api, auth, world.accounts["A2"])
    customer = principal_for(world.users["alpha.customer1"], Role.CUSTOMER)

    found = customer_orders(db_session, customer, q=f"SO-{order['number']}")
    detail = customer_order(db_session, customer, uuid.UUID(order["id"]))

    assert [o.id for o in found] == [uuid.UUID(order["id"])]
    assert detail.status == "confirmed"
    assert not hasattr(detail, "internal_note")


def test_assistant_cannot_read_another_customers_order(world, db_session, api, auth) -> None:
    theirs = confirmed_order(api, auth, world.accounts["A2"])
    customer = principal_for(world.users["alpha.customer1"], Role.CUSTOMER)

    with pytest.raises(NotFoundError):
        customer_order(db_session, customer, uuid.UUID(theirs["id"]))
    assert customer_orders(db_session, customer, account_id=world.accounts["A2"]) == []


def test_assistant_order_lookup_only_acts_for_customers(world, db_session) -> None:
    staff = principal_for(world.users["alpha.admin"], Role.TENANT_ADMIN)

    with pytest.raises(ForbiddenError):
        customer_orders(db_session, staff)


def test_write_scope_is_enforced_even_when_read_scope_is_wider(
    world, db_session, api, auth
) -> None:
    """Defence in depth: a (future) role that may READ every account and order but WRITE
    only for its own accounts must still be refused on someone else's account."""
    theirs = new_order(api, auth, "alpha.admin", world.accounts["A2"])
    user = world.users["alpha.agent1"]
    wide_reader = Principal(
        subject=user.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset({Role.SALES_AGENT}),
        permissions=frozenset(
            {
                Permission.ACCOUNT_READ_ALL,
                Permission.ORDER_READ_ALL,
                Permission.ORDER_WRITE_OWN_ACCOUNTS,
            }
        ),
        user_id=user.id,
        tenant_id=user.tenant_id,
    )

    with pytest.raises(NotFoundError):
        order_service.create_order(
            db_session,
            wide_reader,
            account_id=world.accounts["A2"],
            currency="EUR",
            customer_reference=None,
            expected_delivery_date=None,
            internal_note=None,
            lines=[],
        )
    with pytest.raises(ForbiddenError):
        order_service.change_status(
            db_session,
            wide_reader,
            uuid.UUID(theirs["id"]),
            target="cancelled",
            version=theirs["version"],
            reason="Not mine",
        )
