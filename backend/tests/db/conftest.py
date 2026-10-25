"""Fixtures for tests that need the real PostgreSQL test database (crm_test).

Configuration (backend/.env or environment variables):
    CRM_TEST_DATABASE_URL            app role       -> what the API uses
    CRM_TEST_MIGRATION_DATABASE_URL  owner role     -> what Alembic uses

If these are not set, the database tests are SKIPPED (reported as "s"). If they are set but
the database is down, the tests FAIL - a configured database that cannot be reached is a
real problem, not something to hide.

The schema is built with Alembic migrations, exactly as in development - never create_all().
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from app.core.auth.principal import Principal

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


@pytest.fixture(scope="session")
def owner_engine(migration_database_url: str, migrated_database: str) -> Iterator[Engine]:
    """Privileged (crm_owner, BYPASSRLS) engine for TEST SETUP ONLY.

    API/RLS assertions must keep using app_engine (crm_app, no BYPASSRLS). Data created through
    this engine is not part of the app connection's rollback; callers own cleanup.
    """
    engine = create_engine(migration_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def owner_db_session(owner_engine: Engine) -> Iterator[Session]:
    """Setup session as crm_owner. Do not use it to assert application/RLS behaviour."""
    with sessionmaker(bind=owner_engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def committed_owner_data(owner_db_session: Session) -> Iterator[Session]:
    """Setup session for data that must be COMMITTED and visible to the app connection.

    Pair with clean_committed_data so the rows are removed after the test. Never assert RLS
    behaviour through this session.
    """
    yield owner_db_session


@pytest.fixture
def clean_committed_data(
    owner_engine: Engine, db_connection: Connection, db_session: Session
) -> Iterator[None]:
    """After the test, truncate all application tables on the test database (owner role).

    The app connection's outer transaction must be finished first: it may hold row locks from
    API writes, and TRUNCATE would block on them. The owner cleanup then runs outside RLS.
    """
    yield
    db_session.close()
    if db_connection.in_transaction():
        db_connection.rollback()
    with owner_engine.begin() as connection:
        names = (
            connection.execute(
                text(
                    "select tablename from pg_tables "
                    "where schemaname = current_schema() and tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        if names:
            connection.execute(
                text("TRUNCATE TABLE " + ", ".join(names) + " RESTART IDENTITY CASCADE")
            )


@pytest.fixture
def db_connection(app_engine: Engine) -> Iterator[Connection]:
    """One connection + transaction per test, rolled back afterwards: tests never see each
    other's data. The test's session AND the API under test both use this connection."""
    with app_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            if transaction.is_active:
                transaction.rollback()


@pytest.fixture
def committed_world(committed_owner_data: Session, clean_committed_data: None) -> Session:
    """Session for building test worlds: crm_owner (BYPASSRLS), committed, cleaned afterwards.

    Setup fixtures use this so their rows are visible to the restricted crm_app connection that
    runs the API and the RLS assertions. Never assert application/RLS behaviour through it.
    """
    return committed_owner_data


def forget_request_user(session: Session) -> None:
    """Drop the user and lead scope earlier API calls left on the shared test transaction.

    In production every worker job is its own transaction with only the tenant bound. Tests run
    everything in one outer transaction, where a request's settings would otherwise still be
    there when the worker runs - and hide bugs that only show up in the real worker.
    """
    session.execute(
        text("select set_config('app.user_id', '', true), set_config('app.lead_scope', '', true)")
    )


def setup_lead_context(
    session: Session,
    tenant_id: uuid.UUID,
    owner_id: uuid.UUID | None = None,
    *,
    scope: str | None = None,
) -> None:
    """Give a rolled-back setup session the RLS context a real request would have.

    Rows inserted in a test's transaction cannot be written through the owner connection: their
    tenants/users are uncommitted, so a separate owner transaction could not see the foreign
    keys. The policy is not weakened - it still checks the tenant and that the row is owned by
    the current user (scope "own") or that the current user is a manager (scope "all", used for
    rows deliberately left without an owner).
    """
    from app.core.db import bind_tenant, bind_user

    bind_tenant(session, tenant_id)
    bind_user(session, owner_id or uuid.uuid4(), scope or ("own" if owner_id else "all"))


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


def bind_principal(session: Session, principal: "Principal") -> None:
    """Bind the RLS context identity resolution gives a request for this principal.

    For tests that call a module's service/api directly with a hand-built Principal: in the
    application those calls always run inside a request session already bound by
    identity.service.resolve_principal(). Same values, same rule for the lead scope.
    """
    from app.core.db import bind_tenant, bind_user

    assert principal.tenant_id is not None and principal.user_id is not None
    bind_tenant(session, principal.tenant_id)
    managers = {"sales_manager", "tenant_admin"}
    scope = "all" if any(role.value in managers for role in principal.roles) else "own"
    bind_user(session, principal.user_id, scope)
