"""Monitoring utilities leveraging Prometheus client."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "twinops_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_latency_seconds = Histogram(
    "twinops_http_request_latency_seconds",
    "HTTP request latency",
    ["method", "path"],
)


def observe_request(method: str, path: str, status: int, duration_seconds: float) -> None:
    http_requests_total.labels(method=method, path=path, status=str(status)).inc()
    http_request_latency_seconds.labels(method=method, path=path).observe(duration_seconds)
