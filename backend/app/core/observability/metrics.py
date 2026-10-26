"""Prometheus metrics for the API, RAG pipeline, AI calls and operational gauges (R6).

Rules:
- **Low cardinality only.** Labels are route TEMPLATES, status codes, job kinds, providers and
  fixed outcomes. Never tenant IDs, user IDs, questions, documents, tokens or prompts.
- The registry is private; the only exposure is the token-guarded internal route.
"""

import re
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import text
from sqlalchemy.engine import Engine
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "crm_http_requests_total",
    "HTTP requests by method, route template and status code.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "crm_http_request_duration_seconds",
    "HTTP request duration by method and route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)

AI_REQUESTS = Counter(
    "crm_ai_requests_total",
    "AI model calls by provider, model and outcome.",
    ["provider", "model", "outcome"],
    registry=REGISTRY,
)
AI_DURATION = Histogram(
    "crm_ai_request_duration_seconds",
    "AI model call duration by provider and model.",
    ["provider", "model"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120),
    registry=REGISTRY,
)
AI_TOKENS = Counter(
    "crm_ai_tokens_total",
    "AI tokens by provider, model and direction (input/output).",
    ["provider", "model", "direction"],
    registry=REGISTRY,
)
AI_COST = Counter(
    "crm_ai_estimated_cost_usd_total",
    "Estimated AI cost in USD (price table from environment; not a bill).",
    ["provider", "model"],
    registry=REGISTRY,
)
AI_REFUSALS = Counter(
    "crm_ai_refusals_total",
    "AI calls refused before reaching the model, by agent and reason (ADR 0016). No tenant label.",
    ["agent", "reason"],
    registry=REGISTRY,
)
AI_DROPPED_TOOL_CALLS = Counter(
    "crm_ai_dropped_tool_calls_total",
    "Tool calls a model made that its agent may not use (ADR 0016). No tenant label.",
    ["agent"],
    registry=REGISTRY,
)

