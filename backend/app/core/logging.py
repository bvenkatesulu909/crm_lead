"""Structured (JSON) logging.

Each log line is one JSON object, so tools can filter by fields such as ``request_id`` or
``status_code`` instead of searching free text. Never pass secrets, tokens or personal data
in log messages or ``extra`` fields.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.observability.redaction import redact_text, redact_value
from app.core.request_context import get_request_id

# Attributes every LogRecord has; anything else on a record came from ``extra=...``.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",  # uvicorn's terminal-coloured copy of the message; noise in JSON
}


def _current_trace_ids() -> tuple[str | None, str | None]:
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            return format(context.trace_id, "032x"), format(context.span_id, "016x")
    except Exception:  # noqa: BLE001 - logging must never fail because tracing is absent
        return None, None
    return None, None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        trace_id, span_id = _current_trace_ids()
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = redact_value(key, value)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    # Replace only our own handler, so calling this twice (or under pytest) does not
    # duplicate lines or remove handlers that other tools installed.
    for handler in list(root.handlers):
        if isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    # Send uvicorn's messages through the same JSON handler. Its access log is turned off
    # because RequestContextMiddleware already logs every request with more detail.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
