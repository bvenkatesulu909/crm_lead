"""Phase E1 - catalogue (products, price books) and quotes, through the real API and PostgreSQL
(rolled back after each test).

tenant ALPHA: admin, manager, manager2, agent1 (owns A1, contact C1, deal O1), agent2 (owns
              A2, deal O2), support, customer -> A1, customer2 -> A2
tenant BETA:  admin, agent (owns B1), with its own product and price book
Catalogue: P1 widget 100.00 EUR (19 % tax), P2 service 80.00 EUR, P3 inactive 10.00 EUR;
           USD book with P1 only.
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.catalog.models import PriceBook, PriceBookEntry, Product
from app.modules.contacts.models import Contact
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.quotes.models import Quote
from app.modules.sales.models import Opportunity
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for

PEOPLE = {
    "alpha.admin": ("alpha", "tenant_admin"),
    "alpha.manager": ("alpha", "sales_manager"),
    "alpha.manager2": ("alpha", "sales_manager"),
    "alpha.agent1": ("alpha", "sales_agent"),
    "alpha.agent2": ("alpha", "sales_agent"),
    "alpha.support": ("alpha", "support_agent"),
    "alpha.customer": ("alpha", "customer"),
    "alpha.customer2": ("alpha", "customer"),
    "beta.admin": ("beta", "tenant_admin"),
    "beta.agent": ("beta", "sales_agent"),
}
Headers = Callable[[str], dict[str, str]]
QUOTES = "/api/v1/quotes"
PORTAL = "/api/v1/portal/quotes"
D = Decimal


class World:
    users: dict[str, User]
    ids: dict[str, uuid.UUID]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    tenants: dict[str, uuid.UUID] = {}
    for slug in ("alpha", "beta"):
        new_tenant = Tenant(slug=f"{slug}-quotes", name=f"{slug.title()} Quotes Test")
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

    def add(key: str, obj: Any) -> None:
        db_session.add(obj)
        db_session.flush()
        w.ids[key] = obj.id

    alpha, beta = tenants["alpha"], tenants["beta"]
    u = {n: x.id for n, x in w.users.items()}
    add("A1", Account(tenant_id=alpha, name="Quote A1", owner_id=u["alpha.agent1"]))
    add("A2", Account(tenant_id=alpha, name="Quote A2", owner_id=u["alpha.agent2"]))
    add("B1", Account(tenant_id=beta, name="Quote B1", owner_id=u["beta.agent"]))
    add(
        "C1",
        Contact(
            tenant_id=alpha, last_name="C1", account_id=w.ids["A1"], owner_id=u["alpha.agent1"]
        ),
    )
    add(
        "C2",
        Contact(
            tenant_id=alpha, last_name="C2", account_id=w.ids["A2"], owner_id=u["alpha.agent2"]
        ),
    )
    for key, account, owner in [("O1", "A1", "alpha.agent1"), ("O2", "A2", "alpha.agent2")]:
        add(
            key,
            Opportunity(
                tenant_id=alpha,
                name=key,
                account_id=w.ids[account],
                owner_id=u[owner],
                currency="EUR",
            ),
        )
    for customer, account in [("alpha.customer", "A1"), ("alpha.customer2", "A2")]:
        db_session.add(
            PortalAccessGrant(tenant_id=alpha, user_id=u[customer], account_id=w.ids[account])
        )
    add("P1", Product(tenant_id=alpha, sku="WID-1", name="Widget", tax_rate=D("19")))
    add(
        "P2",
        Product(
            tenant_id=alpha,
            sku="SVC-1",
            name="Installation",
            product_type="service",
            unit="hour",
            tax_rate=D("19"),
        ),
    )
    add("P3", Product(tenant_id=alpha, sku="OLD-1", name="Old thing", is_active=False))
    add("PB", Product(tenant_id=beta, sku="BETA-1", name="Beta product"))
    add("EUR", PriceBook(tenant_id=alpha, name="Standard EUR", currency="EUR", is_default=True))
    add("USD", PriceBook(tenant_id=alpha, name="Standard USD", currency="USD"))
    add("BBOOK", PriceBook(tenant_id=beta, name="Beta EUR", currency="EUR"))
    for book, product, price in [
        ("EUR", "P1", "100.00"),
        ("EUR", "P2", "80.00"),
        ("EUR", "P3", "10.00"),
        ("USD", "P1", "120.00"),
        ("BBOOK", "PB", "5.00"),
    ]:
        tenant = beta if book == "BBOOK" else alpha
        db_session.add(
            PriceBookEntry(
                tenant_id=tenant,
                price_book_id=w.ids[book],
                product_id=w.ids[product],
                unit_price=D(price),
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


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def code_of(response: Any) -> tuple[int, str | None]:
    body = response.json() if response.content else {}
    return response.status_code, body.get("code")


def lines(world: World, *items: tuple[str, str, str]) -> list[dict[str, str]]:
    return [
        {"product_id": str(world.ids[p]), "quantity": q, "discount_percent": d} for p, q, d in items
    ]


def new_quote(
    api: TestClient,
    auth: Headers,
    world: World,
    user: str = "alpha.agent1",
    account: str = "A1",
    book: str = "EUR",
    **extra: Any,
) -> Any:
    body = {
        "account_id": str(world.ids[account]),
        "title": "50 widgets",
        "price_book_id": str(world.ids[book]),
        "lines": lines(world, ("P1", "3", "5"), ("P2", "1.5", "0")),
        **extra,
    }
    return ok(api.post(QUOTES, json=body, headers=auth(user)), 201)


def step(api: TestClient, auth: Headers, user: str, quote: Any, action: str, **body: Any) -> Any:
    return api.post(
        f"{QUOTES}/{quote['id']}/{action}",
        json={"version": quote["version"], **body},
        headers=auth(user),
    )


def to_sent(api: TestClient, auth: Headers, world: World, **extra: Any) -> Any:
    quote = new_quote(api, auth, world, **extra)
    quote = ok(step(api, auth, "alpha.agent1", quote, "submit"))
    return ok(step(api, auth, "alpha.agent1", quote, "send"))


# === Catalogue ====================================================================================


def test_catalogue_is_read_by_staff_and_maintained_by_managers(
    api, auth, world, db_session
) -> None:
    for user in ("alpha.agent1", "alpha.support", "alpha.manager"):
        names = [p["name"] for p in ok(api.get("/api/v1/products", headers=auth(user)))["items"]]
        assert names == ["Installation", "Old thing", "Widget"]
    active = ok(api.get("/api/v1/products", params={"active": True}, headers=auth("alpha.agent1")))
    assert [p["sku"] for p in active["items"]] == ["SVC-1", "WID-1"]
    assert api.get("/api/v1/products", headers=auth("alpha.customer")).status_code == 403

    body = {"sku": "NEW-1", "name": "New", "tax_rate": "7"}
    assert api.post("/api/v1/products", json=body, headers=auth("alpha.agent1")).status_code == 403
    created = ok(api.post("/api/v1/products", json=body, headers=auth("alpha.manager")), 201)
    assert (created["unit"], created["product_type"], created["tax_rate"]) == (
        "each",
        "product",
        "7.00",
    )
    dup = api.post("/api/v1/products", json={**body, "sku": "new-1"}, headers=auth("alpha.manager"))
    assert code_of(dup) == (409, "already_exists")
    ok(
        api.post("/api/v1/products", json=body, headers=auth("beta.admin")), 201
    )  # other tenant: fine
    for bad in (
        {"sku": "a b", "name": "x"},
        {"sku": "X", "name": "x", "tax_rate": "101"},
        {"sku": "X"},
    ):
        assert (
            api.post("/api/v1/products", json=bad, headers=auth("alpha.manager")).status_code == 422
        )
    url = f"/api/v1/products/{world.ids['P1']}"
    assert api.get(url, headers=auth("beta.admin")).status_code == 404
    off = ok(api.patch(url, json={"version": 1, "is_active": False}, headers=auth("alpha.manager")))
    assert off["is_active"] is False


def test_prices_are_governed_and_audited(api, auth, world, db_session) -> None:
    book = f"/api/v1/price-books/{world.ids['EUR']}"
    prices = ok(api.get(f"{book}/prices", headers=auth("alpha.agent1")))
    assert [(p["sku"], p["unit_price"]) for p in prices] == [
        ("SVC-1", "80.00"),
        ("OLD-1", "10.00"),
        ("WID-1", "100.00"),
    ]
    put = f"{book}/prices/{world.ids['P1']}"
    assert (
        api.put(put, json={"unit_price": "1.00"}, headers=auth("alpha.agent1")).status_code == 403
    )
    assert api.put(put, json={"unit_price": "-1"}, headers=auth("alpha.manager")).status_code == 422
    assert (
        api.put(put, json={"unit_price": "110.00"}, headers=auth("alpha.manager")).status_code
        == 204
    )
    audit = db_session.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == world.ids["EUR"], AuditLog.action == "price.changed"
        )
    ).all()
    assert audit[-1].changes["unit_price"] == {"old": "100.00", "new": "110.00"}
    beta_book = f"/api/v1/price-books/{world.ids['BBOOK']}/prices/{world.ids['P1']}"
    assert (
        api.put(beta_book, json={"unit_price": "1"}, headers=auth("alpha.manager")).status_code
        == 404
    )


def test_one_default_price_book_per_currency(api, auth, world) -> None:
    created = ok(
        api.post(
            "/api/v1/price-books",
            json={"name": "Partner EUR", "currency": "EUR", "is_default": True},
            headers=auth("alpha.manager"),
        ),
        201,
    )
    books = {b["name"]: b for b in ok(api.get("/api/v1/price-books", headers=auth("alpha.agent1")))}
    assert (books["Partner EUR"]["is_default"], books["Standard EUR"]["is_default"]) == (
        True,
        False,
    )
    assert books["Standard USD"]["is_default"] is False
    again = api.post(
        "/api/v1/price-books",
        json={"name": "partner eur", "currency": "EUR"},
        headers=auth("alpha.manager"),
    )
    assert code_of(again) == (409, "already_exists")
    assert created["currency"] == "EUR"


# === Quotes: create and price ===================================================================


def test_server_prices_the_quote_from_the_price_book(api, auth, world) -> None:
    quote = new_quote(
        api, auth, world, opportunity_id=str(world.ids["O1"]), contact_id=str(world.ids["C1"])
    )
    assert (quote["status"], quote["revision"], quote["currency"]) == ("draft", 1, "EUR")
    assert quote["owner_id"] == str(world.users["alpha.agent1"].id)
    first, second = quote["lines"]
    assert (first["sku"], first["list_price"], first["net_unit_price"], first["line_subtotal"]) == (
        "WID-1",
        "100.00",
        "95.00",
        "285.00",
    )
    assert (second["description"], second["unit"], second["line_subtotal"]) == (
        "Installation",
        "hour",
        "120.00",
    )
    assert (quote["gross_total"], quote["discount_total"], quote["subtotal"]) == (
        "420.00",
        "15.00",
        "405.00",
    )
    assert (quote["tax_total"], quote["total"]) == ("76.95", "481.95")
    assert (quote["needs_approval"], quote["max_discount_percent"]) == (False, "5.00")
    assert datetime.fromisoformat(quote["valid_until"]).date() == datetime.now(
        UTC
    ).date() + timedelta(days=30)


@pytest.mark.parametrize(
    "line",
    [
        {"unit_price": "1.00"},  # prices are never accepted from the client
        {"line_total": "1.00"},
        {"discount_percent": "101"},
        {"quantity": "0"},
    ],
)
def test_clients_cannot_set_prices_or_bad_values(api, auth, world, line) -> None:
    body = {
        "account_id": str(world.ids["A1"]),
        "title": "x",
        "price_book_id": str(world.ids["EUR"]),
        "lines": [{"product_id": str(world.ids["P1"]), "quantity": "1", **line}],
    }
    assert api.post(QUOTES, json=body, headers=auth("alpha.agent1")).status_code == 422


@pytest.mark.parametrize(
    ("user", "change", "expected"),
    [
        ("alpha.agent1", {"account": "A2"}, (404, "related_not_found")),  # colleague's account
        ("alpha.manager", {"account": "B1"}, (404, "related_not_found")),  # other tenant
        ("alpha.agent1", {"book": "BBOOK"}, (404, "related_not_found")),  # other tenant's book
        ("alpha.agent1", {"opportunity_id": "O2"}, (404, "related_not_found")),  # hidden deal
        ("alpha.manager", {"opportunity_id": "O2"}, (422, "invalid_quote")),  # other account
        ("alpha.manager", {"contact_id": "C2"}, (422, "invalid_quote")),
        ("alpha.agent1", {"lines": [("P3", "1", "0")]}, (422, "invalid_quote")),  # inactive
        ("alpha.agent1", {"book": "USD", "lines": [("P2", "1", "0")]}, (422, "invalid_quote")),
    ],
)
def test_quote_links_and_lines_are_checked(api, auth, world, user, change, expected) -> None:
    body: dict[str, Any] = {
        "account_id": str(world.ids[change.get("account", "A1")]),
        "title": "x",
        "price_book_id": str(world.ids[change.get("book", "EUR")]),
        "lines": lines(world, *change.get("lines", [("P1", "1", "0")])),
    }
    for link in ("opportunity_id", "contact_id"):
        if link in change:
            body[link] = str(world.ids[change[link]])
    assert code_of(api.post(QUOTES, json=body, headers=auth(user))) == expected


# === Approval ====================================================================================


def test_small_discounts_need_no_approval(api, auth, world) -> None:
    quote = new_quote(api, auth, world)
    submitted = ok(step(api, auth, "alpha.agent1", quote, "submit"))
    assert submitted["status"] == "approved"
    assert submitted["approved_by_user_id"] is None


def test_big_discounts_need_another_manager(api, auth, world) -> None:
    quote = new_quote(api, auth, world, lines=lines(world, ("P1", "1", "15")))
    assert quote["needs_approval"] is True
    pending = ok(step(api, auth, "alpha.agent1", quote, "submit", note="Strategic customer"))
    assert pending["status"] == "pending_approval"
    assert step(api, auth, "alpha.agent1", pending, "approve").status_code == 403
    assert step(api, auth, "alpha.agent1", pending, "send").status_code == 409  # not approved
    approved = ok(step(api, auth, "alpha.manager", pending, "approve", note="OK this time"))
    assert (approved["status"], approved["approved_by_user_id"]) == (
        "approved",
        str(world.users["alpha.manager"].id),
    )


def test_four_eyes_rule_for_managers(api, auth, world) -> None:
    quote = new_quote(api, auth, world, user="alpha.manager", lines=lines(world, ("P1", "1", "20")))
    pending = ok(step(api, auth, "alpha.manager", quote, "submit"))
    assert step(api, auth, "alpha.manager", pending, "approve").status_code == 403
    ok(step(api, auth, "alpha.manager2", pending, "approve"))
    # Tenant admins may approve their own (small organisations have no second approver).
    own = new_quote(api, auth, world, user="alpha.admin", lines=lines(world, ("P1", "1", "20")))
    own = ok(step(api, auth, "alpha.admin", own, "submit"))
    assert ok(step(api, auth, "alpha.admin", own, "approve"))["status"] == "approved"


def test_rejected_quotes_go_back_to_draft_with_the_reason(api, auth, world) -> None:
    quote = new_quote(api, auth, world, lines=lines(world, ("P1", "1", "30")))
    pending = ok(step(api, auth, "alpha.agent1", quote, "submit"))
    assert step(api, auth, "alpha.manager", pending, "reject").status_code == 422  # reason needed
    back = ok(
        step(api, auth, "alpha.manager", pending, "reject", reason="Max 20 % for this customer")
    )
    assert back["status"] == "draft"
    history = ok(api.get(f"{QUOTES}/{quote['id']}/history", headers=auth("alpha.agent1")))
    assert (history[0]["to_status"], history[0]["note"]) == (
        "draft",
        "Returned: Max 20 % for this customer",
    )
    assert [h["to_status"] for h in history] == ["draft", "pending_approval", "draft"]


def test_only_drafts_change_and_submit_reprices(api, auth, world, db_session) -> None:
    quote = new_quote(api, auth, world)
    db_session.execute(
        update(PriceBookEntry)
        .where(
            PriceBookEntry.price_book_id == world.ids["EUR"],
            PriceBookEntry.product_id == world.ids["P1"],
        )
        .values(unit_price=D("200.00"))
    )
    db_session.flush()
    submitted = ok(step(api, auth, "alpha.agent1", quote, "submit"))
    assert submitted["lines"][0]["list_price"] == "200.00"  # current price, not the draft's
    change = {"version": submitted["version"], "title": "New title"}
    assert code_of(
        api.patch(f"{QUOTES}/{quote['id']}", json=change, headers=auth("alpha.agent1"))
    ) == (409, "quote_state")


def test_editing_a_draft_and_who_may(api, auth, world) -> None:
    quote = new_quote(api, auth, world)
    url = f"{QUOTES}/{quote['id']}"
    edited = ok(
        api.patch(
            url,
            json={"version": 1, "lines": lines(world, ("P2", "2", "0"))},
            headers=auth("alpha.agent1"),
        )
    )
    assert (edited["total"], len(edited["lines"])) == ("190.40", 1)
    usd = ok(
        api.patch(
            url,
            json={
                "version": edited["version"],
                "price_book_id": str(world.ids["USD"]),
                "lines": lines(world, ("P1", "1", "0")),
            },
            headers=auth("alpha.agent1"),
        )
    )
    assert (usd["currency"], usd["total"]) == ("USD", "142.80")
    assert (
        api.patch(
            url, json={"version": usd["version"], "title": "x"}, headers=auth("alpha.agent2")
        ).status_code
        == 404
    )
    assert (
        api.patch(
            url, json={"version": usd["version"], "title": "x"}, headers=auth("beta.admin")
        ).status_code
        == 404
    )
    assert (
        api.patch(url, json={"version": 1, "title": "x"}, headers=auth("alpha.agent1")).status_code
        == 409
    )
    assert api.get(url, headers=auth("alpha.support")).status_code == 403


# === Send, decide, convert =======================================================================


def test_accepted_quote_becomes_an_order_once(api, auth, world) -> None:
    sent = to_sent(api, auth, world)
    accepted = ok(step(api, auth, "alpha.agent1", sent, "accept", note="Signed PDF received"))
    assert accepted["status"] == "accepted"
    converted = ok(
        step(api, auth, "alpha.agent1", accepted, "order", customer_reference="PO-77"), 201
    )
    order = ok(api.get(f"/api/v1/orders/{converted['order_id']}", headers=auth("alpha.agent1")))
    assert (order["status"], order["customer_reference"], order["total"]) == (
        "draft",
        "PO-77",
        accepted["total"],
    )
    assert [(line["product_code"], line["unit_price"]) for line in order["lines"]] == [
        ("WID-1", "95.00"),
        ("SVC-1", "80.00"),
    ]
    again = step(api, auth, "alpha.agent1", converted, "order")
    assert code_of(again) == (409, "quote_state")
    found = ok(
        api.get(QUOTES, params={"order_id": converted["order_id"]}, headers=auth("alpha.agent1"))
    )
    assert [q["id"] for q in found["items"]] == [sent["id"]]


def test_only_accepted_quotes_become_orders(api, auth, world) -> None:
    sent = to_sent(api, auth, world)
    assert code_of(step(api, auth, "alpha.agent1", sent, "order")) == (409, "quote_state")


def test_customer_sees_and_answers_only_their_sent_quotes(api, auth, world) -> None:
    draft = new_quote(api, auth, world)
    sent = to_sent(api, auth, world)
    other = new_quote(api, auth, world, user="alpha.agent2", account="A2")
    ok(
        step(
            api, auth, "alpha.agent2", ok(step(api, auth, "alpha.agent2", other, "submit")), "send"
        )
    )
    customer = auth("alpha.customer")
    mine = ok(api.get(PORTAL, headers=customer))
    assert [q["id"] for q in mine["items"]] == [sent["id"]]
    assert api.get(f"{PORTAL}/{draft['id']}", headers=customer).status_code == 404
    assert api.get(f"{PORTAL}/{other['id']}", headers=customer).status_code == 404
    view = ok(api.get(f"{PORTAL}/{sent['id']}", headers=customer))
    assert "internal_note" not in view and "owner_id" not in view and "needs_approval" not in view
    assert len(view["lines"]) == 2
    url = f"{PORTAL}/{sent['id']}"
    assert (
        api.post(f"{url}/decline", json={"version": sent["version"]}, headers=customer).status_code
        == 422
    )
    assert (
        api.post(
            f"{url}/accept", json={"version": sent["version"]}, headers=auth("alpha.customer2")
        ).status_code
        == 404
    )
    assert (
        api.post(
            f"{url}/accept", json={"version": sent["version"]}, headers=auth("alpha.agent1")
        ).status_code
        == 403
    )
    accepted = ok(
        api.post(
            f"{url}/accept", json={"version": sent["version"], "note": "Go ahead"}, headers=customer
        )
    )
    assert (accepted["status"], accepted["decision_note"]) == ("accepted", "Go ahead")
    history = ok(api.get(f"{QUOTES}/{sent['id']}/history", headers=auth("alpha.agent1")))
    assert (history[0]["to_status"], history[0]["actor_name"]) == ("accepted", "alpha.customer")


def test_expired_quotes_cannot_be_accepted(api, auth, world, db_session) -> None:
    sent = to_sent(api, auth, world)
    db_session.execute(
        update(Quote)
        .where(Quote.id == uuid.UUID(sent["id"]))
        .values(valid_until=datetime.now(UTC).date() - timedelta(days=1))
    )
    db_session.flush()
    view = ok(api.get(f"{PORTAL}/{sent['id']}", headers=auth("alpha.customer")))
    assert view["expired"] is True
    response = api.post(
        f"{PORTAL}/{sent['id']}/accept",
        json={"version": view["version"] if "version" in view else sent["version"]},
        headers=auth("alpha.customer"),
    )
    assert code_of(response) == (409, "quote_expired")
    declined = api.post(
        f"{PORTAL}/{sent['id']}/decline",
        json={"version": sent["version"], "reason": "Too late"},
        headers=auth("alpha.customer"),
    )
    assert declined.status_code == 200  # declining is still possible


def test_revisions_supersede_the_old_quote(api, auth, world) -> None:
    sent = to_sent(api, auth, world)
    revised = ok(step(api, auth, "alpha.agent1", sent, "revise"), 201)
    assert (revised["number"], revised["revision"], revised["status"]) == (
        sent["number"],
        2,
        "draft",
    )
    assert revised["revision_of_id"] == sent["id"]
    assert len(revised["lines"]) == 2
    old = ok(api.get(f"{QUOTES}/{sent['id']}", headers=auth("alpha.agent1")))
    assert old["status"] == "superseded"
    listed = ok(
        api.get(QUOTES, params={"account_id": str(world.ids["A1"])}, headers=auth("alpha.agent1"))
    )
    assert [q["revision"] for q in listed["items"]] == [2]
    every = ok(
        api.get(
            QUOTES,
            params={"account_id": str(world.ids["A1"]), "include_superseded": True},
            headers=auth("alpha.agent1"),
        )
    )
    assert sorted(q["revision"] for q in every["items"]) == [1, 2]
    assert code_of(step(api, auth, "alpha.agent1", old, "revise")) == (409, "quote_state")
    # The customer no longer sees the superseded quote.
    assert api.get(f"{PORTAL}/{sent['id']}", headers=auth("alpha.customer")).status_code == 404


def test_quote_lists_respect_ownership_and_tenants(api, auth, world) -> None:
    new_quote(api, auth, world, opportunity_id=str(world.ids["O1"]))
    new_quote(api, auth, world, user="alpha.agent2", account="A2")

    def titles(user: str, **params: Any) -> int:
        total: int = ok(api.get(QUOTES, params=params, headers=auth(user)))["total"]
        return total

    assert (titles("alpha.agent1"), titles("alpha.agent2"), titles("alpha.manager")) == (1, 1, 2)
    assert titles("alpha.manager", opportunity_id=str(world.ids["O1"])) == 1
    assert titles("beta.admin") == 0
    assert api.get(QUOTES, headers=auth("alpha.customer")).status_code == 403
    assert api.get(PORTAL, headers=auth("alpha.manager")).status_code == 403


def test_only_managers_change_the_catalogue_even_inside_the_service(world, db_session) -> None:
    """Defence in depth: the endpoints already refuse agents; the rule itself does too."""
    from app.core.auth.principal import Principal
    from app.core.auth.rbac import Role, permissions_for
    from app.core.errors import ForbiddenError
    from app.modules.catalog.schemas import ProductCreate
    from app.modules.catalog.service import create_product

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
    with pytest.raises(ForbiddenError):
        create_product(db_session, principal, ProductCreate(sku="X-1", name="X"))
