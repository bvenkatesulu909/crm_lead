#!/usr/bin/env python3
"""Writes the server's ``.env`` for the one-server deployment (ADR 0021).

It copies ``.env.example``, puts the names you give into it and replaces every generated secret by
a fresh random value (``secrets.token_urlsafe``, 43 characters). The services that live OUTSIDE the
server - your file bucket, your mail provider, your backup bucket - stay ``CHANGE_ME``: only you
have those values.

    python3 bin/make_env.py --api-host api.yourcompany.in --login-host login.yourcompany.in \\
        --web-url https://crm.yourcompany.in --acme-email you@yourcompany.in \\
        --mail-from no-reply@yourcompany.in

The new file is readable by you only. This tool prints which variables are left to fill in, never a
secret. It refuses to overwrite an existing ``.env`` unless you pass ``--force`` (a lost password
file means a database nobody can open).

Standard library only, so it runs on a fresh server.
"""

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / ".env.example"

# Generated here: a different random value each, all URL-safe (they are used inside URLs).
GENERATED = (
    "POSTGRES_PASSWORD",
    "CRM_DB_OWNER_PASSWORD",
    "CRM_DB_APP_PASSWORD",
    "CRM_DB_BACKUP_PASSWORD",
    "KEYCLOAK_DB_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "CRM_WEB_CLIENT_SECRET",
    "CRM_USER_ADMIN_CLIENT_SECRET",
    "CRM_METRICS_TOKEN",
)

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOSTNAME = re.compile(rf"^(?:{_LABEL}\.)+[a-z]{{2,24}}$")
EMAIL = re.compile(rf"^[A-Za-z0-9._%+-]+@((?:{_LABEL}\.)+[a-z]{{2,24}})$")
# Names that can never be a real public address (placeholders, local or reserved names).
_NOT_REAL = {"example", "localhost", "invalid", "test", "local", "internal", "localdomain"}


def real_hostname(value: str) -> bool:
    """A public DNS name such as api.yourcompany.in: lower case, a dot, no scheme, no path, no IP
    address, and not a placeholder or reserved name."""
    if not HOSTNAME.match(value) or len(value) > 253:
        return False
    return not (set(value.split(".")) & _NOT_REAL)


def real_email(value: str) -> bool:
    match = EMAIL.match(value)
    return match is not None and real_hostname(match.group(1))


def real_https_url(value: str) -> bool:
    return value.startswith("https://") and real_hostname(value[len("https://") :])


def generate(
    *,
    api_host: str,
    login_host: str,
    web_url: str,
    acme_email: str,
    mail_from_address: str,
) -> str:
    """The text of a new ``.env``. Raises ValueError for an address that cannot work."""
    if not real_hostname(api_host):
        raise ValueError(
            f"--api-host '{api_host}' is not a public host name like api.yourcompany.in"
        )
    if not real_hostname(login_host):
        raise ValueError(f"--login-host '{login_host}' is not a public host name")
    if api_host == login_host:
        raise ValueError("--api-host and --login-host must be two different names")
    if not real_https_url(web_url):
        raise ValueError(f"--web-url '{web_url}' must be https://your-site-name (no path)")
    if not real_email(acme_email):
        raise ValueError(f"--acme-email '{acme_email}' is not an e-mail address")
    if not real_email(mail_from_address):
        raise ValueError(f"--mail-from '{mail_from_address}' is not an e-mail address")

    values = {
        "API_HOST": api_host,
        "LOGIN_HOST": login_host,
        "WEB_URL": web_url,
        "ACME_EMAIL": acme_email,
        "MAIL_FROM_ADDRESS": mail_from_address,
        **{name: secrets.token_urlsafe(32) for name in GENERATED},
    }
    lines = []
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match and match.group(1) in values:
            line = f"{match.group(1)}={values[match.group(1)]}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def still_to_fill(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=CHANGE_ME$", text, flags=re.M)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the server's .env with fresh secrets.")
    parser.add_argument("--api-host", required=True, help="e.g. api.yourcompany.in")
    parser.add_argument("--login-host", required=True, help="e.g. login.yourcompany.in")
    parser.add_argument(
        "--web-url", required=True, help="the Netlify site, e.g. https://crm.yourcompany.in"
    )
    parser.add_argument(
        "--acme-email", required=True, help="where certificate problems are reported"
    )
    parser.add_argument("--mail-from", required=True, help="sender address of every e-mail")
    parser.add_argument("--out", default=".env", help="file to write (default: .env)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)

    target = Path(args.out)
    if target.exists() and not args.force:
        print(f"{target} already exists - not overwritten. Use --force only if you are sure.")
        return 2
    try:
        text = generate(
            api_host=args.api_host,
            login_host=args.login_host,
            web_url=args.web_url,
            acme_email=args.acme_email,
            mail_from_address=args.mail_from,
        )
    except ValueError as error:
        print(f"Not written: {error}")
        return 1

    # Create it private from the first byte (never world-readable, not even for a moment).
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    if sys.platform != "win32":
        os.chmod(target, 0o600)

    print(f"Wrote {target}: {len(GENERATED)} secrets generated (not shown), readable by you only.")
    print("Still to fill in by hand (your own accounts):")
    for name in still_to_fill(text):
        print(f"  {name}")
    print("Then run:  python3 bin/check_env.py", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
