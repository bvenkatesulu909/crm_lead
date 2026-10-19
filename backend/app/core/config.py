"""Application configuration, read from environment variables (and an optional .env file).

Every setting has the prefix ``CRM_`` in the environment, e.g. ``CRM_LOG_LEVEL=DEBUG``.
Invalid values stop the application at startup instead of failing later at runtime.
"""

from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_ENV_CONFIG = SettingsConfigDict(
    env_prefix="CRM_",
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)
_DATABASE_URL_PREFIX = "postgresql+psycopg://"


def _require_postgres_url(value: SecretStr) -> SecretStr:
    # SecretStr keeps the password out of logs, error messages and repr().
    if not value.get_secret_value().startswith(_DATABASE_URL_PREFIX):
        raise ValueError(f"Database URLs must start with {_DATABASE_URL_PREFIX!r}.")
    return value


class Settings(BaseSettings):
    model_config = _ENV_CONFIG

    app_name: str = "crm-lead-api"
    environment: Environment = "development"
    log_level: LogLevel = "INFO"
    docs_enabled: bool = True

    # NoDecode lets us write a plain comma-separated list in .env instead of JSON.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # Connection used by the running API (the restricted app role). Required.
    database_url: SecretStr
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: float = Field(default=10, gt=0)
    # Any single SQL statement running longer than this is cancelled by PostgreSQL.
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)

    _check_database_url = field_validator("database_url")(_require_postgres_url)

    # OpenID Connect (Keycloak). Access tokens must be issued by exactly this issuer and
    # name this audience. Required: there is no way to run the API without token checks.
    oidc_issuer: str
    oidc_audience: str = "crm-api"
    # Where the issuer publishes its public signing keys. Defaults to Keycloak's standard path.
    oidc_jwks_url: str | None = None
    # Tolerated clock difference between Keycloak and this server when checking exp/nbf/iat.
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=120)

    # User administration through Keycloak's admin API (ADR 0004). The "crm-user-admin" client
    # may only manage users of the CRM realm. Without a secret, user administration answers 503
    # and everything else keeps working.
    keycloak_admin_client_id: str = "crm-user-admin"
    keycloak_admin_client_secret: SecretStr | None = None
    # Where invited people land after setting their password (the web app's login page).
    web_app_url: str = "http://localhost:3000"
    # Lifetime of set-your-password links sent by e-mail.
    invite_link_lifespan_seconds: int = Field(default=72 * 3600, ge=3600, le=14 * 24 * 3600)

    # AI assistant (ADR 0003). Without a key the assistant answers 503 and the portal hides it.
    # The key stays on the server; customers' questions and the tool results the assistant
    # reads are sent to Anthropic.
    anthropic_api_key: SecretStr | None = None
    # Needed only for user-level keys (sk-ant-usr-...): Anthropic then requires the workspace
    # to bill and log requests to. Workspace keys (sk-ant-api...) don't need it. Not a secret.
    anthropic_workspace_id: str | None = Field(default=None, pattern=r"^wrkspc_[A-Za-z0-9]+$")
    assistant_model: str = "claude-opus-5-5"
    assistant_max_tokens: int = Field(default=1024, ge=128, le=8192)
    # Tool calls the model may make while answering one message.
    assistant_max_tool_rounds: int = Field(default=6, ge=1, le=20)
    assistant_messages_per_hour: int = Field(default=30, ge=1, le=1000)
    assistant_timeout_seconds: float = Field(default=60, gt=0, le=300)

    # S3-compatible file store (ADR 0005; SeaweedFS locally). Without keys, features that store
    # files answer 503 and everything else keeps working.
    files_s3_endpoint: str = Field(default="127.0.0.1:8333", pattern=r"^[A-Za-z0-9.\-]+:\d{1,5}$")
    files_s3_secure: bool = False
    files_s3_access_key: SecretStr | None = None
    files_s3_secret_key: SecretStr | None = None
    files_s3_bucket: str = Field(
        default="crm-files", pattern=r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$"
    )
    # Largest file the API will store or serve.
    files_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)

    # Outgoing e-mail via SMTP (ADR 0005). Locally Mailpit catches everything (127.0.0.1:2525).
    smtp_host: str = "127.0.0.1"
    smtp_port: int = Field(default=2525, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_timeout_seconds: float = Field(default=15, gt=0, le=120)
    mail_from: str = Field(default="CRM <no-reply@crm.localhost>", min_length=3, max_length=200)

    # Background worker (outbox jobs, ADR 0005).
    worker_poll_seconds: float = Field(default=2, gt=0, le=60)
    worker_max_attempts: int = Field(default=5, ge=1, le=20)
    # Workflow rules (ADR 0006): automatic actions per organisation per hour, at most.
    workflow_actions_per_hour: int = Field(default=500, ge=1, le=100_000)

    @field_validator("oidc_issuer")
    @classmethod
    def _validate_issuer(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc or value.endswith("/"):
            raise ValueError("oidc_issuer must be an absolute URL without a trailing slash.")
        return value

    @model_validator(mode="after")
    def _production_requires_https(self) -> "Settings":
        if self.environment == "production" and not self.oidc_issuer.startswith("https://"):
            raise ValueError("In production the OIDC issuer must use https://.")
        return self

    @model_validator(mode="after")
    def _production_requires_secure_transport(self) -> "Settings":
        if self.environment == "production" and not self.files_s3_secure:
            raise ValueError("In production the file store must use HTTPS (files_s3_secure).")
        return self

    @property
    def files_configured(self) -> bool:
        return self.files_s3_access_key is not None and self.files_s3_secret_key is not None

    @property
    def keycloak_base_url(self) -> str:
        """http://host:port of Keycloak, derived from the issuer (".../realms/<realm>")."""
        return self.oidc_issuer.split("/realms/")[0]

    @property
    def keycloak_realm(self) -> str:
        return self.oidc_issuer.rsplit("/realms/", 1)[1]

    @property
    def resolved_jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer}/protocol/openid-connect/certs"

    @field_validator(
        "anthropic_api_key",
        "keycloak_admin_client_secret",
        "anthropic_workspace_id",
        "files_s3_access_key",
        "files_s3_secret_key",
        "smtp_username",
        "smtp_password",
        mode="before",
    )
    @classmethod
    def _empty_secret_is_none(cls, value: Any) -> Any:
        # "CRM_ANTHROPIC_API_KEY=" (copied from .env.example) means "not configured".
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase_log_level(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        # The browser compares origins exactly, so anything other than scheme://host[:port]
        # would silently never match. A wildcard would let any website call the API.
        for origin in origins:
            if origin == "*":
                raise ValueError("Wildcard '*' is not allowed; list each origin explicitly.")
            parts = urlsplit(origin)
            if (
                parts.scheme not in ("http", "https")
                or not parts.netloc
                or parts.path
                or parts.query
                or parts.fragment
            ):
                raise ValueError(
                    f"Invalid CORS origin {origin!r}: use scheme://host[:port] "
                    "with no path and no trailing slash."
                )
        return origins


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()


class MigrationSettings(BaseSettings):
    """Settings for Alembic only: it connects as the schema owner role, not the app role."""

    model_config = _ENV_CONFIG

    migration_database_url: SecretStr

    _check_database_url = field_validator("migration_database_url")(_require_postgres_url)
