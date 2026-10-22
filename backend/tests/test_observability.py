"""R6 instrumentation tests: metric exposure, labels, redaction, AI cost instrumentation."""

import json
import logging

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.core.observability.metrics import (
    REGISTRY,
    observe_ai_call,
)
from app.main import create_app

UNREACHABLE = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nothing"


def make_client(token: str | None) -> TestClient:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE,
        oidc_issuer="https://issuer.example/realms/test",
        metrics_token=token,
    )
    return TestClient(create_app(settings))


def test_metrics_route_is_absent_when_no_token_is_configured():
    with make_client(None) as client:
        assert client.get("/api/v1/internal/metrics").status_code == 404


def test_metrics_route_requires_the_bearer_token():
    with make_client("secret-token") as client:
        assert client.get("/api/v1/internal/metrics").status_code == 401
        assert (
            client.get(
                "/api/v1/internal/metrics",
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )


def test_metrics_route_exposes_prometheus_text_without_pii_labels():
    with make_client("secret-token") as client:
        client.get("/api/v1/health")
        response = client.get(
            "/api/v1/internal/metrics",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "crm_http_requests_total" in body
    assert "crm_database_up" in body
    # Low-cardinality labels only; no tenant/user/question labels in the contract.
    assert 'route="/api/v1/health"' in body
    for forbidden in ("tenant_id=", "user_id=", "question="):
        assert forbidden not in body


def test_ai_token_and_estimated_cost_metrics_are_recorded():
    before = (
        REGISTRY.get_sample_value(
            "crm_ai_tokens_total",
            {"provider": "anthropic", "model": "test-model", "direction": "input"},
        )
        or 0.0
    )
    observe_ai_call(
        provider="anthropic",
        model="test-model",
        outcome="ok",
        seconds=0.5,
        input_tokens=1000,
        output_tokens=500,
        input_price_per_million=3.0,
        output_price_per_million=15.0,
    )
    after = REGISTRY.get_sample_value(
        "crm_ai_tokens_total",
        {"provider": "anthropic", "model": "test-model", "direction": "input"},
    )
    cost = REGISTRY.get_sample_value(
        "crm_ai_estimated_cost_usd_total",
        {"provider": "anthropic", "model": "test-model"},
    )
    assert after == before + 1000
    assert cost is not None and cost > 0
    assert (
        REGISTRY.get_sample_value(
            "crm_ai_requests_total",
            {"provider": "anthropic", "model": "test-model", "outcome": "ok"},
        )
        or 0
    ) >= 1


def test_log_formatter_redacts_secret_values():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "request done", None, None)
    record.api_key = "sk-abcdefghijklmnopqrstuvwxyz"
    record.note = "Bearer abcdefghijklmnop"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["api_key"] == "[REDACTED]"
    assert payload["note"] == "[REDACTED]"


def test_health_still_works_when_metrics_token_is_missing():
    with make_client(None) as client:
        assert client.get("/api/v1/health").status_code == 200
