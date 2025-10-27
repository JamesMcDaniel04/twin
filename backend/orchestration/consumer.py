"""Kafka consumer that delivers asynchronous responses back to Slack."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaConsumer

from backend.core.config import settings
from backend.integrations.slack.bot import slack_bot

logger = logging.getLogger(__name__)


class ResponseConsumer:
    """Consumes TwinOps response events and forwards them to Slack."""

    def __init__(self) -> None:
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if not settings.KAFKA_BOOTSTRAP_SERVERS:
            logger.warning("Kafka bootstrap servers not configured; response consumer disabled.")
            return

        self._consumer = AIOKafkaConsumer(
            "twinops.responses",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            enable_auto_commit=True,
            value_deserializer=lambda data: json.loads(data.decode("utf-8")),
        )

        try:
            await self._consumer.start()
        except Exception as exc:  # pragma: no cover - network errors
            logger.error("Failed to start Kafka consumer: %s", exc)
            self._consumer = None
            return

        self._task = asyncio.create_task(self._consume())
        logger.info("Kafka response consumer started.")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._consumer:
            await self._consumer.stop()
            self._consumer = None

    async def _consume(self) -> None:
        assert self._consumer is not None
        try:
            async for message in self._consumer:
                payload: Dict[str, Any] = message.value or {}
                await slack_bot.dispatch_async_response(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Kafka consumer encountered an error: %s", exc)


response_consumer = ResponseConsumer()
