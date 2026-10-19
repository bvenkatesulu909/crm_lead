from fastapi.testclient import TestClient

from app import __version__


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "service": "crm-lead-api", "version": __version__}


def test_health_response_has_generated_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert request_id.isalnum()


def test_health_echoes_valid_incoming_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["X-Request-ID"] == "trace-abc-123"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\twith spaces"})

    assert response.headers["X-Request-ID"] != "bad id\twith spaces"
    assert len(response.headers["X-Request-ID"]) == 32


def test_health_rejects_wrong_method_with_problem_details(client: TestClient) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 405
    assert "GET" in response.headers["allow"]


def test_health_is_only_served_under_api_v1(client: TestClient) -> None:
    assert client.get("/health").status_code == 404


def test_readiness_returns_503_problem_when_database_is_unreachable(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "Database unavailable."
    # No connection details may leak to the caller.
    assert "127.0.0.1" not in response.text
    assert "nobody" not in response.text
