"""DB isolation for customer assistant tools."""

from collections.abc import Iterable

import pytest

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import NotFoundError
from app.modules.assistant import tools
from app.modules.catalog import api as catalog_api
from app.modules.contacts import api as contacts_api
from app.modules.quotes import api as quotes_api
from tests.db.test_quotes_api import (  # noqa: F401
    api,
    auth,
    new_quote,
    ok,
    step,
    to_sent,
    world,
)


def _customer(world, user: str, tenant: str, permissions: Iterable[Permission]) -> Principal:  # noqa: F811
    return Principal(
        subject=f"sub-{user}",
        issuer="test",
        user_type="customer",
        roles=frozenset(),
        permissions=frozenset(permissions),
        user_id=world.users[user].id,
        tenant_id=world.users[f"{tenant}.admin"].tenant_id,
    )


def test_get_my_quote_tool_hides_another_customers_quote(api, auth, world, db_session):  # noqa: F811
    mine = to_sent(api, auth, world)
    other = new_quote(api, auth, world, user="alpha.agent2", account="A2")
    other = ok(step(api, auth, "alpha.agent2", other, "submit"))
    other = ok(step(api, auth, "alpha.agent2", other, "send"))
    principal = _customer(world, "alpha.customer", "alpha", {Permission.PORTAL_QUOTE_READ})

    assert quotes_api.customer_quote(db_session, principal, __import__("uuid").UUID(mine["id"]))
    with pytest.raises(NotFoundError):
        quotes_api.customer_quote(db_session, principal, __import__("uuid").UUID(other["id"]))

    result = tools.execute(
        db_session, principal, "get_my_quote", {"quote_id": other["id"]}, lambda *_: None
    )
    assert result.is_error
    assert other["id"] not in result.content


def test_product_and_contact_results_are_customer_safe(api, auth, world, db_session):  # noqa: F811
    principal = _customer(world, "alpha.customer", "alpha", set())

    products = catalog_api.customer_products(db_session, principal)
    assert products
    assert set(products[0]) == {"sku", "name", "description", "unit", "tax_rate"}

    contacts = contacts_api.customer_contacts(db_session, principal)
    assert contacts
    assert set(contacts[0]) == {"name", "email", "phone", "job_title", "account_id"}
    assert all(row["account_id"] is not None for row in contacts)


def test_other_tenant_products_and_contacts_are_not_visible(api, auth, world, db_session):  # noqa: F811
    alpha = _customer(world, "alpha.customer", "alpha", set())
    beta = _customer(world, "beta.admin", "beta", set())

    alpha_products = catalog_api.customer_products(db_session, alpha)
    beta_products = catalog_api.customer_products(db_session, beta)
    assert alpha_products and beta_products
    assert {p["sku"] for p in alpha_products}.isdisjoint({p["sku"] for p in beta_products})

    alpha_contacts = contacts_api.customer_contacts(db_session, alpha)
    assert all(row["account_id"] is not None for row in alpha_contacts)
    beta_account_ids = {
        str(world.ids["B1"]),
    }
    assert not any(row["account_id"] in beta_account_ids for row in alpha_contacts)
