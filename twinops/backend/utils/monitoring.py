from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.jaeger import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram


class MonitoringService:
    def __init__(
        self,
        jaeger_host: str = "localhost",
        jaeger_port: int = 6831,
        service_name: str = "twinops-backend",
    ) -> None:
        self.query_counter = Counter("queries_total", "Total queries processed")
        self.query_latency = Histogram("query_duration_seconds", "Query latency")
        self.active_twins = Gauge("active_twins", "Number of active digital twins")

        if not isinstance(trace.get_tracer_provider(), TracerProvider):
            resource = Resource.create({SERVICE_NAME: service_name})
            provider = TracerProvider(resource=resource)
            exporter = JaegerExporter(agent_host_name=jaeger_host, agent_port=jaeger_port)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)

        self.tracer = trace.get_tracer(__name__)

    @contextmanager
    def record_latency(self, label: Optional[str] = None):
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.query_latency.observe(duration)

    async def track_query(self, query_id: str) -> None:
        with self.tracer.start_as_current_span("process_query") as span:
            span.set_attribute("query.id", query_id)
            self.query_counter.inc()
            with self.record_latency():
                span.set_attribute("query.status", "processing")
