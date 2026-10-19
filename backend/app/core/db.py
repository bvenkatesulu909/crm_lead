"""Database connection setup (SQLAlchemy 2.x, synchronous, psycopg 3 driver).

- ``create_db_engine`` builds the connection pool. It does not connect until first use.
- ``get_db_session`` is a FastAPI dependency: one Session per request, always closed afterwards.

Tables are created ONLY by Alembic migrations, never by ``Base.metadata.create_all``.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        # Test each pooled connection before use, so a database restart does not cause errors.
        pool_pre_ping=True,
        connect_args={
            "application_name": settings.app_name,
            "connect_timeout": 5,
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after commit (e.g. to build the response).
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


def check_database(engine: Engine) -> None:
    """Raise if the database cannot answer a trivial query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
