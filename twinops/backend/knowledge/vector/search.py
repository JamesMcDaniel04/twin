"""Similarity search helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.core.database import database_manager

logger = logging.getLogger(__name__)


class VectorSearch:
    """Execute vector similarity queries against Pinecone."""

    async def search(self, embedding: List[float], *, top_k: int, filter: Optional[Dict[str, Any]] = None) -> List[dict]:
        index = database_manager.index
        if index is None:
            logger.warning("Pinecone index not available; returning empty results.")
            return []

        response = await asyncio.to_thread(
            index.query, vector=embedding, top_k=top_k, include_metadata=True, filter=filter
        )
        return response["matches"] if isinstance(response, dict) else response.matches


vector_search = VectorSearch()
