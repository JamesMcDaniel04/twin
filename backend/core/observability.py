"""OpenTelemetry initialization helpers for TwinOps services."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

from backend.core.config import settings

try:  # pragma: no cover - optional dependency
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
except ImportError:  # pragma: no cover - OTLP exporter optional
    OTLPSpanExporter = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
_TRACING_INITIALIZED = False


def setup_tracing(app: Optional[FastAPI] = None) -> None:
    """Configure OpenTelemetry tracers and instrument FastAPI if requested."""

    global _TRACING_INITIALIZED
    if not _TRACING_INITIALIZED:
        resource = Resource.create(
            {
                "service.name": settings.API_TITLE.lower().replace(" ", "-"),
                "service.version": settings.API_VERSION,
                "environment": settings.ENVIRONMENT,
            }
        )

        provider = TracerProvider(resource=resource)
        exporter = _select_exporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _TRACING_INITIALIZED = True
        logger.info("OpenTelemetry tracing initialized with %s exporter", exporter.__class__.__name__)

    if app is not None:
        FastAPIInstrumentor.instrument_app(app)


def _select_exporter():
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        if OTLPSpanExporter is None:
            logger.warning(
                "OTEL_EXPORTER_OTLP_ENDPOINT is set but the OTLP exporter is unavailable; falling back to Jaeger."
            )
        else:
            headers = _parse_headers(settings.OTEL_EXPORTER_OTLP_HEADERS)
            return OTLPSpanExporter(endpoint=str(settings.OTEL_EXPORTER_OTLP_ENDPOINT), headers=headers or None)
    return _create_jaeger_exporter()


def _parse_headers(raw_headers: Optional[str]) -> Dict[str, str]:
    if not raw_headers:
        return {}
    pairs = {}
    for item in raw_headers.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def _create_jaeger_exporter() -> JaegerExporter:
    if settings.OTEL_EXPORTER_JAEGER_ENDPOINT:
        return JaegerExporter(collector_endpoint=str(settings.OTEL_EXPORTER_JAEGER_ENDPOINT))
    return JaegerExporter(
        agent_host_name=settings.JAEGER_AGENT_HOST,
        agent_port=settings.JAEGER_AGENT_PORT,
    )


__all__ = ["setup_tracing"]

