"""Kafka event publisher for TwinOps."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

from aiokafka import AIOKafkaProducer
from opentelemetry import trace

from backend.core.config import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class EventPublisher:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._lock = asyncio.Lock()

    async def _ensure_producer(self) -> AIOKafkaProducer | None:
        if self._producer and not self._producer._closed:
            return self._producer

        async with self._lock:
            if self._producer and not self._producer._closed:
                return self._producer
            try:
                self._producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
                await self._producer.start()
            except Exception as exc:  # pragma: no cover - Kafka optional
                logger.warning("Kafka producer unavailable: %s", exc)
                self._producer = None
        return self._producer

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        producer = await self._ensure_producer()
        if producer is None:
            return
        encoded = json.dumps(payload).encode("utf-8")
        with tracer.start_as_current_span("kafka.publish") as span:
            span.set_attribute("messaging.system", "kafka")
            span.set_attribute("messaging.destination", topic)
            span.set_attribute("payload.bytes", len(encoded))
            try:
                await producer.send_and_wait(topic, encoded)
            except Exception as exc:  # pragma: no cover - Kafka optional
                span.record_exception(exc)
                logger.error("Failed to publish event: %s", exc)

    async def close(self) -> None:
        if self._producer:
            await self._producer.stop()
            self._producer = None


event_publisher = EventPublisher()
