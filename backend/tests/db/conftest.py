"""Fixtures for tests that need the real PostgreSQL test database (crm_test).

Configuration (backend/.env or environment variables):
    CRM_TEST_DATABASE_URL            app role       -> what the API uses
    CRM_TEST_MIGRATION_DATABASE_URL  owner role     -> what Alembic uses

If these are not set, the database tests are SKIPPED (reported as "s"). If they are set but
the database is down, the tests FAIL - a configured database that cannot be reached is a
real problem, not something to hide.

The schema is built with Alembic migrations, exactly as in development - never create_all().
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, Engine, create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]


class DatabaseTestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRM_TEST_", env_file=BACKEND_DIR / ".env", extra="ignore"
    )

    database_url: SecretStr | None = None
    migration_database_url: SecretStr | None = None


def _require_test_database(url: SecretStr) -> str:
    value = url.get_secret_value()
    name = make_url(value).database or ""
    if not name.endswith("_test"):
        # Tests drop and recreate every table. Never let them touch a real database.
        raise RuntimeError(
            f"Refusing to run database tests against database {name!r}: "
            "its name must end with '_test'."
        )
    return value


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture(scope="session")
def db_test_settings() -> DatabaseTestSettings:
    settings = DatabaseTestSettings()
    if settings.database_url is None or settings.migration_database_url is None:
        pytest.skip("CRM_TEST_DATABASE_URL / CRM_TEST_MIGRATION_DATABASE_URL are not configured")
    return settings


@pytest.fixture(scope="session")
def app_database_url(db_test_settings: DatabaseTestSettings) -> str:
    assert db_test_settings.database_url is not None
    return _require_test_database(db_test_settings.database_url)


@pytest.fixture(scope="session")
def migration_database_url(db_test_settings: DatabaseTestSettings) -> str:
    assert db_test_settings.migration_database_url is not None
    return _require_test_database(db_test_settings.migration_database_url)


@pytest.fixture(scope="session")
def migrated_database(migration_database_url: str) -> str:
    """Start every test run from an empty schema, then apply all migrations."""
    config = alembic_config(migration_database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return migration_database_url


@pytest.fixture(scope="session")
def app_engine(app_database_url: str, migrated_database: str) -> Iterator[Engine]:
    # NullPool: no idle connections are kept, so migration tests can drop tables freely.
    engine = create_engine(app_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(app_engine: Engine) -> Iterator[Connection]:
    """One connection + transaction per test, rolled back afterwards: tests never see each
    other's data. The test's session AND the API under test both use this connection."""
    with app_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def session_factory_for(connection: Connection) -> sessionmaker[Session]:
    # create_savepoint: commits inside the code under test only release a savepoint, so the
    # outer test transaction can still roll everything back.
    return sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    session = session_factory_for(db_connection)()
    try:
        yield session
    finally:
        session.close()
