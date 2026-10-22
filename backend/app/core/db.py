"""Database connection setup (SQLAlchemy 2.x, synchronous, psycopg 3 driver).

- ``create_db_engine`` builds the connection pool. It does not connect until first use.
- ``get_db_session`` is a FastAPI dependency: one Session per request, always closed afterwards.

Tables are created ONLY by Alembic migrations, never by ``Base.metadata.create_all``.
"""

import uuid
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

# PostgreSQL setting read by the RLS policies (crm_current_tenant(), ADR 0009).
TENANT_SETTING = "app.tenant_id"


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
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    # Re-apply the tenant at the start of EVERY transaction (ADR 0009): some request paths commit
    # mid-request, and a SET LOCAL without re-application would silently disappear.
    if not event.contains(Session, "after_begin", _apply_tenant_setting):
        event.listen(Session, "after_begin", _apply_tenant_setting)
    return factory


def bind_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    """Remember the tenant on the Session and apply it to the current transaction.

    The value comes only from the verified Principal (never from a request parameter). The
    after_begin listener re-applies it after every commit/rollback.
    """
    session.info["tenant_id"] = str(tenant_id)
    session.execute(
        text("select set_config(:name, :tenant, true)"),
        {"name": TENANT_SETTING, "tenant": str(tenant_id)},
    )


def clear_tenant(session: Session) -> None:
    """Remove the tenant setting from the current transaction (tests / defensive cleanup)."""
    session.info.pop("tenant_id", None)
    session.execute(
        text("select set_config(:name, '', true)"),
        {"name": TENANT_SETTING},
    )


def _apply_tenant_setting(session: Session, transaction: object, connection: object) -> None:
    tenant = session.info.get("tenant_id")
    if tenant:
        connection.execute(  # type: ignore[attr-defined]
            text("select set_config(:name, :tenant, true)"),
            {"name": TENANT_SETTING, "tenant": tenant},
        )


def get_db_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


def check_database(engine: Engine) -> None:
    """Raise if the database cannot answer a trivial query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def check_vector_store(engine: Engine) -> None:
    """Readiness for the RAG store: pgvector extension and the HNSW index must exist."""
    with engine.connect() as connection:
        extension = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        index = connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                "WHERE indexname = 'ix_kb_chunks_embedding_hnsw')"
            )
        )
        if not extension or not index:
            raise RuntimeError("pgvector extension or HNSW index is missing")
