"""Application entry point.

Run locally (from the backend folder, with the virtual environment active):

    uvicorn app.main:create_app --factory --reload

"--factory" tells uvicorn to call create_app() itself. Nothing is built at import time, so
importing this module (e.g. in tests) never needs a real .env file or database.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.ai.embeddings import Embedder, build_embedder
from app.core.auth.identity_admin import IdentityAdmin, build_identity_admin
from app.core.auth.tokens import JwksKeyProvider, TokenVerifier
from app.core.config import Settings, get_settings
from app.core.db import create_db_engine, create_session_factory
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.observability.metrics import MetricsMiddleware
from app.core.observability.tracing import configure_tracing
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.storage import FileStore, build_file_store
from app.modules.assistant.llm import ChatModel, build_chat_model
from app.modules.knowledge.retrieval import Reranker, build_reranker
from app.modules.voice.provider import SpeechProvider, build_speech_provider

API_V1_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None,
    token_verifier: TokenVerifier | None = None,
    identity_admin: IdentityAdmin | None = None,
    chat_model: ChatModel | None = None,
    file_store: FileStore | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Tests pass their own Settings, and a TokenVerifier that trusts a test key pair instead of
    Keycloak. The verification rules are identical; only the source of public keys differs.
    They also pass an in-memory IdentityAdmin instead of Keycloak's admin API.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Close pooled database connections cleanly on shutdown.
        engine.dispose()

    app = FastAPI(
        title="crm-lead API",
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.token_verifier = token_verifier or TokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        key_provider=JwksKeyProvider(settings.resolved_jwks_url),
        clock_skew_seconds=settings.oidc_clock_skew_seconds,
    )

    app.state.identity_admin = identity_admin or build_identity_admin(settings)
    # The AI assistant's model (Claude, or "not configured" without an API key).
    app.state.chat_model = chat_model or build_chat_model(settings)
    speech_provider: SpeechProvider | None = build_speech_provider(settings)
    app.state.speech_provider = speech_provider
    # S3 file store (ADR 0005); answers 503 if no keys are configured.
    app.state.file_store = file_store or build_file_store(settings)
    # Local text embeddings (ADR 0010) and the optional reranker (ADR 0011).
    app.state.embedder = embedder or build_embedder(settings)
    app.state.reranker = reranker or build_reranker(settings)

    register_exception_handlers(app)

    # Middleware added last runs first. CORS is outermost so that even error responses
    # carry CORS headers and the browser lets the frontend read them.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        # Cookies are not sent to the API: the Next.js server calls it with a bearer token.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )

    app.include_router(api_router, prefix=API_V1_PREFIX)
    configure_tracing(app, engine, settings)
    return app
