"""Vector index management for TwinOps."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List, Tuple

from backend.core.database import database_manager

logger = logging.getLogger(__name__)


class VectorIndex:
    """Pinecone index helper."""

    async def upsert(self, namespace: str, vectors: Iterable[Tuple[str, List[float], dict]]) -> None:
        index = database_manager.index
        if index is None:
            logger.warning("Pinecone index not available; skipping upsert.")
            return

        items = list(vectors)
        if not items:
            return

        await asyncio.to_thread(index.upsert, vectors=items, namespace=namespace)


vector_index = VectorIndex()
