# ruff: noqa: S101, S104, S310, S607, E501 - a local admin tool: asserts, local URLs, docker CLI, long messages
"""Open the CRM to other devices on your network (and back to this computer only).

    python -m scripts.network_mode on <PC-address>    use this computer's network address
    python -m scripts.network_mode off                  back to localhost only
    python -m scripts.network_mode status               what is set now

Run it from the backend folder with the virtual environment active.

Why one script: the sign-in service (Keycloak) signs every token with its own web address, and
the API, the web app and Keycloak's allowed redirect addresses must all agree on it. "on"
changes them together and "off" puts them back from the backups it made. Nothing leaves your
network: no cloud, no internet exposure. Anyone on the SAME network can open the login page,
but still needs a CRM account.

It edits three git-ignored files (backups: *.network-backup), and registers the new address
with Keycloak's "crm-web" client through Keycloak's admin API (using the admin login from
infrastructure/.env; the password is never printed).
"""

import argparse
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infrastructure" / ".env"
BACKEND = ROOT / "backend" / ".env"
FRONTEND = ROOT / "frontend" / ".env.local"
LOCAL_KEYCLOAK = "http://localhost:9080"
BACKUP_SUFFIX = ".network-backup"
CLIENT_ID = "crm-web"


def read(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def set_values(path: Path, changes: dict[str, str]) -> None:
    """Change or add KEY=value lines, keeping everything else (comments, order) as it is."""
    lines = path.read_text(encoding="utf-8").splitlines()
    done: set[str] = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in changes:
                lines[i] = f"{key}={changes[key]}"
                done.add(key)
    lines += [f"{key}={value}" for key, value in changes.items() if key not in done]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def backup(path: Path) -> None:
    saved = path.with_name(path.name + BACKUP_SUFFIX)
    if not saved.exists():  # keep the ORIGINAL, even if "on" is run twice
        shutil.copy2(path, saved)


def restore(path: Path) -> bool:
    saved = path.with_name(path.name + BACKUP_SUFFIX)
    if not saved.exists():
        return False
    shutil.copy2(saved, path)
    saved.unlink()
    return True


# --- Keycloak admin API ----------------------------------------------------------------------


def _call(base: str, path: str, token: str | None = None, data: bytes | None = None,
          method: str = "GET", form: bool = False) -> object:  # fmt: skip
    # A request with a body is a POST unless a method (e.g. PUT) is given.
    request = urllib.request.Request(
        base + path, data=data, method=method if method != "GET" or data is None else "POST"
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header(
            "Content-Type", "application/x-www-form-urlencoded" if form else "application/json"
        )
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - local Keycloak
        body = response.read()
        return json.loads(body) if body else None


def edit_client_addresses(keycloak: str, web: str, *, add: bool) -> None:
    """Add (or remove) the web app's address in crm-web's redirect URIs and web origins."""
    infra = read(INFRA)
    token_form = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": infra["KEYCLOAK_ADMIN_USER"],
            "password": infra["KEYCLOAK_ADMIN_PASSWORD"],
        }
    ).encode()
    token = _call(
        keycloak, "/realms/master/protocol/openid-connect/token", data=token_form, form=True
    )
    assert isinstance(token, dict)
    access = token["access_token"]
    clients = _call(keycloak, f"/admin/realms/crm/clients?clientId={CLIENT_ID}", access)
    assert isinstance(clients, list) and clients, "client crm-web not found"
    client = clients[0]
    mine = {f"{web}/api/auth/callback/keycloak", f"{web}/login", web}

    def merge(values: list[str]) -> list[str]:
        kept = [v for v in values if v not in mine]
        return kept + sorted(mine) if add else kept

    client["redirectUris"] = merge([u for u in client.get("redirectUris", [])])
    client["webOrigins"] = merge(client.get("webOrigins", []))
    attrs = client.setdefault("attributes", {})
    post = [u for u in attrs.get("post.logout.redirect.uris", "").split("##") if u]
    logout = f"{web}/"
    post = [u for u in post if u != logout] + ([logout] if add else [])
    attrs["post.logout.redirect.uris"] = "##".join(post)
    _call(
        keycloak,
        f"/admin/realms/crm/clients/{client['id']}",
        access,
        json.dumps(client).encode(),
        "PUT",
    )


