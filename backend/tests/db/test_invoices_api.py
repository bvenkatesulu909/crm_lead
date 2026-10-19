"""Invoices, credit notes and payments - integration tests through the real API and PostgreSQL
(rolled back).

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support,
              customer1 -> A1, customer2 -> A2
tenant BETA:  admin, customer -> B1
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.auth.rbac import Role, permissions_for
from app.core.config import Settings
from app.core.errors import ForbiddenError, NotFoundError
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.invoices import repository as invoice_repository
from app.modules.invoices import service as invoice_service
from app.modules.invoices.api import customer_invoice, customer_invoices
from app.modules.invoices.repository import InvoiceFilters
from app.modules.invoices.rules import INVOICEABLE_ORDER_STATUSES
from app.modules.orders import api as orders_api
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
# 3 x 19.99 @ 19 % = 71.36 ; 1.5 x 80 @ 19 % = 142.80 -> total 214.16
LINES = [
    {"description": "Widget", "quantity": "3", "unit_price": "19.99", "tax_rate": "19"},
    {"description": "Installation", "quantity": "1.5", "unit_price": "80.00", "tax_rate": "19"},
]
TODAY = datetime.now(UTC).date()


class World:
    users: dict[str, User]
    accounts: dict[str, uuid.UUID]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        tenant = Tenant(slug=f"{slug}-billing", name=f"{slug.title()} Billing Test")
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
            tenant_id=tenants[slug], name=f"Billing Account {key}", owner_id=w.users[owner].id
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


def ok(response: Any, code: int = 200) -> dict[str, Any]:
    assert response.status_code == code, response.text
    result: dict[str, Any] = response.json()
    return result


def confirmed_order(
    api: TestClient, auth: Headers, account: uuid.UUID, user: str = "alpha.admin"
) -> dict[str, Any]:
    order = ok(
        api.post(
            "/api/v1/orders", json={"account_id": str(account), "lines": LINES}, headers=auth(user)
        ),
        201,
    )
    return ok(
        api.post(
            f"/api/v1/orders/{order['id']}/status",
            json={"status": "confirmed", "version": order["version"]},
            headers=auth(user),
        )
    )


def draft_invoice(
    api: TestClient, auth: Headers, account: uuid.UUID, user: str = "alpha.admin"
) -> dict[str, Any]:
    tenant_admin = "beta.admin" if user.startswith("beta") else "alpha.admin"
    order = confirmed_order(api, auth, account, tenant_admin)
    return ok(api.post("/api/v1/invoices", json={"order_id": order["id"]}, headers=auth(user)), 201)


def issued_invoice(
    api: TestClient, auth: Headers, account: uuid.UUID, user: str = "alpha.admin", **extra: Any
) -> dict[str, Any]:
    draft = draft_invoice(api, auth, account, user)
    body = {"version": draft["version"], **extra}
    return ok(api.post(f"/api/v1/invoices/{draft['id']}/issue", json=body, headers=auth(user)))


def pay(
    api: TestClient,
    auth: Headers,
    invoice: dict[str, Any],
    amount: str,
    user: str = "alpha.admin",
    **extra: Any,
) -> Any:
    body = {"amount": amount, "received_on": str(TODAY), "method": "bank_transfer", **extra}
    return api.post(f"/api/v1/invoices/{invoice['id']}/payments", json=body, headers=auth(user))


def credit(
    api: TestClient, auth: Headers, invoice: dict[str, Any], amount: str, user: str = "alpha.admin"
) -> Any:
    body = {
        "reason": "Goodwill discount",
        "lines": [{"description": "Discount", "unit_price": amount}],
    }
    return api.post(f"/api/v1/invoices/{invoice['id']}/credit-notes", json=body, headers=auth(user))


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


# --- From order to issued invoice ----------------------------------------------------------


def test_invoice_is_created_from_the_order_as_a_numberless_draft(api, auth, world) -> None:
    invoice = draft_invoice(api, auth, world.accounts["A1"])

    assert (invoice["status"], invoice["number"], invoice["payment_state"]) == (
        "draft",
        None,
        "draft",
    )
    assert [line["line_total"] for line in invoice["lines"]] == ["71.36", "142.80"]
    assert (invoice["total"], invoice["balance_due"]) == ("214.16", "214.16")  # fmt: skip


def test_issue_assigns_gapless_numbers_and_default_due_date(api, auth, world) -> None:
    first = draft_invoice(api, auth, world.accounts["A1"])
    second = draft_invoice(api, auth, world.accounts["A1"])
    url = "/api/v1/invoices/{}/discard"
    ok(api.post(url.format(first["id"]), json={"version": 1}, headers=auth("alpha.admin")))

    issued = ok(
        api.post(
            f"/api/v1/invoices/{second['id']}/issue",
            json={"version": 1},
            headers=auth("alpha.admin"),
        )
    )

    # The discarded draft never used a number, so the first issued invoice is number 1.
    assert (issued["number"], issued["status"], issued["payment_state"]) == (1, "issued", "open")
    assert issued["issue_date"] == str(TODAY)
    assert issued["due_date"] == str(TODAY + timedelta(days=14))
    beta = issued_invoice(api, auth, world.accounts["B1"], "beta.admin")
    assert beta["number"] == 1  # per tenant


def test_one_live_invoice_per_order(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    body = {"order_id": order["id"]}
    first = ok(api.post("/api/v1/invoices", json=body, headers=auth("alpha.admin")), 201)

    again = api.post("/api/v1/invoices", json=body, headers=auth("alpha.admin"))
    assert (again.status_code, again.json()["code"]) == (409, "order_already_invoiced")

    ok(
        api.post(
            f"/api/v1/invoices/{first['id']}/discard",
            json={"version": 1},
            headers=auth("alpha.admin"),
        )
    )
    ok(api.post("/api/v1/invoices", json=body, headers=auth("alpha.admin")), 201)  # freed again


def test_draft_or_cancelled_orders_cannot_be_invoiced(api, auth, world) -> None:
    order = ok(
        api.post(
            "/api/v1/orders",
            json={"account_id": str(world.accounts["A1"]), "lines": LINES},
            headers=auth("alpha.admin"),
        ),
        201,
    )

    response = api.post(
        "/api/v1/invoices", json={"order_id": order["id"]}, headers=auth("alpha.admin")
    )

    assert (response.status_code, response.json()["code"]) == (409, "order_not_invoiceable")


def test_client_cannot_supply_amounts_or_numbers(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    for extra in (
        {"total": "1.00"},
        {"number": 7},
        {"account_id": str(world.accounts["A2"])},
        {"status": "issued"},
    ):
        body = {"order_id": order["id"], **extra}
        assert (
            api.post("/api/v1/invoices", json=body, headers=auth("alpha.admin")).status_code == 422
        )
    draft = draft_invoice(api, auth, world.accounts["A1"])
    body = {"version": 1, "number": 99}
    assert (
        api.post(
            f"/api/v1/invoices/{draft['id']}/issue", json=body, headers=auth("alpha.admin")
        ).status_code
        == 422
    )


@pytest.mark.parametrize("days", [-1, 366])
def test_due_date_must_be_sensible(api, auth, world, days) -> None:
    draft = draft_invoice(api, auth, world.accounts["A1"])
    body = {"version": 1, "due_date": str(TODAY + timedelta(days=days))}

    response = api.post(
        f"/api/v1/invoices/{draft['id']}/issue", json=body, headers=auth("alpha.admin")
    )

    assert response.status_code == 422


def test_issued_invoice_cannot_be_discarded_or_issued_again(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    for action in ("issue", "discard"):
        response = api.post(
            f"/api/v1/invoices/{invoice['id']}/{action}",
            json={"version": invoice["version"]},
            headers=auth("alpha.admin"),
        )
        assert (response.status_code, response.json()["code"]) == (409, "invoice_not_draft")


def test_stale_version_is_rejected(api, auth, world) -> None:
    draft = draft_invoice(api, auth, world.accounts["A1"])

    response = api.post(
        f"/api/v1/invoices/{draft['id']}/issue", json={"version": 9}, headers=auth("alpha.admin")
    )

    assert (response.status_code, response.json()["code"]) == (409, "version_conflict")


# --- Payments and credit notes -------------------------------------------------------------


def test_partial_then_full_payment(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])

    partial = ok(pay(api, auth, invoice, "100.00", reference="BANK-1"), 201)
    assert (partial["amount_paid"], partial["balance_due"], partial["payment_state"]) == (
        "100.00",
        "114.16",
        "partially_paid",
    )
    paid = ok(pay(api, auth, invoice, "114.16"), 201)
    assert (paid["balance_due"], paid["payment_state"]) == ("0.00", "paid")
    assert [p["recorded_by_name"] for p in paid["payments"]] == ["alpha.admin", "alpha.admin"]


def test_overpayment_is_refused(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])

    response = pay(api, auth, invoice, "214.17")

    assert (response.status_code, response.json()["code"]) == (422, "invalid_amount")


@pytest.mark.parametrize(
    "body",
    [
        {"amount": "0"},
        {"amount": "-5"},
        {"amount": "1.001"},
        {"method": "crypto"},
        {"received_on": str(TODAY + timedelta(days=1))},
    ],
)
def test_payment_validation(api, auth, world, body) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    base = {"amount": "10", "received_on": str(TODAY), "method": "cash"}

    response = api.post(
        f"/api/v1/invoices/{invoice['id']}/payments",
        json={**base, **body},
        headers=auth("alpha.admin"),
    )

    assert response.status_code == 422


def test_draft_cannot_be_paid_or_credited(api, auth, world) -> None:
    draft = draft_invoice(api, auth, world.accounts["A1"])

    assert pay(api, auth, draft, "10").json()["code"] == "invoice_not_issued"
    assert credit(api, auth, draft, "10").json()["code"] == "invoice_not_issued"


def test_payment_reversal_restores_the_balance_once(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    paid = ok(pay(api, auth, invoice, "214.16"), 201)
    payment_id = paid["payments"][0]["id"]
    url = f"/api/v1/invoices/{invoice['id']}/payments/{payment_id}/reverse"

    reversed_ = ok(
        api.post(url, json={"reason": "Transfer bounced"}, headers=auth("alpha.admin")), 201
    )

    assert (reversed_["balance_due"], reversed_["amount_paid"], reversed_["payment_state"]) == (
        "214.16",
        "0.00",
        "open",
    )
    assert reversed_["payments"][0]["reversed"] is True
    assert reversed_["payments"][1]["reverses_payment_id"] == payment_id
    again = api.post(url, json={"reason": "Twice"}, headers=auth("alpha.admin"))
    assert (again.status_code, again.json()["code"]) == (409, "payment_not_reversible")
    reversal_url = (
        f"/api/v1/invoices/{invoice['id']}/payments/{reversed_['payments'][1]['id']}/reverse"
    )
    assert (
        api.post(
            reversal_url, json={"reason": "Undo undo"}, headers=auth("alpha.admin")
        ).status_code
        == 409
    )


def test_payment_of_another_invoice_cannot_be_reversed_through_this_one(api, auth, world) -> None:
    mine = issued_invoice(api, auth, world.accounts["A1"])
    other = issued_invoice(api, auth, world.accounts["A2"])
    other_payment = ok(pay(api, auth, other, "10"), 201)["payments"][0]["id"]

    response = api.post(
        f"/api/v1/invoices/{mine['id']}/payments/{other_payment}/reverse",
        json={"reason": "Tamper"},
        headers=auth("alpha.admin"),
    )

    assert response.status_code == 404


def test_credit_note_reduces_the_balance_and_is_numbered(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])

    credited = ok(credit(api, auth, invoice, "14.16"), 201)
    assert (credited["amount_credited"], credited["balance_due"]) == ("14.16", "200.00")
    assert credited["credit_notes"][0]["number"] == 1
    assert credited["credit_notes"][0]["reason"] == "Goodwill discount"
    rest = ok(credit(api, auth, invoice, "200.00"), 201)
    assert (rest["payment_state"], rest["credit_notes"][1]["number"]) == ("credited", 2)


def test_credit_note_cannot_exceed_what_is_unpaid(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    ok(pay(api, auth, invoice, "200.00"), 201)

    response = credit(api, auth, invoice, "14.17")

    assert (response.status_code, response.json()["code"]) == (422, "invalid_amount")


def test_overdue_filter_and_state(api, auth, world, db_session) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"], due_date=str(TODAY))
    paid = issued_invoice(api, auth, world.accounts["A1"])
    ok(pay(api, auth, paid, "214.16"), 201)
    # Issued invoices are frozen (even the due date), so instead of moving the due date into
    # the past, the query and the state are checked as if "today" were tomorrow.
    admin = principal_for(world.users["alpha.admin"], Role.TENANT_ADMIN)
    tomorrow = TODAY + timedelta(days=1)
    overdue, total = invoice_repository.search(
        db_session, admin, InvoiceFilters(state="overdue"), tomorrow
    )
    assert [str(i.id) for i in overdue] == [invoice["id"]] and total == 1
    assert invoice_service.to_summary(overdue[0], tomorrow).payment_state == "overdue"
    unpaid = ok(api.get("/api/v1/invoices?state=unpaid", headers=auth("alpha.admin")))
    assert [i["id"] for i in unpaid["items"]] == [invoice["id"]]
    paid_list = ok(api.get("/api/v1/invoices?state=paid", headers=auth("alpha.admin")))
    assert [i["id"] for i in paid_list["items"]] == [paid["id"]]


def test_search_by_number(api, auth, world) -> None:
    issued_invoice(api, auth, world.accounts["A1"])
    second = issued_invoice(api, auth, world.accounts["A1"])

    found = ok(api.get("/api/v1/invoices?q=INV-0002", headers=auth("alpha.admin")))

    assert [i["id"] for i in found["items"]] == [second["id"]]


def test_audit_trail(api, auth, world, db_session) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    payment_id = ok(pay(api, auth, invoice, "10"), 201)["payments"][0]["id"]
    api.post(
        f"/api/v1/invoices/{invoice['id']}/payments/{payment_id}/reverse",
        json={"reason": "Wrong invoice"},
        headers=auth("alpha.admin"),
    )
    credit(api, auth, invoice, "5")

    actions = db_session.scalars(
        select(AuditLog.action)
        .where(AuditLog.entity_id == uuid.UUID(invoice["id"]))
        .order_by(AuditLog.seq)
    ).all()
    assert actions == ["invoice.created", "invoice.issued", "payment.recorded", "payment.reversed"]
    notes = db_session.scalars(
        select(AuditLog.action).where(AuditLog.entity_type == "credit_note")
    ).all()
    assert notes == ["credit_note.issued"]


# --- Who may see / change ------------------------------------------------------------------


def test_staff_visibility_by_role_and_tenant(api, auth, world) -> None:
    i1 = issued_invoice(api, auth, world.accounts["A1"])["id"]
    i2 = issued_invoice(api, auth, world.accounts["A2"])["id"]
    issued_invoice(api, auth, world.accounts["B1"], "beta.admin")

    def visible(user: str) -> set[str]:
        page = ok(api.get("/api/v1/invoices", headers=auth(user)))
        assert page["total"] == len(page["items"])
        return {i["id"] for i in page["items"]}

    assert visible("alpha.admin") == {i1, i2}
    assert visible("alpha.manager") == {i1, i2}
    assert visible("alpha.support") == {i1, i2}
    assert visible("alpha.agent1") == {i1}
    assert api.get(f"/api/v1/invoices/{i2}", headers=auth("alpha.agent1")).status_code == 404
    assert api.get(f"/api/v1/invoices/{i1}", headers=auth("beta.admin")).status_code == 404


@pytest.mark.parametrize("user", ["alpha.agent1", "alpha.support"])
def test_read_only_roles_cannot_bill(api, auth, world, user) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    invoice = issued_invoice(api, auth, world.accounts["A1"])

    assert (
        api.post("/api/v1/invoices", json={"order_id": order["id"]}, headers=auth(user)).status_code
        == 403
    )
    assert pay(api, auth, invoice, "10", user).status_code == 403
    assert credit(api, auth, invoice, "10", user).status_code == 403


def test_other_tenant_cannot_bill_or_pay(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    invoice = issued_invoice(api, auth, world.accounts["A1"])

    response = api.post(
        "/api/v1/invoices", json={"order_id": order["id"]}, headers=auth("beta.admin")
    )
    assert response.status_code == 404
    assert pay(api, auth, invoice, "10", "beta.admin").status_code == 404
    assert credit(api, auth, invoice, "10", "beta.admin").status_code == 404


def test_super_admin_sees_no_invoices(api, token_factory, world) -> None:
    headers = bearer(token_factory.mint("sub-platform-billing", ["super_admin"]))
    assert api.get("/api/v1/invoices", headers=headers).status_code in (401, 403)


# --- Customer portal -----------------------------------------------------------------------


def test_customer_sees_only_issued_invoices_of_own_accounts(api, auth, world) -> None:
    draft = draft_invoice(api, auth, world.accounts["A1"])
    mine = issued_invoice(api, auth, world.accounts["A1"])
    theirs = issued_invoice(api, auth, world.accounts["A2"])

    listed = api.get("/api/v1/portal/invoices", headers=auth("alpha.customer1")).json()

    assert [i["id"] for i in listed] == [mine["id"]]
    for invoice_id, user in [
        (draft["id"], "alpha.customer1"),
        (theirs["id"], "alpha.customer1"),
        (mine["id"], "beta.customer"),
    ]:
        assert (
            api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=auth(user)).status_code == 404
        )


def test_customer_view_hides_staff_details_and_reversed_payments(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    bounced = ok(pay(api, auth, invoice, "50"), 201)["payments"][0]["id"]
    api.post(
        f"/api/v1/invoices/{invoice['id']}/payments/{bounced}/reverse",
        json={"reason": "Bounced - customer flagged risky"},
        headers=auth("alpha.admin"),
    )
    ok(pay(api, auth, invoice, "100", reference="BANK-77"), 201)
    credit(api, auth, invoice, "4.16")

    response = api.get(f"/api/v1/portal/invoices/{invoice['id']}", headers=auth("alpha.customer1"))
    body = ok(response)

    assert (body["balance_due"], body["payment_state"]) == ("110.00", "partially_paid")
    assert [(p["amount"], p["reference"]) for p in body["payments"]] == [("100.00", "BANK-77")]
    assert body["credit_notes"][0]["reason"] == "Goodwill discount"
    for hidden in ("created_by_user_id", "version", "status", "issued_at"):
        assert hidden not in body
    assert "risky" not in response.text
    assert "recorded_by" not in response.text


def test_customer_and_staff_apis_reject_each_other(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])

    assert api.get("/api/v1/invoices", headers=auth("alpha.customer1")).status_code == 403
    assert pay(api, auth, invoice, "10", "alpha.customer1").status_code == 403
    assert api.get("/api/v1/portal/invoices", headers=auth("alpha.admin")).status_code == 403


# --- Order invoice lock --------------------------------------------------------------------


def order_of(api: TestClient, auth: Headers, invoice: dict[str, Any], user: str) -> dict[str, Any]:
    return ok(api.get(f"/api/v1/orders/{invoice['order_id']}", headers=auth(user)))


def cancel(api: TestClient, auth: Headers, order: dict[str, Any], user: str = "alpha.admin") -> Any:
    body = {"status": "cancelled", "version": order["version"], "reason": "Customer request"}
    return api.post(f"/api/v1/orders/{order['id']}/status", json=body, headers=auth(user))


@pytest.mark.parametrize("make", [draft_invoice, issued_invoice])
def test_invoiced_order_cannot_be_cancelled(api, auth, world, make) -> None:
    invoice = make(api, auth, world.accounts["A1"])
    order = order_of(api, auth, invoice, "alpha.admin")

    response = cancel(api, auth, order)

    assert (response.status_code, response.json()["code"]) == (409, "order_invoiced")
    assert order_of(api, auth, invoice, "alpha.admin")["status"] == "confirmed"


def test_discarding_the_draft_releases_the_order(api, auth, world, db_session) -> None:
    draft = draft_invoice(api, auth, world.accounts["A1"])
    order = order_of(api, auth, draft, "alpha.admin")
    ok(
        api.post(
            f"/api/v1/invoices/{draft['id']}/discard",
            json={"version": draft["version"]},
            headers=auth("alpha.admin"),
        )
    )

    cancelled = ok(cancel(api, auth, order))

    assert cancelled["status"] == "cancelled"
    invoiced_at = db_session.scalar(
        text("SELECT invoiced_at FROM orders WHERE id = :id"), {"id": order["id"]}
    )
    assert invoiced_at is None


def test_invoicing_does_not_invalidate_an_open_order_page(api, auth, world) -> None:
    order = confirmed_order(api, auth, world.accounts["A1"])
    ok(
        api.post("/api/v1/invoices", json={"order_id": order["id"]}, headers=auth("alpha.admin")),
        201,
    )

    # The order page loaded before the invoice still has the right version for fulfilment.
    body = {"status": "in_fulfilment", "version": order["version"]}
    moved = ok(
        api.post(f"/api/v1/orders/{order['id']}/status", json=body, headers=auth("alpha.admin"))
    )
    assert moved["status"] == "in_fulfilment"


def test_order_cancelled_meanwhile_is_not_invoiced(api, auth, world, db_session) -> None:
    """The race "cancel" vs "invoice": the lock is only taken on a still-invoiceable order."""
    order = confirmed_order(api, auth, world.accounts["A1"])
    ok(cancel(api, auth, order))
    admin = principal_for(world.users["alpha.admin"], Role.TENANT_ADMIN)

    assert not orders_api.mark_invoiced(
        db_session, admin, uuid.UUID(order["id"]), statuses=INVOICEABLE_ORDER_STATUSES
    )


def test_invoice_lock_respects_tenants(api, auth, world, db_session) -> None:
    alpha = draft_invoice(api, auth, world.accounts["A1"])
    alpha_order = order_of(api, auth, alpha, "alpha.admin")
    beta = draft_invoice(api, auth, world.accounts["B1"], "beta.admin")
    beta_order = order_of(api, auth, beta, "beta.admin")
    beta_admin = principal_for(world.users["beta.admin"], Role.TENANT_ADMIN)

    # Another tenant can neither cancel (looks missing) nor lock/unlock the order.
    assert cancel(api, auth, alpha_order, "beta.admin").status_code == 404
    other = uuid.UUID(alpha_order["id"])
    assert not orders_api.mark_invoiced(
        db_session, beta_admin, other, statuses=INVOICEABLE_ORDER_STATUSES
    )
    orders_api.release_invoiced(db_session, world.users["beta.admin"].tenant_id, other)
    assert cancel(api, auth, alpha_order).json()["code"] == "order_invoiced"
    # Discarding beta's draft frees only beta's order.
    ok(
        api.post(
            f"/api/v1/invoices/{beta['id']}/discard",
            json={"version": beta["version"]},
            headers=auth("beta.admin"),
        )
    )
    assert ok(cancel(api, auth, beta_order, "beta.admin"))["status"] == "cancelled"
    assert cancel(api, auth, alpha_order).json()["code"] == "order_invoiced"


# --- Database guarantees -------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE invoices SET total = total + 1, balance_due = balance_due + 1 "
        "WHERE status = 'issued'",
        "UPDATE invoices SET due_date = due_date + 30 WHERE status = 'issued'",
        "UPDATE invoices SET number = number + 100 WHERE status = 'issued'",
        "UPDATE invoices SET status = 'draft', number = NULL WHERE status = 'issued'",
    ],
)
def test_database_freezes_issued_invoices(api, auth, world, db_session, statement) -> None:
    issued_invoice(api, auth, world.accounts["A1"])

    with pytest.raises(DBAPIError, match="cannot be changed"), db_session.begin_nested():
        db_session.execute(text(statement))


def test_database_still_allows_balance_updates(api, auth, world, db_session) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    with db_session.begin_nested():
        db_session.execute(
            text("UPDATE invoices SET amount_paid = 1, balance_due = total - 1 WHERE id = :id"),
            {"id": invoice["id"]},
        )


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM invoices",
        "UPDATE invoice_lines SET unit_price = 0",
        "DELETE FROM payments",
        "UPDATE payments SET amount = 1",
        "UPDATE credit_notes SET total = 1",
        "DELETE FROM credit_note_lines",
    ],
)
def test_billing_records_are_insert_only(app_engine, statement) -> None:
    with (
        app_engine.connect() as connection,
        pytest.raises(ProgrammingError, match="permission denied"),
    ):
        connection.execute(text(statement))


def test_database_rejects_inconsistent_balance(api, auth, world, db_session) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])

    with pytest.raises(DBAPIError, match="balance_consistent"), db_session.begin_nested():
        db_session.execute(
            text("UPDATE invoices SET amount_paid = 5 WHERE id = :id"), {"id": invoice["id"]}
        )


def test_database_rejects_a_cancelled_order_with_a_live_invoice(
    api, auth, world, db_session
) -> None:
    invoice = draft_invoice(api, auth, world.accounts["A1"])

    with pytest.raises(DBAPIError, match="not_cancelled_while_invoiced"), db_session.begin_nested():
        db_session.execute(
            text(
                "UPDATE orders SET status = 'cancelled', cancelled_at = now(), "
                "cancellation_reason = 'x' WHERE id = :id"
            ),
            {"id": invoice["order_id"]},
        )


# --- Assistant interface -------------------------------------------------------------------


def test_assistant_reads_invoices_as_the_customer(world, db_session, api, auth) -> None:
    mine = issued_invoice(api, auth, world.accounts["A1"])
    issued_invoice(api, auth, world.accounts["A2"])
    customer = principal_for(world.users["alpha.customer1"], Role.CUSTOMER)

    unpaid = customer_invoices(db_session, customer, state="unpaid")
    detail = customer_invoice(db_session, customer, uuid.UUID(mine["id"]))

    assert [i.id for i in unpaid] == [uuid.UUID(mine["id"])]
    assert str(detail.balance_due) == "214.16"


def test_assistant_cannot_read_another_customers_invoice(world, db_session, api, auth) -> None:
    theirs = issued_invoice(api, auth, world.accounts["A2"])
    customer = principal_for(world.users["alpha.customer1"], Role.CUSTOMER)

    with pytest.raises(NotFoundError):
        customer_invoice(db_session, customer, uuid.UUID(theirs["id"]))
    assert customer_invoices(db_session, customer, account_id=world.accounts["A2"]) == []


def test_assistant_invoice_lookup_only_acts_for_customers(world, db_session) -> None:
    staff = principal_for(world.users["alpha.admin"], Role.TENANT_ADMIN)

    with pytest.raises(ForbiddenError):
        customer_invoices(db_session, staff)


def test_dates_are_plain_dates(api, auth, world) -> None:
    invoice = issued_invoice(api, auth, world.accounts["A1"])
    assert date.fromisoformat(invoice["due_date"]) > date.fromisoformat(invoice["issue_date"])
