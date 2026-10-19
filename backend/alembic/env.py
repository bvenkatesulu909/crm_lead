"""Alembic migration environment: tells Alembic where the models and the database are."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import MigrationSettings
from app.model_registry import metadata

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    # disable_existing_loggers=False: don't silence the application's own loggers.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = metadata


def _database_url() -> str:
    # Tests pass the URL in config.attributes; otherwise read CRM_MIGRATION_DATABASE_URL.
    # (Not via alembic.ini: configparser would mangle "%" characters in passwords.)
    url = config.attributes.get("database_url")
    if url:
        return str(url)
    return MigrationSettings().migration_database_url.get_secret_value()


def run_migrations_offline() -> None:
    """``alembic upgrade head --sql``: print the SQL instead of running it."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # One transaction per migration file: a failure never leaves a half-applied file.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
