#!/usr/bin/env python3
"""Refuses a ``.env`` that must not reach production (ADR 0021).

    python3 bin/check_env.py .env

Exit code 0 = fine; 1 = problems, listed by VARIABLE NAME. A message never repeats a secret value,
so the output is safe to paste into a chat or a ticket.

What it refuses: a missing or placeholder (CHANGE_ME) value; a secret that is short, made of a
repeated pattern, contains an obvious word such as "password", or is used twice; addresses that are
not real public names; an administration console open to everybody; a bucket for backups that is
the documents bucket; a backup key that is not a public ``age1...`` key; and any development setting
(fake AI providers, the demo web check, the API docs, a file store without HTTPS, an environment
other than production).

Standard library only, so it runs on a fresh server.
"""

import ipaddress
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_env  # noqa: E402  (the same address rules as the tool that writes the file)

SECRETS = make_env.GENERATED
PLACEHOLDER = "CHANGE_ME"
MIN_SECRET = 32
FORBIDDEN_WORDS = ("password", "changeme", "change_me", "secret", "qwerty", "letmein", "example")
AGE_PUBLIC_KEY = re.compile(r"^age1[02-9ac-hj-np-z]{58}$")  # bech32 characters only
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
ENDPOINT = re.compile(r"^[A-Za-z0-9.-]+:\d{1,5}$")

# Settings that are only ever for development. Someone adding one of these lines is refused.
DEVELOPMENT_ONLY: dict[str, Callable[[str], bool]] = {
    "CRM_ENVIRONMENT": lambda v: v != "production",
    "CRM_AI_PROVIDER": lambda v: v == "fake",
    "CRM_PUBLIC_CHAT_PROVIDER": lambda v: v == "fake",
    "CRM_WEBCHECK_DEMO": lambda v: v.lower() in {"1", "true", "yes", "on"},
    "CRM_DOCS_ENABLED": lambda v: v.lower() in {"1", "true", "yes", "on"},
    "CRM_FILES_S3_SECURE": lambda v: v.lower() in {"0", "false", "no", "off"},
}


def parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return values


def weak_reason(value: str) -> str | None:
    """Why a secret is not good enough (without repeating it), or None."""
    if len(value) < MIN_SECRET:
        return f"too short (at least {MIN_SECRET} characters)"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return "has characters other than letters, digits, - and _"
    lowered = value.lower()
    if any(word in lowered for word in FORBIDDEN_WORDS):
        return "contains an obvious word"
    if len(set(value)) < 12:
        return "is not random (too few different characters)"
    for size in range(1, len(value) // 2 + 1):
        block = value[:size]
        if len(value) % size == 0 and block * (len(value) // size) == value:
            return "is a repeated pattern"
    return None


def _missing(values: dict[str, str], name: str) -> bool:
    return values.get(name, "") in {"", PLACEHOLDER}


def check(text: str) -> Iterator[str]:
    values = parse(text)

    for name, accepts in DEVELOPMENT_ONLY.items():
        if name in values and accepts(values[name]):
            yield f"{name}: a development setting - not allowed in production"

    for name in SECRETS:
        if _missing(values, name):
            yield f"{name}: missing - run bin/make_env.py"
        elif (reason := weak_reason(values[name])) is not None:
            yield f"{name}: {reason}"
    used: dict[str, str] = {}
    for name in SECRETS:
        value = values.get(name, "")
        if value and value != PLACEHOLDER:
            if value in used:
                yield f"{name}: the same value as {used[value]} - every secret must be different"
            used.setdefault(value, name)

    for name in ("API_HOST", "LOGIN_HOST"):
        if not make_env.real_hostname(values.get(name, "")):
            yield f"{name}: not a real public host name (no placeholder, localhost or IP address)"
    if values.get("API_HOST") and values.get("API_HOST") == values.get("LOGIN_HOST"):
        yield "LOGIN_HOST: must differ from API_HOST"
    if not make_env.real_https_url(values.get("WEB_URL", "")):
        yield "WEB_URL: must be https://your-site-name (no path)"
    for name in ("ACME_EMAIL", "MAIL_FROM_ADDRESS"):
        if not make_env.real_email(values.get(name, "")):
            yield f"{name}: not a real e-mail address"

    yield from _admin_addresses(values.get("ADMIN_ALLOWED_IPS", ""))

    for name in ("CRM_FILES_S3_ENDPOINT", "BACKUP_S3_ENDPOINT"):
        if _missing(values, name):
            yield f"{name}: fill in your provider's endpoint (host:port)"
        elif not ENDPOINT.match(values[name]):
            yield f"{name}: must look like host:port, for example s3.provider.com:443"
    for name in ("CRM_FILES_S3_BUCKET", "BACKUP_S3_BUCKET"):
        if _missing(values, name):
            yield f"{name}: fill in the bucket name"
        elif not BUCKET.match(values[name]):
            yield f"{name}: not a valid bucket name"
    if values.get("BACKUP_S3_BUCKET") and values.get("BACKUP_S3_BUCKET") == values.get(
        "CRM_FILES_S3_BUCKET"
    ):
        yield "BACKUP_S3_BUCKET: backups need their own bucket, not the documents bucket"
    for name in (
        "CRM_FILES_S3_ACCESS_KEY",
        "CRM_FILES_S3_SECRET_KEY",
        "BACKUP_S3_ACCESS_KEY",
        "BACKUP_S3_SECRET_KEY",
        "CRM_SMTP_USERNAME",
        "CRM_SMTP_PASSWORD",
    ):
        if _missing(values, name):
            yield f"{name}: fill in the value from your provider"
        elif len(values[name]) < 12 and "SMTP_USERNAME" not in name:
            yield f"{name}: too short to be a real key"
    if _missing(values, "CRM_SMTP_HOST"):
        yield "CRM_SMTP_HOST: fill in your mail provider's host"
    if not values.get("CRM_SMTP_PORT", "").isdigit():
        yield "CRM_SMTP_PORT: must be a number (587 for STARTTLS)"

    key = values.get("BACKUP_AGE_PUBLIC_KEY", "")
    if _missing(values, "BACKUP_AGE_PUBLIC_KEY"):
        yield (
            "BACKUP_AGE_PUBLIC_KEY: create a key pair on YOUR computer (age-keygen) "
            "and paste the public half"
        )
    elif not AGE_PUBLIC_KEY.match(key):
        yield "BACKUP_AGE_PUBLIC_KEY: must be the PUBLIC key, starting with age1 (not the secret)"

    for name, value in values.items():
        if value == PLACEHOLDER and name not in SECRETS:
            yield f"{name}: still CHANGE_ME"


def _admin_addresses(raw: str) -> Iterator[str]:
    parts = raw.split()
    if not parts:
        yield "ADMIN_ALLOWED_IPS: set it (127.0.0.1 = nobody)"
        return
    for part in parts:
        try:
            network = ipaddress.ip_network(part, strict=False)
        except ValueError:
            yield "ADMIN_ALLOWED_IPS: not an IP address or network"
            return
        if network.network_address.is_unspecified or network.num_addresses > 65_536:
            yield "ADMIN_ALLOWED_IPS: open to (almost) everybody - list your own address instead"
            return


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_env.py PATH_TO_ENV_FILE")
        return 2
    path = Path(args[0])
    if not path.is_file():
        print(f"{path}: no such file - run bin/make_env.py first")
        return 2
    problems = list(check(path.read_text(encoding="utf-8")))
    if not problems:
        print(f"{path}: OK - nothing here that must not reach production.")
        return 0
    print(f"{path}: {len(problems)} problem(s):")
    for problem in problems:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