RAG_SEARCHES = Counter(
    "crm_rag_searches_total",
    "Knowledge searches by outcome.",
    ["outcome"],
    registry=REGISTRY,
)
RAG_SEARCH_DURATION = Histogram(
    "crm_rag_stage_duration_seconds",
    "Retrieval/answer stage duration.",
    ["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)
RAG_ANSWERS = Counter(
    "crm_rag_answers_total",
    "Knowledge answers by outcome (answered/refused/ungrounded/unavailable).",
    ["outcome"],
    registry=REGISTRY,
)

DB_UP = Gauge(
    "crm_database_up",
    "1 when the last readiness/metrics query reached the database.",
    registry=REGISTRY,
)
PGVECTOR = Gauge(
    "crm_pgvector_check",
    "1 when the check passed: extension, HNSW index, expected schema revision.",
    ["check"],
    registry=REGISTRY,
)
OUTBOX_JOBS = Gauge("crm_outbox_jobs", "Outbox jobs by status.", ["status"], registry=REGISTRY)
WORKER_HEARTBEAT_AGE = Gauge(
    "crm_worker_heartbeat_age_seconds",
    "Seconds since the worker last wrote its heartbeat (-1 when never seen).",
    registry=REGISTRY,
)
KNOWLEDGE_DOCUMENTS = Gauge(
    "crm_knowledge_documents",
    "Knowledge documents by indexing status.",
    ["status"],
    registry=REGISTRY,
)
CHUNKS_MISSING_EMBEDDING = Gauge(
    "crm_knowledge_chunks_missing_embedding",
    "Chunks without an embedding (should stay at 0 after ingestion).",
    registry=REGISTRY,
)

_UUID_IN_PATH = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_NUMBER_IN_PATH = re.compile(r"/\d+(?=/|$)")


def _route_template(path: str) -> str:
    """Fallback when the router did not expose a template: strip IDs to keep labels bounded."""
    return _NUMBER_IN_PATH.sub("/{id}", _UUID_IN_PATH.sub("{id}", path))


_KNOWN_JOB_STATUSES = ("pending", "running", "done", "dead")
_KNOWN_DOCUMENT_STATUSES = ("processing", "indexed", "needs_review", "failed", "no_text")


class MetricsMiddleware:
    """Counts every request and its duration, labelled by route template (never by raw path)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").endswith("/internal/metrics"):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "UNKNOWN")
        started = time.perf_counter()
        status = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            # Mounted sub-routers expose only their relative path, so sanitize the real path
            # (UUIDs/numbers become {id}) - still bounded and never a raw record ID.
            template = _route_template(scope.get("path", "unmatched"))
            HTTP_REQUESTS.labels(method=method, route=template, status=str(status)).inc()
            HTTP_DURATION.labels(method=method, route=template).observe(
                time.perf_counter() - started
            )


def observe_ai_call(
    *,
    provider: str,
    model: str,
    outcome: str,
    seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    input_price_per_million: float = 0.0,
    output_price_per_million: float = 0.0,
) -> None:
    AI_REQUESTS.labels(provider=provider, model=model, outcome=outcome).inc()
    AI_DURATION.labels(provider=provider, model=model).observe(seconds)
    if input_tokens:
        AI_TOKENS.labels(provider=provider, model=model, direction="input").inc(input_tokens)
    if output_tokens:
        AI_TOKENS.labels(provider=provider, model=model, direction="output").inc(output_tokens)
    cost = (
        input_tokens * input_price_per_million + output_tokens * output_price_per_million
    ) / 1_000_000
    if cost > 0:
        AI_COST.labels(provider=provider, model=model).inc(cost)


def refresh_operational_gauges(engine: Engine) -> None:
    """Bounded read-only queries for gauges that must reflect the database at scrape time."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            DB_UP.set(1)
            extension = bool(
                connection.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                )
            )
            index = bool(
                connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                        "WHERE indexname = 'ix_kb_chunks_embedding_hnsw')"
                    )
                )
            )
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            PGVECTOR.labels(check="extension").set(1 if extension else 0)
            PGVECTOR.labels(check="hnsw_index").set(1 if index else 0)
            PGVECTOR.labels(check="schema_revision").set(1 if revision else 0)

            age = connection.scalar(
                text(
                    "SELECT EXTRACT(EPOCH FROM (now() - last_seen)) "
                    "FROM service_heartbeats WHERE name = 'worker'"
                )
            )
            WORKER_HEARTBEAT_AGE.set(float(age) if age is not None else -1.0)

            # The scrape has no tenant, so plain counts would be zero under RLS (ADR 0009).
            # ops_queue_counts() returns only cross-tenant aggregates per status.
            for status in _KNOWN_JOB_STATUSES:
                OUTBOX_JOBS.labels(status=status).set(0)
            for status in _KNOWN_DOCUMENT_STATUSES:
                KNOWLEDGE_DOCUMENTS.labels(status=status).set(0)
            CHUNKS_MISSING_EMBEDDING.set(0)
            for metric, status, total in connection.execute(
                text("SELECT metric, status, total FROM ops_queue_counts()")
            ):
                if metric == "outbox_jobs":
                    OUTBOX_JOBS.labels(status=str(status)).set(int(total))
                elif metric == "kb_documents":
                    KNOWLEDGE_DOCUMENTS.labels(status=str(status)).set(int(total))
                else:
                    CHUNKS_MISSING_EMBEDDING.set(int(total))
    except Exception:  # noqa: BLE001 - a scrape must never raise
        DB_UP.set(0)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def observe_request_metric(method: str, route: str, status: int, seconds: float) -> None:
    """Reusable for non-ASGI callers/tests."""
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, route=route).observe(seconds)


__all__ = [
    "AI_COST",
    "AI_DROPPED_TOOL_CALLS",
    "AI_REFUSALS",
    "AI_REQUESTS",
    "AI_TOKENS",
    "MetricsMiddleware",
    "REGISTRY",
    "RAG_ANSWERS",
    "RAG_SEARCHES",
    "metrics_payload",
    "observe_ai_call",
    "refresh_operational_gauges",
]
