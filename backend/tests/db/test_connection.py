"""Can the API's database role connect, and is it correctly restricted?"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from app.core.config import Settings
from app.main import create_app
from tests.auth_helpers import TEST_ISSUER


def test_app_role_connects_to_postgres_16_or_newer(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_setting('server_version_num')::int, "
                "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
            )
        ).one()

    database, version_num, is_superuser = row
    assert database.endswith("_test")
    assert version_num >= 160000
    assert is_superuser is False


def test_app_role_does_not_own_any_table(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        owned = connection.execute(
            text(
                "SELECT count(*) FROM pg_tables "
                "WHERE schemaname = 'public' AND tableowner = current_user"
            )
        ).scalar_one()

    assert owned == 0


def test_app_role_cannot_create_tables(app_engine: Engine) -> None:
    with (
        app_engine.connect() as connection,
        pytest.raises(ProgrammingError, match="permission denied"),
    ):
        connection.execute(text("CREATE TABLE should_not_exist (id int)"))


def test_app_role_cannot_drop_tables(app_engine: Engine) -> None:
    with app_engine.connect() as connection, pytest.raises(ProgrammingError, match="must be owner"):
        connection.execute(text("DROP TABLE leads"))


def test_readiness_endpoint_reports_database_ok(
    app_database_url: str, migrated_database: str
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=app_database_url,
        oidc_issuer=TEST_ISSUER,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
