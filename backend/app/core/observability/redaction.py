"""Redaction for log fields (R6): secrets and token patterns never reach stdout."""

import re
from typing import Any

SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|session|credential)",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|password|secret)\s*[=:]\s*\S+"),
)
REDACTED = "[REDACTED]"


def redact_text(value: str) -> str:
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def redact_value(key: str, value: Any) -> Any:
    if SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k): redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, item) for item in value]
    return value
