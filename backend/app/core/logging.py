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

from app.core.request_context import get_request_id

# Attributes every LogRecord has; anything else on a record came from ``extra=...``.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",  # uvicorn's terminal-coloured copy of the message; noise in JSON
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
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
