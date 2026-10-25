"""The crm-mcp Keycloak client (ADR 0015): local, public, PKCE, staff roles only."""

import json
from typing import Any

from scripts import keycloak_add_clients as add_clients
from scripts import make_production_realm as realm


def development() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(realm.SOURCE.read_text(encoding="utf-8"))
    return loaded


def mcp_client(data: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in data["clients"] if c["clientId"] == "crm-mcp")


def test_mcp_client_is_public_pkce_with_loopback_redirect_only() -> None:
    client = mcp_client(development())
    assert client["publicClient"] is True  # a local program cannot keep a secret
    assert "secret" not in client
    assert client["standardFlowEnabled"] is True
    assert client["implicitFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False  # never sees the password
    assert client["serviceAccountsEnabled"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["redirectUris"] == ["http://127.0.0.1:8765/callback"]
    assert client["webOrigins"] == []
    assert client["fullScopeAllowed"] is False
    audience = client["protocolMappers"][0]["config"]["included.client.audience"]
    assert audience == "crm-api"


def test_mcp_tokens_carry_staff_roles_only() -> None:
    roles = add_clients.scope_roles(development(), "crm-mcp")
    assert set(roles) == {"tenant_admin", "sales_manager", "sales_agent", "support_agent"}
    assert "customer" not in roles and "super_admin" not in roles


def test_mcp_client_is_not_shipped_to_production() -> None:
    production = realm.build(development())
    assert "crm-mcp" not in {c["clientId"] for c in production["clients"]}
    assert "crm-mcp" not in {m["client"] for m in production["scopeMappings"]}


def test_add_clients_skips_existing_and_placeholder_clients() -> None:
    data = development()
    todo = add_clients.missing_clients(data, existing={"crm-api", "crm-user-admin"})
    # crm-web is missing too, but its secret is a ${PLACEHOLDER}: left to the realm import.
    assert [c["clientId"] for c in todo] == ["crm-mcp"]
    assert add_clients.missing_clients(data, existing={"crm-web", "crm-api", "crm-mcp"}) == []
