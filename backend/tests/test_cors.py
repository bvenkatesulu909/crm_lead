from fastapi.testclient import TestClient

FRONTEND_ORIGIN = "http://localhost:3000"  # matches the settings fixture in conftest.py
EVIL_ORIGIN = "https://evil.example.com"


def test_preflight_from_allowed_origin_succeeds(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_preflight_from_unknown_origin_is_rejected(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": EVIL_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_simple_request_from_unknown_origin_gets_no_cors_header(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": EVIL_ORIGIN})

    # The server still answers, but without the header the browser hides the response
    # from the other website's JavaScript.
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_can_read_request_id_header(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": FRONTEND_ORIGIN})

    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()


def test_credentials_are_not_allowed(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": FRONTEND_ORIGIN})

    assert "access-control-allow-credentials" not in response.headers
