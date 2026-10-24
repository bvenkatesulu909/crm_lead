from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import MigrationSettings, Settings
from tests.conftest import UNREACHABLE_DATABASE_URL


@pytest.fixture(autouse=True)
def _database_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The database URL is required; provide one so each test checks only what it names.
    monkeypatch.setenv("CRM_DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("CRM_OIDC_ISSUER", "http://localhost:9080/realms/crm")
    monkeypatch.delenv("CRM_MIGRATION_DATABASE_URL", raising=False)


def test_defaults_are_safe_for_local_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRM_CORS_ALLOWED_ORIGINS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.cors_allowed_origins == ["http://localhost:3000"]
    assert settings.environment == "development"


def test_origins_are_read_from_comma_separated_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CRM_CORS_ALLOWED_ORIGINS", "http://localhost:3000, https://crm.example.test"
    )

    settings = Settings(_env_file=None)

    assert settings.cors_allowed_origins == ["http://localhost:3000", "https://crm.example.test"]


@pytest.mark.parametrize(
    "bad_origin",
    [
        "*",
        "http://localhost:3000/",  # trailing slash never matches the browser's Origin header
        "http://localhost:3000/app",
        "localhost:3000",
        "ftp://localhost",
    ],
)
def test_invalid_cors_origins_are_rejected(bad_origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_allowed_origins=[bad_origin])


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRM_LOG_LEVEL", "debug")

    assert Settings(_env_file=None).log_level == "DEBUG"


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRM_ENVIRONMENT", "staging-typo")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRM_DATABASE_URL")

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "bad_url",
    ["sqlite:///crm.db", "postgresql://user@127.0.0.1/crm", "mysql+pymysql://u@h/db"],
)
def test_only_postgres_psycopg_urls_are_accepted(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=bad_url)


def test_database_password_is_hidden_in_repr_and_errors() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://crm_app:s3cret-value@127.0.0.1/crm"
    )

    assert "s3cret-value" not in repr(settings)
    assert "s3cret-value" not in str(settings.model_dump())


def test_migration_url_is_required_for_alembic() -> None:
    with pytest.raises(ValidationError, match="migration_database_url"):
        MigrationSettings(_env_file=None)


def test_oidc_issuer_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRM_OIDC_ISSUER")

    with pytest.raises(ValidationError, match="oidc_issuer"):
        Settings(_env_file=None)


@pytest.mark.parametrize("bad_issuer", ["localhost:9080/realms/crm", "http://kc/realms/crm/"])
def test_malformed_oidc_issuer_is_rejected(bad_issuer: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, oidc_issuer=bad_issuer)


def test_production_requires_https_issuer() -> None:
    with pytest.raises(ValidationError, match="https"):
        Settings(_env_file=None, environment="production", oidc_issuer="http://kc.test/realms/crm")


def test_jwks_url_defaults_to_keycloak_path() -> None:
    settings = Settings(_env_file=None)

    assert settings.resolved_jwks_url == (
        "http://localhost:9080/realms/crm/protocol/openid-connect/certs"
    )


def test_anthropic_workspace_id_is_validated_and_sent() -> None:
    from pydantic import ValidationError

    from app.modules.assistant.llm import ClaudeChatModel

    base: dict[str, Any] = {
        "_env_file": None,
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/db",
        "oidc_issuer": "http://localhost:9080/realms/crm",
        "anthropic_api_key": "sk-ant-usr-test",
    }
    with pytest.raises(ValidationError):
        Settings(**base, anthropic_workspace_id="not-a-workspace")
    assert Settings(**base, anthropic_workspace_id="").anthropic_workspace_id is None

    model = ClaudeChatModel(Settings(**base, anthropic_workspace_id="wrkspc_01Test"))
    assert model._client.default_headers["anthropic-workspace-id"] == "wrkspc_01Test"
    plain = ClaudeChatModel(Settings(**base))
    assert "anthropic-workspace-id" not in plain._client.default_headers
