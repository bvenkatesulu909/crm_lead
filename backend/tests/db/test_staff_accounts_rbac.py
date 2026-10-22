"""DB RBAC/tenant tests for staff account/contact APIs."""

# ruff: noqa: F811 - the imported world fixture is used as a test parameter

import pytest

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ForbiddenError, NotFoundError
from app.modules.accounts import api as accounts_api
from app.modules.contacts import api as contacts_api
from tests.db.test_quotes_api import world  # noqa: F401


def _staff(world, user: str, permissions: set[str]) -> Principal:
    return Principal(
        subject="sub-" + user,
        issuer="test",
        user_type="staff",
        roles=frozenset(),
        permissions=frozenset(permissions),
        user_id=world.users[user].id,
        tenant_id=world.users[user].tenant_id,
    )


def _agent(world) -> Principal:
    return _staff(world, "alpha.agent1", {Permission.ACCOUNT_READ_OWN, Permission.CONTACT_READ_OWN})


def test_search_accounts_is_owner_and_tenant_scoped(world, db_session):
    rows = accounts_api.search_accounts(db_session, _agent(world), q="A")
    ids = {row["id"] for row in rows}
    assert str(world.ids["A1"]) in ids
    assert str(world.ids["A2"]) not in ids
    assert str(world.ids["B1"]) not in ids


def test_get_account_brief_hides_other_account_and_tenant(world, db_session):
    agent = _agent(world)
    assert accounts_api.get_account_brief(db_session, agent, world.ids["A1"])["id"] == str(
        world.ids["A1"]
    )
    with pytest.raises(NotFoundError):
        accounts_api.get_account_brief(db_session, agent, world.ids["A2"])
    with pytest.raises(NotFoundError):
        accounts_api.get_account_brief(db_session, agent, world.ids["B1"])


def test_contacts_only_for_readable_accounts(world, db_session):
    agent = _agent(world)
    mine = contacts_api.list_account_contacts(db_session, agent, world.ids["A1"])
    assert any(row["id"] == str(world.ids["C1"]) for row in mine)
    assert contacts_api.list_account_contacts(db_session, agent, world.ids["A2"]) == []
    assert contacts_api.list_account_contacts(db_session, agent, world.ids["B1"]) == []


def test_search_accounts_requires_permission(world, db_session):
    nobody = _staff(world, "alpha.agent1", set())
    with pytest.raises(ForbiddenError):
        accounts_api.search_accounts(db_session, nobody, q="A")
