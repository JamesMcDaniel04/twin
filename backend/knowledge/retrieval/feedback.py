"""Feedback capture and aggregation for retrieval ranking."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List

from backend.core.database import database_manager

logger = logging.getLogger(__name__)


@dataclass
class FeedbackSignal:
    """User-provided feedback on a retrieval result."""

    query: str
    document_id: str
    user_id: str
    helpful: bool
    score: float
    channel: str = "ui"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())


class FeedbackManager:
    """Persist feedback in MongoDB when available, otherwise fall back to memory."""

    def __init__(self, collection: str = "retrieval_feedback", buffer_size: int = 500) -> None:
        self.collection = collection
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=buffer_size)

    def _collection(self):
        mongodb = database_manager.mongodb
        if mongodb is None:
            return None
        return mongodb["twinops"][self.collection]

    async def record(self, signal: FeedbackSignal) -> None:
        payload = asdict(signal)
        collection = self._collection()
        if collection is None:
            self._buffer.append(payload)
            logger.debug("Buffered feedback signal: %s", payload)
            return
        try:
            await collection.insert_one(payload)
        except Exception as exc:  # pragma: no cover - external dependency
            logger.warning("Failed to persist feedback to MongoDB: %s", exc)
            self._buffer.append(payload)

    async def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        collection = self._collection()
        if collection is None:
            return list(self._buffer)[-limit:]
        cursor = collection.find({}).sort("created_at", -1).limit(limit)
        return [document async for document in cursor]

    async def aggregate_component_feedback(self, limit: int = 100) -> Dict[str, float]:
        signals = await self.recent(limit)
        if not signals:
            return {}

        totals: Dict[str, float] = {"graph": 0.0, "vector": 0.0, "text": 0.0}
        counts: Dict[str, int] = {"graph": 0, "vector": 0, "text": 0}

        for signal in signals:
            metadata = signal.get("metadata") or {}
            components = metadata.get("component_scores") or {}
            modifier = 1.0 if signal.get("helpful") else -1.0
            for key in totals:
                if key in components:
                    totals[key] += float(components[key]) * modifier
                    counts[key] += 1

        return {key: totals[key] / counts[key] for key in totals if counts[key] > 0}

    async def recommend_weights(
        self,
        base_weights: Dict[str, float],
        *,
        learning_rate: float = 0.1,
        sample_size: int = 100,
    ) -> Dict[str, float]:
        """Return normalized weights adjusted using recent feedback signals."""

        adjustments = await self.aggregate_component_feedback(sample_size)
        if not adjustments:
            return base_weights

        updated = dict(base_weights)
        for component, delta in adjustments.items():
            updated[component] = max(0.0, updated.get(component, 0.0) + learning_rate * delta)

        total = sum(updated.values()) or 1.0
        return {component: weight / total for component, weight in updated.items()}
