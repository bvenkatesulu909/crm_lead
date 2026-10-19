"""Shared pytest fixtures.

Tests in this folder never use a real database: their Settings point at an address where
nothing listens. Database tests live in tests/db/ and have their own fixtures.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.auth_helpers import TEST_ISSUER, TokenFactory

FRONTEND_ORIGIN = "http://localhost:3000"
# Port 1 on localhost: connections are refused immediately. Not a real credential.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://nobody:unused@127.0.0.1:1/unreachable"


@pytest.fixture(scope="session")
def token_factory() -> TokenFactory:
    # One RSA key per test run (generating keys is slow).
    return TokenFactory()


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests must not depend on a developer's local .env file.
    return Settings(
        _env_file=None,
        environment="test",
        cors_allowed_origins=[FRONTEND_ORIGIN],
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
    )


@pytest.fixture
def client(settings: Settings, token_factory: TokenFactory) -> Iterator[TestClient]:
    app = create_app(settings, token_verifier=token_factory.verifier())
    with TestClient(app) as test_client:
        yield test_client
