import json
import logging

from app.core.logging import JsonFormatter


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_log_lines_are_valid_json_with_standard_fields() -> None:
    line = JsonFormatter().format(_record("hello"))

    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["timestamp"].endswith("+00:00")


def test_extra_fields_are_included() -> None:
    line = JsonFormatter().format(_record("request completed", status_code=200, path="/x"))

    payload = json.loads(line)
    assert payload["status_code"] == 200
    assert payload["path"] == "/x"
