"""The production Keycloak realm (ADR 0007) must never carry development leftovers."""

import json
import re
from pathlib import Path
from typing import Any

from scripts import make_production_realm as realm

SECRET_LIKE = re.compile(r"(?i)\"(secret|password|value)\"\s*:\s*\"(?!\$\{)[^\"]+\"")


def production() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(Path(realm.TARGET).read_text(encoding="utf-8"))
    return loaded


def test_the_file_is_generated_from_the_development_realm() -> None:
    expected = realm.render(realm.build(json.loads(realm.SOURCE.read_text(encoding="utf-8"))))
    assert realm.TARGET.read_text(encoding="utf-8") == expected, (
        "realm-crm-production.json is out of date: run  python -m scripts.make_production_realm"
    )


def test_no_test_users_no_local_addresses_no_literal_secrets() -> None:
    text = realm.TARGET.read_text(encoding="utf-8")
    data = production()
    assert "users" not in data  # the 11 development identities are not shipped
    for forbidden in ("localhost", "127.0.0.1", "mailpit", "example.test", "(local development)"):
        assert forbidden not in text, f"{forbidden!r} found in the production realm"
    assert not SECRET_LIKE.search(text), "a literal secret/password/value is in the realm file"


def test_production_security_settings() -> None:
    data = production()
    assert data["sslRequired"] == "all"  # HTTPS for every request
    assert data["registrationAllowed"] is False  # administrators invite people
    assert data["bruteForceProtected"] is True
    assert data["verifyEmail"] is True
    assert "length(14)" in data["passwordPolicy"]
    assert data["smtpServer"]["starttls"] == "true" and data["smtpServer"]["auth"] == "true"


def test_clients_keep_their_roles_and_only_the_web_address_is_a_placeholder() -> None:
    data = production()
    clients = {c["clientId"]: c for c in data["clients"]}
    assert set(clients) == {"crm-web", "crm-api", "crm-user-admin"}
    web = clients["crm-web"]
    assert web["redirectUris"] == [
        "${CRM_WEB_URL}/api/auth/callback/keycloak",
        "${CRM_WEB_URL}/login",
    ]
    assert web["directAccessGrantsEnabled"] is False  # no password grant: only the login page
    assert clients["crm-user-admin"]["serviceAccountsEnabled"] is True
    assert {r["name"] for r in data["roles"]["realm"]} == {
        "super_admin", "tenant_admin", "sales_manager", "sales_agent", "support_agent", "customer",
    }  # fmt: skip
