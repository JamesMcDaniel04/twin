#!/usr/bin/env python
"""
Emit a diagnostic trace span to verify OpenTelemetry exporter configuration.

Usage:
    poetry run python scripts/verify_tracing.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from opentelemetry import trace

from backend.core.observability import setup_tracing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("twinops.telemetry")


async def main() -> None:
    setup_tracing()
    tracer = trace.get_tracer("twinops.telemetry.verifier")

    with tracer.start_as_current_span("telemetry_verification") as span:
        span.set_attribute("twinops.verification.timestamp", datetime.utcnow().isoformat())
        span.set_attribute("twinops.verification.hostname", os.uname().nodename)
        span.set_attribute("twinops.verification.success", True)
        logger.info("Emitted verification span. Check your Jaeger/Tempo backend for span name 'telemetry_verification'.")


if __name__ == "__main__":
    asyncio.run(main())

