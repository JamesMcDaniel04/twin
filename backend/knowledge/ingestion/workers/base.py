"""Common ingestion worker scaffolding."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.knowledge.ingestion.pipeline import IngestionPipeline
from backend.orchestration.publisher import event_publisher

logger = logging.getLogger(__name__)


class BaseIngestionWorker:
    """Base class shared across ingestion workers."""

    source: str = "unknown"

    def __init__(self, pipeline: Optional[IngestionPipeline] = None) -> None:
        self.pipeline = pipeline or IngestionPipeline()

    async def process_document(self, document_id: str, content: bytes, metadata: Dict[str, Any]) -> Optional[str]:
        """Ingest a single document with consistent error handling."""

        metadata = dict(metadata)
        metadata.setdefault("id", document_id)
        metadata.setdefault("mime_type", "text/plain")
        metadata.setdefault("title", metadata.get("name", document_id))

        try:
            ingested_id = await self.pipeline.ingest_document(self.source, content, metadata)
            await self._publish_ingestion_event(ingested_id, metadata)
            return ingested_id
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to ingest document %s from %s: %s", document_id, self.source, exc)
            return None

    async def _publish_ingestion_event(self, document_id: str, metadata: Dict[str, Any]) -> None:
        await event_publisher.publish(
            topic="twinops.ingestion.events",
            payload={
                "document_id": document_id,
                "source": self.source,
                "metadata": metadata,
            },
        )

    async def run(self) -> None:
        raise NotImplementedError
