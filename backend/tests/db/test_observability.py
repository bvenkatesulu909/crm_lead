"""R6 operational gauges against the real test database."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.heartbeat import record_heartbeat
from app.main import create_app
from tests.db.conftest import alembic_config  # noqa: F401 - documents the fixture relationship

TEST_ISSUER = "https://issuer.example/realms/test"


def test_metrics_endpoint_reflects_db_pgvector_and_worker_heartbeat(
    app_database_url: str, migration_database_url: str
):
    from sqlalchemy.orm import sessionmaker

    from app.core.observability.metrics import refresh_operational_gauges

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=app_database_url,
        oidc_issuer=TEST_ISSUER,
        metrics_token="ops-token",  # noqa: S106 - test value only
    )
    with TestClient(create_app(settings)) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        factory = sessionmaker(bind=engine)
        record_heartbeat(factory)
        refresh_operational_gauges(engine)

        response = client.get(
            "/api/v1/internal/metrics",
            headers={"Authorization": "Bearer ops-token"},
        )

    assert response.status_code == 200
    body = response.text
    assert "crm_database_up 1.0" in body
    assert 'crm_pgvector_check{check="extension"} 1.0' in body
    assert 'crm_pgvector_check{check="hnsw_index"} 1.0' in body
    assert "crm_worker_heartbeat_age_seconds" in body
    assert "crm_outbox_jobs" in body
    assert "crm_knowledge_documents" in body
