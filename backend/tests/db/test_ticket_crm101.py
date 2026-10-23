# ruff: noqa: F811
"""CRM-101 support boundary: tenant-wide read/manage, read-only billing, no admin."""

import json
import uuid
from pathlib import Path

from app.core.auth.rbac import Permission, Role, permissions_for
from tests.db.test_invoices_api import (  # noqa: F401
    api,
    auth,
    world,
)

REALM = Path(__file__).resolve().parents[3] / "infrastructure" / "keycloak" / "realm-crm.json"


def test_support_agent_has_tenant_wide_read_permissions():
    permissions = permissions_for(frozenset({Role.SUPPORT_AGENT}))
    assert Permission.TICKET_READ_ALL in permissions
    assert Permission.TICKET_MANAGE in permissions
    assert Permission.INVOICE_READ_ALL in permissions
    assert Permission.ORDER_READ_ALL in permissions
    assert Permission.INVOICE_MANAGE not in permissions
    assert Permission.ORDER_WRITE_ALL not in permissions


def test_support_agent_can_list_invoices(api, auth):
    response = api.get("/api/v1/invoices", headers=auth("alpha.support"))
    assert response.status_code == 200, response.text


def test_support_agent_can_list_orders(api, auth):
    response = api.get("/api/v1/orders", headers=auth("alpha.support"))
    assert response.status_code == 200, response.text


def test_support_agent_cannot_open_admin_users(api, auth):
    response = api.get("/api/v1/tenant/users", headers=auth("alpha.support"))
    assert response.status_code == 403


def test_support_agent_cannot_read_another_tenants_account(api, auth, world):
    response = api.get(f"/api/v1/accounts/{world.accounts['B1']}", headers=auth("alpha.support"))
    assert response.status_code == 404


def test_support_agent_cannot_read_a_guessed_account_id(api, auth):
    response = api.get(f"/api/v1/accounts/{uuid.uuid4()}", headers=auth("alpha.support"))
    assert response.status_code == 404


def test_support_agent_realm_mapping_has_no_forbidden_roles():
    data = json.loads(REALM.read_text(encoding="utf-8"))
    support = next(user for user in data["users"] if user["username"] == "alpha.support")
    assert support["realmRoles"] == ["support_agent"]
    assert "groups" not in support or support["groups"] == []
