"""Settings, read from environment variables (all have local-development defaults)."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    api_url: str = "http://localhost:8000/api/v1"
    issuer: str = "http://localhost:9080/realms/crm"
    client_id: str = "crm-mcp"
    # Must match the redirect URI registered on the crm-mcp Keycloak client.
    redirect_port: int = 8765
    login_timeout_seconds: int = 300
    # A runaway agent loop must not hammer the CRM; one tool call makes 1-4 API calls.
    max_calls_per_minute: int = 60

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.redirect_port}/callback"

    def validate(self) -> "Settings":
        # Tokens travel to both addresses: plain HTTP is only acceptable on this PC.
        for name, url in (("CRM_MCP_API_URL", self.api_url), ("CRM_MCP_ISSUER", self.issuer)):
            parts = urlsplit(url)
            if parts.scheme == "https":
                continue
            if parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS:
                continue
            raise ConfigError(f"{name} must use https (http is allowed only for localhost)")
        return self


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)
    defaults = Settings()
    try:
        port = int(env.get("CRM_MCP_REDIRECT_PORT", defaults.redirect_port))
    except ValueError as error:
        raise ConfigError("CRM_MCP_REDIRECT_PORT must be a number") from error
    try:
        per_minute = int(env.get("CRM_MCP_MAX_CALLS_PER_MINUTE", defaults.max_calls_per_minute))
    except ValueError as error:
        raise ConfigError("CRM_MCP_MAX_CALLS_PER_MINUTE must be a number (1-600)") from error
    if not 1 <= per_minute <= 600:
        raise ConfigError("CRM_MCP_MAX_CALLS_PER_MINUTE must be between 1 and 600")
    return Settings(
        api_url=env.get("CRM_MCP_API_URL", defaults.api_url).rstrip("/"),
        issuer=env.get("CRM_MCP_ISSUER", defaults.issuer).rstrip("/"),
        client_id=env.get("CRM_MCP_CLIENT_ID", defaults.client_id),
        redirect_port=port,
        max_calls_per_minute=per_minute,
    ).validate()
