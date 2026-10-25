"""Adds clients from realm-crm.json that the RUNNING local Keycloak does not have yet.

    python -m scripts.keycloak_add_clients            add missing clients (e.g. crm-mcp, ADR 0015)
    python -m scripts.keycloak_add_clients --dry-run  only list what would be added

Why: Keycloak imports realm-crm.json only on its very first start. Recreating the keycloak
database would apply later edits but deletes every invited or signed-up login. This script is the
non-destructive alternative for NEW clients: it never changes or deletes an existing client.

Clients whose file entry contains a ${PLACEHOLDER} (for example a client secret) are skipped -
those need the value from infrastructure/.env and are set up by the realm import.

Needs the Keycloak bootstrap administrator from infrastructure/.env (KEYCLOAK_ADMIN_USER,
KEYCLOAK_ADMIN_PASSWORD), read from the environment first, then from that file
(or --env-file). Local development only.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_DIR = Path(__file__).resolve().parents[2]
REALM_FILE = REPO_DIR / "infrastructure" / "keycloak" / "realm-crm.json"
DEFAULT_ENV_FILE = REPO_DIR / "infrastructure" / ".env"
REALM = "crm"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def missing_clients(realm: dict[str, Any], existing: set[str]) -> list[dict[str, Any]]:
    """Clients in the file that Keycloak lacks and that carry no ${PLACEHOLDER}."""
    return [
        client
        for client in realm.get("clients", [])
        if client["clientId"] not in existing and "${" not in json.dumps(client)
    ]


def scope_roles(realm: dict[str, Any], client_id: str) -> list[str]:
    for mapping in realm.get("scopeMappings", []):
        if mapping.get("client") == client_id:
            return list(mapping.get("roles", []))
    return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="only list missing clients")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--url", default=None, help="Keycloak address (default from .env)")
    args = parser.parse_args()

    env = {**read_env_file(args.env_file), **os.environ}
    user, password = env.get("KEYCLOAK_ADMIN_USER"), env.get("KEYCLOAK_ADMIN_PASSWORD")
    if not user or not password:
        sys.exit(
            f"KEYCLOAK_ADMIN_USER / KEYCLOAK_ADMIN_PASSWORD not set (looked in {args.env_file})"
        )
    base = args.url or f"http://localhost:{env.get('KEYCLOAK_PORT', '9080')}"

    realm: dict[str, Any] = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    with httpx.Client(base_url=base, timeout=15) as http:
        token = http.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": user,
                "password": password,
            },
        )
        if token.status_code != 200:
            sys.exit(f"Keycloak admin login failed (HTTP {token.status_code})")
        http.headers["Authorization"] = f"Bearer {token.json()['access_token']}"

        response = http.get(f"/admin/realms/{REALM}/clients", params={"max": 1000})
        response.raise_for_status()
        existing = {c["clientId"] for c in response.json()}
        todo = missing_clients(realm, existing)
        if not todo:
            print("nothing to add: every client from realm-crm.json already exists")
            return
        for client in todo:
            client_id = client["clientId"]
            roles = scope_roles(realm, client_id)
            if args.dry_run:
                print(f"would add {client_id} (scope roles: {', '.join(roles) or 'none'})")
                continue
            http.post(f"/admin/realms/{REALM}/clients", json=client).raise_for_status()
            created = http.get(f"/admin/realms/{REALM}/clients", params={"clientId": client_id})
            created.raise_for_status()
            internal_id = created.json()[0]["id"]
            role_reps = []
            for name in roles:
                role = http.get(f"/admin/realms/{REALM}/roles/{name}")
                role.raise_for_status()
                role_reps.append(role.json())
            if role_reps:
                http.post(
                    f"/admin/realms/{REALM}/clients/{internal_id}/scope-mappings/realm",
                    json=role_reps,
                ).raise_for_status()
            print(f"added {client_id} (scope roles: {', '.join(roles) or 'none'})")


if __name__ == "__main__":
    main()
