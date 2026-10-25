"""The access log names the calling application from the VERIFIED token (ADR 0015, decision 6)."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import TokenFactory, bearer, forge_token


@pytest.fixture(autouse=True)
def _request_logger_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Alembic's fileConfig (run by the database tests) disables loggers that already exist.
    monkeypatch.setattr(logging.getLogger("app.request"), "disabled", False)


def _request_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.request" and r.msg == "request completed"]


def _call(client: TestClient, caplog: pytest.LogCaptureFixture, **kwargs: object) -> dict[str, Any]:
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.get("/api/v1/me", **kwargs)  # type: ignore[arg-type]
    (line,) = _request_lines(caplog)
    return vars(line)


def test_calls_through_the_mcp_server_are_logged_as_crm_mcp(
    client: TestClient, token_factory: TokenFactory, caplog: pytest.LogCaptureFixture
) -> None:
    token = token_factory.mint(azp="crm-mcp")
    assert _call(client, caplog, headers=bearer(token))["client_id"] == "crm-mcp"


def test_web_app_calls_are_logged_as_crm_web(
    client: TestClient, token_factory: TokenFactory, caplog: pytest.LogCaptureFixture
) -> None:
    assert _call(client, caplog, headers=bearer(token_factory.mint()))["client_id"] == "crm-web"


def test_no_client_without_a_token(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    assert "client_id" not in _call(client, caplog)


def test_a_rejected_token_cannot_choose_its_client_name(
    client: TestClient, token_factory: TokenFactory, caplog: pytest.LogCaptureFixture
) -> None:
    forged = forge_token({"alg": "none", "typ": "JWT"}, token_factory.claims(azp="crm-mcp"))
    assert "client_id" not in _call(client, caplog, headers=bearer(forged))


@pytest.mark.parametrize("azp", ["crm-mcp\nfake log line", "x" * 65, 42])
def test_odd_client_names_are_not_copied_into_the_log(
    azp: object,
    client: TestClient,
    token_factory: TokenFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = token_factory.mint(azp=azp)
    assert _call(client, caplog, headers=bearer(token))["client_id"] == "invalid"


def test_token_without_azp_logs_no_client(
    client: TestClient, token_factory: TokenFactory, caplog: pytest.LogCaptureFixture
) -> None:
    claims = token_factory.claims()
    del claims["azp"]
    assert "client_id" not in _call(client, caplog, headers=bearer(token_factory.sign(claims)))
