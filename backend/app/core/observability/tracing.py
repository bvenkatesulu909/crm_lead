"""OpenTelemetry tracing, opt-in via environment (R6). A no-op when disabled."""

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import Settings

logger = logging.getLogger(__name__)


def configure_tracing(app: Any, engine: Engine, settings: Settings) -> None:
    """Instrument FastAPI, SQLAlchemy and httpx only when an OTLP endpoint is configured."""
    if not (settings.otel_enabled and settings.otel_endpoint):
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": settings.otel_service_name,
                    "service.version": app.version,
                    "deployment.environment": settings.environment,
                }
            ),
            sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_ratio)),
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        # SQLAlchemy 2.1.5 is newer than opentelemetry-instrumentation-sqlalchemy supports
        # (<2.1.0), so add minimal DB spans ourselves (no SQL parameters, no customer data).
        _instrument_sqlalchemy_spans(engine, provider)
        logger.info("OpenTelemetry tracing enabled", extra={"endpoint": settings.otel_endpoint})
    except Exception as exc:  # noqa: BLE001 - tracing must never stop the API from starting
        logger.warning("tracing could not be enabled", extra={"error": type(exc).__name__})


def _instrument_sqlalchemy_spans(engine: Engine, provider: Any) -> None:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode

    tracer = trace.get_tracer("crm-lead.db", tracer_provider=provider)

    def before(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        span = tracer.start_span("db.query", kind=SpanKind.CLIENT)
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.operation", statement.strip().split(" ", 1)[0][:20])
        conn.info["_otel_db_span"] = span

    def after(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        span = conn.info.pop("_otel_db_span", None)
        if span is not None:
            span.end()

    def on_error(exception_context: Any) -> None:
        conn = exception_context.connection
        span = conn.info.pop("_otel_db_span", None) if conn is not None else None
        if span is not None:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(exception_context.original_exception)
            span.end()

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    event.listen(engine, "handle_error", on_error)
    logger.info("SQLAlchemy fallback DB spans enabled")