# --- commands --------------------------------------------------------------------------------


def restart_keycloak() -> None:
    subprocess.run(
        ["docker", "compose", "up", "-d", "keycloak"], cwd=ROOT / "infrastructure", check=True
    )


def turn_on(host: str) -> None:
    address = ipaddress.ip_address(host)
    if not address.is_private:
        sys.exit("Use this computer's PRIVATE address (192.168.x.x, 10.x.x.x or 172.16-31.x.x).")
    web, keycloak = f"http://{host}:3000", f"http://{host}:9080"
    print(f"1/4 Telling Keycloak that the web app may also live at {web} ...")
    edit_client_addresses(LOCAL_KEYCLOAK, web, add=True)
    print("2/4 Backing up and updating the settings files ...")
    for path in (INFRA, BACKEND, FRONTEND):
        backup(path)
    set_values(INFRA, {"KEYCLOAK_PUBLIC_URL": keycloak, "KEYCLOAK_BIND": "0.0.0.0"})
    origins = read(BACKEND).get("CRM_CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    if web not in origins:
        origins += f",{web}"
    set_values(BACKEND, {
        "CRM_OIDC_ISSUER": f"{keycloak}/realms/crm",
        "CRM_WEB_APP_URL": web,
        "CRM_CORS_ALLOWED_ORIGINS": origins,
    })  # fmt: skip
    set_values(
        FRONTEND,
        {"APP_BASE_URL": web, "OIDC_ISSUER": f"{keycloak}/realms/crm", "NETWORK_HOST": host},
    )
    print("3/4 Restarting Keycloak with its new address ...")
    restart_keycloak()
    print("4/4 Done. Restart the API and the web app, then open:")
    print(f"      {web}\n")
    print("Start the web app with:  cd frontend && npm run dev:network")
    print(
        "Other devices need the Windows firewall open for ports 3000 and 9080 (see docs/network-access.md)."
    )


def turn_off() -> None:
    web = read(FRONTEND).get("APP_BASE_URL", "")
    if web and "localhost" not in web:
        print(f"1/3 Removing {web} from Keycloak's allowed addresses ...")
        try:
            edit_client_addresses(
                read(INFRA).get("KEYCLOAK_PUBLIC_URL", LOCAL_KEYCLOAK), web, add=False
            )
        except Exception as error:  # noqa: BLE001 - settings are restored either way
            print(
                f"    (could not reach Keycloak: {type(error).__name__}; the extra address stays, harmless)"
            )
    print("2/3 Restoring the settings files from the backups ...")
    for path in (INFRA, BACKEND, FRONTEND):
        print(
            f"    {path.relative_to(ROOT)}: {'restored' if restore(path) else 'no backup (already local)'}"
        )
    print("3/3 Restarting Keycloak on localhost ...")
    restart_keycloak()
    print("Done. Restart the API and the web app; use http://localhost:3000 again.")


def status() -> None:
    web = read(FRONTEND).get("APP_BASE_URL", "?")
    mode = "NETWORK" if web and "localhost" not in web else "LOCAL (this computer only)"
    print(
        f"Mode: {mode}\nWeb app: {web}\nKeycloak: {read(INFRA).get('KEYCLOAK_PUBLIC_URL', LOCAL_KEYCLOAK)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["on", "off", "status"])
    parser.add_argument("host", nargs="?", help="this computer's private address (for 'on')")
    args = parser.parse_args()
    if args.command == "on":
        if not args.host or not re.fullmatch(r"[0-9.]{7,15}", args.host):
            sys.exit("Usage: python -m scripts.network_mode on <this computer's address>")
        turn_on(args.host)
    elif args.command == "off":
        turn_off()
    else:
        status()


if __name__ == "__main__":
    main()
