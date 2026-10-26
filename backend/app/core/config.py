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

    # AI runtime: "anthropic" (default, existing behaviour) or "deepseek" (OpenAI-compatible).
    # "fake" = a scripted model for tests and local demos (no key); refused in production.
    ai_provider: Literal["anthropic", "deepseek", "fake"] = "anthropic"
    # AI assistant (ADR 0003). Without a key the assistant answers 503 and the portal hides it.
    # The key stays on the server; customers' questions and the tool results the assistant
    # reads are sent to the selected provider.
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
    # DeepSeek (OpenAI-compatible API). Key stays in the environment; never logged or committed.
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # Public website chat (ADR 0013). Off unless BOTH the tenant slug and the server key are set.
    # The key is shared only by the API and the Next.js server; browsers never see it.
    public_chat_tenant_slug: str | None = None
    public_chat_server_key: SecretStr | None = None
    # "fake" answers without any model (tests and local demos) and is refused in production.
    public_chat_provider: Literal["deepseek", "anthropic", "fake"] = "deepseek"
    public_chat_messages_per_ip_hour: int = Field(default=20, ge=1, le=10_000)
    public_chat_sessions_per_ip_hour: int = Field(default=3, ge=1, le=1_000)
    public_chat_messages_per_session: int = Field(default=30, ge=1, le=500)
    # A ceiling on the model bill: visitor messages per organisation per day.
    public_chat_messages_per_day: int = Field(default=500, ge=1, le=1_000_000)
    # Conversations that never became a lead are deleted after this many quiet days (privacy).
    public_chat_retention_days: int = Field(default=30, ge=1, le=3650)
    # Server-side speech gateway (STT/TTS), OpenAI-compatible audio API. Disabled without a key.
    voice_enabled: bool = True
    voice_provider: Literal["openai", "elevenlabs", "local"] = "openai"
    # Local mode: Whisper model size, path to a Piper .onnx voice, and the piper executable.
    voice_piper_command: str = "piper"
    voice_api_key: SecretStr | None = None
    voice_base_url: str = "https://api.openai.com/v1"
    voice_stt_model: str = "gpt-4o-mini-transcribe"
    voice_tts_model: str = "gpt-4o-mini-tts"
    voice_tts_voice: str = "alloy"
    voice_max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)

    # Knowledge-base embeddings (ADR 0010). A local ONNX model (fastembed) - text never leaves
    # the machine for indexing. Changing the model later means re-embedding every chunk.
    embeddings_model: str = "BAAI/bge-small-en-v1.5"
    embeddings_dimensions: int = Field(default=384, ge=1)
    embeddings_cache_dir: str | None = None

    # Retrieval (RAG R3, ADR 0011 starting settings; R5 tunes them with measurements).
    knowledge_candidates: int = Field(default=40, ge=5, le=200)
    knowledge_rrf_k: int = Field(default=60, ge=1, le=1000)
    knowledge_top_k: int = Field(default=5, ge=1, le=20)
    # Calibrated on 100 free cases (80 answerable / 20 unanswerable, 2026-10-21):
    # unanswerable max 0.620, answerable min 0.658 -> 0.64 keeps 100% of positives and rejects
    # 100% of negatives on that set. Re-calibrate whenever the embedding model or corpus changes.
    knowledge_min_similarity: float | None = Field(default=0.64, ge=0.0, le=1.0)
    # Cross-encoder reranker: re-scores the RRF top candidates, then the top-k is returned.
    # Measured 2026-10-21 on 13 free cases / 8 demo documents: hit@5/MRR gain +0.000. ADR 0011
    # says keep it off until a larger eval shows a measured gain, so the default is now False.
    # Flip to true for an experiment; it soft-fails to RRF order if the local model cannot load.
    knowledge_reranker_enabled: bool = False
    knowledge_reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    knowledge_rerank_candidates: int = Field(default=10, ge=1, le=50)

    # S3-compatible file store (ADR 0005; SeaweedFS locally). Without keys, features that store
    # files answer 503 and everything else keeps working.
    files_s3_endpoint: str = Field(default="127.0.0.1:9333", pattern=r"^[A-Za-z0-9.\-]+:\d{1,5}$")
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
    # Communication Center (ADR 0012): e-mails one person may send per hour - a guard against
    # mistakes, not a marketing tool.
    communication_emails_per_hour: int = Field(default=200, ge=1, le=10_000)
    # Approval queue for AI-proposed actions (ADR 0014): days until a pending proposal expires,
    # and how many may wait per person (a looping model can't flood the queue).
    agent_action_expiry_days: int = Field(default=7, ge=1, le=90)
    agent_action_pending_per_user: int = Field(default=20, ge=1, le=1_000)

    # Background worker (outbox jobs, ADR 0005).
    worker_poll_seconds: float = Field(default=2, gt=0, le=60)
    worker_max_attempts: int = Field(default=5, ge=1, le=20)
    # A worker that has not updated its heartbeat for this long is considered dead.
    worker_heartbeat_max_age_seconds: int = Field(default=120, ge=10, le=3600)

    # --- Operations (R6): metrics, tracing, AI cost. All environment-driven. ---
    # Prometheus metrics are served only on the token-protected /api/v1/internal/metrics route.
    # When no token is configured the route answers 404 (never public by accident).
    metrics_enabled: bool = True
    metrics_token: SecretStr | None = None
    # OpenTelemetry is a no-op unless both are set (no collector required to run the app).
    otel_enabled: bool = False
    otel_endpoint: str | None = None
    otel_service_name: str = "crm-lead-api"
    otel_sample_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    # Price per 1M tokens, used only to ESTIMATE cost (model prices change; set from the provider).
    ai_input_price_per_million: float = Field(default=0.0, ge=0.0)
    ai_output_price_per_million: float = Field(default=0.0, ge=0.0)
    # AI governance (ADR 0016). The platform switch refuses EVERY AI call for every organisation
    # (a leaked key, a runaway); the default budget is tokens per agent and organisation per month
    # for agents nobody has configured. There is no "unlimited": a cap is always in force.
    ai_disabled: bool = False
    agent_default_monthly_tokens: int = Field(default=2_000_000, ge=1, le=10_000_000_000)
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

    @model_validator(mode="after")
    def _public_chat_is_safe(self) -> "Settings":
        if self.environment == "production" and self.public_chat_provider == "fake":
            raise ValueError("The fake public chat provider can't be used in production.")
        if self.environment == "production" and self.ai_provider == "fake":
            raise ValueError(
                "The fake assistant provider (ai_provider) can't be used in production."
            )
        key = self.public_chat_server_key
        if key is not None and len(key.get_secret_value()) < 32:
            raise ValueError("public_chat_server_key must be at least 32 characters long.")
        return self

    @property
    def public_chat_enabled(self) -> bool:
        return bool(self.public_chat_tenant_slug) and self.public_chat_server_key is not None

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
        "deepseek_api_key",
        "public_chat_tenant_slug",
        "public_chat_server_key",
        "voice_api_key",
        "keycloak_admin_client_secret",
        "anthropic_workspace_id",
        "files_s3_access_key",
        "files_s3_secret_key",
        "smtp_username",
        "smtp_password",
        "metrics_token",
        "otel_endpoint",
        "embeddings_cache_dir",
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
