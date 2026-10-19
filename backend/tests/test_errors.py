"""The API must answer every kind of error in the same Problem Details format."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

# A marker string (not a real secret) that must never appear in an API response.
LEAK_MARKER = "internal-detail-should-never-leak"


@pytest.fixture
def app_with_test_routes(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/test/needs-int")
    def needs_int(value: int) -> dict[str, int]:
        return {"value": value}

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError(LEAK_MARKER)

    return app


@pytest.fixture
def test_client(app_with_test_routes: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_with_test_routes) as client:
        yield client


def _assert_problem(response_json: dict[str, object], status: int) -> None:
    assert response_json["type"] == "about:blank"
    assert response_json["status"] == status
    assert isinstance(response_json["title"], str)
    assert isinstance(response_json["detail"], str)
    assert isinstance(response_json["request_id"], str)


def test_unknown_route_returns_404_problem(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    _assert_problem(response.json(), 404)
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_returns_422_problem_without_echoing_input(
    test_client: TestClient,
) -> None:
    response = test_client.get("/test/needs-int", params={"value": "not-a-number-secret"})

    assert response.status_code == 422
    body = response.json()
    _assert_problem(body, 422)
    assert body["errors"][0]["location"] == ["query", "value"]
    assert "not-a-number-secret" not in response.text


def test_unexpected_error_returns_generic_500_problem(test_client: TestClient) -> None:
    response = test_client.get("/test/crash")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    _assert_problem(response.json(), 500)
    assert response.json()["detail"] == "An unexpected error occurred."
    assert LEAK_MARKER not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
