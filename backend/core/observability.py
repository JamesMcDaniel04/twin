"""OpenTelemetry initialization helpers for TwinOps services."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

from backend.core.config import settings

_TRACING_INITIALIZED = False


def setup_tracing(app: Optional[FastAPI] = None) -> None:
    """Configure OpenTelemetry tracers and instrument FastAPI if requested."""

    global _TRACING_INITIALIZED
    if not _TRACING_INITIALIZED:
        resource = Resource.create({
            "service.name": settings.API_TITLE.lower().replace(" ", "-"),
            "service.version": settings.API_VERSION,
            "environment": settings.ENVIRONMENT,
        })

        provider = TracerProvider(resource=resource)
        exporter = _create_jaeger_exporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _TRACING_INITIALIZED = True

    if app is not None:
        FastAPIInstrumentor.instrument_app(app)


def _create_jaeger_exporter() -> JaegerExporter:
    if settings.OTEL_EXPORTER_JAEGER_ENDPOINT:
        return JaegerExporter(collector_endpoint=str(settings.OTEL_EXPORTER_JAEGER_ENDPOINT))
    return JaegerExporter(
        agent_host_name=settings.JAEGER_AGENT_HOST,
        agent_port=settings.JAEGER_AGENT_PORT,
    )


__all__ = ["setup_tracing"]

