"""Builds the PRODUCTION Keycloak realm file from the development one (ADR 0007).

    python -m scripts.make_production_realm           write realm-crm-production.json
    python -m scripts.make_production_realm --check   fail if that file is out of date

What changes compared with realm-crm.json (development):
- **No users.** The 11 test identities and their shared development password do not exist online.
  The first administrator is created by hand (docs/deployment.md).
- HTTPS is required for every request (``sslRequired: all``).
- Addresses and mail settings are ${PLACEHOLDERS} that Keycloak fills in from environment
  variables on the first start, so no real address or password is stored in this repository.
- Self sign-up is off (administrators invite people, ADR 0004); the stronger password rule is on.
- The ``crm-mcp`` client is removed: the MCP server is local only (ADR 0015 (originally 0010)).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

KEYCLOAK_DIR = Path(__file__).resolve().parents[2] / "infrastructure" / "keycloak"
SOURCE = KEYCLOAK_DIR / "realm-crm.json"
TARGET = KEYCLOAK_DIR / "realm-crm-production.json"
WEB = "${CRM_WEB_URL}"  # e.g. https://app.example.com - set on the Keycloak host
LOCAL_ONLY = {"crm-mcp"}


def build(development: dict[str, Any]) -> dict[str, Any]:
    realm: dict[str, Any] = json.loads(json.dumps(development))  # deep copy
    realm.pop("users", None)
    realm["displayName"] = "crm-lead"
    realm["sslRequired"] = "all"
    realm["registrationAllowed"] = False
    realm["passwordPolicy"] = (
        "length(14) and notUsername and upperCase(1) and lowerCase(1) and digits(1)"
    )
    realm["smtpServer"] = {
        "host": "${SMTP_HOST}",
        "port": "${SMTP_PORT}",
        "from": "${SMTP_FROM}",
        "fromDisplayName": "crm-lead",
        "ssl": "false",
        "starttls": "true",
        "auth": "true",
        "user": "${SMTP_USER}",
        "password": "${SMTP_PASSWORD}",
    }
    # A remote MCP endpoint would need its own ADR (ADR 0015 (originally 0010), decision 7).
    realm["clients"] = [c for c in realm.get("clients", []) if c.get("clientId") not in LOCAL_ONLY]
    realm["scopeMappings"] = [
        m for m in realm.get("scopeMappings", []) if m.get("client") not in LOCAL_ONLY
    ]
    for client in realm.get("clients", []):
        if client.get("clientId") == "crm-web":
            client["redirectUris"] = [f"{WEB}/api/auth/callback/keycloak", f"{WEB}/login"]
            client["webOrigins"] = [WEB]
            attributes = client.setdefault("attributes", {})
            attributes["post.logout.redirect.uris"] = f"{WEB}/"
    return realm


def render(realm: dict[str, Any]) -> str:
    return json.dumps(realm, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="only check that the file is up to date"
    )
    args = parser.parse_args()
    text = render(build(json.loads(SOURCE.read_text(encoding="utf-8"))))
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            sys.exit(f"{TARGET.name} is out of date: run  python -m scripts.make_production_realm")
        print("up to date")
        return
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
