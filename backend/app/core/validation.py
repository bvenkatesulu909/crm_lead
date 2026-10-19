"""Reusable input field types for request schemas (any module may use these).

Each type trims whitespace, enforces the database column length and rejects obviously invalid
values with a clear message, so bad input becomes a 422 instead of a database error.
"""

import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, StringConstraints

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^[0-9+().\-\s]{3,50}$")
# "mailto:x", "javascript:x"... - a scheme without "//" (a port such as "host:8080" is fine).
_OTHER_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:(?!\d)")


def _email(value: str) -> str:
    if not _EMAIL.fullmatch(value):
        raise ValueError("must be a valid e-mail address")
    local, domain = value.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


def _phone(value: str) -> str:
    if not _PHONE.fullmatch(value):
        raise ValueError("may contain only digits, spaces and + ( ) . -")
    return value


def _url(value: str) -> str:
    # Only http(s): a "javascript:" or "data:" link shown in the UI would be an XSS vector.
    if "://" not in value:
        if _OTHER_SCHEME.match(value):
            raise ValueError("must be a web address such as https://example.com")
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in value:
        raise ValueError("must be a web address such as https://example.com")
    return value


def trimmed(max_length: int) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


Text50 = Annotated[str, trimmed(50)]
Text100 = Annotated[str, trimmed(100)]
Text150 = Annotated[str, trimmed(150)]
Text255 = Annotated[str, trimmed(255)]
Reason = Annotated[str, trimmed(500)]
Email = Annotated[str, trimmed(320), AfterValidator(_email)]
Phone = Annotated[str, trimmed(50), AfterValidator(_phone)]
WebUrl = Annotated[str, trimmed(2048), AfterValidator(_url)]
