"""Embedding generation utilities."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List

from openai import APIError, AsyncOpenAI

from backend.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Wrapper around OpenAI embedding API with retry handling."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.EMBEDDING_MODEL
        self.batch_size = 16
        self.max_retries = 3

    async def generate(self, chunks: Iterable[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        chunk_list = list(chunks)
        for i in range(0, len(chunk_list), self.batch_size):
            batch = chunk_list[i : i + self.batch_size]
            embeddings.extend(await self._embed_batch(batch))
        return embeddings

    async def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self.client.embeddings.create(model=self.model, input=batch)
                return [item.embedding for item in response.data]
            except APIError as exc:
                logger.warning("Embedding request failed (attempt %s/%s): %s", attempt, self.max_retries, exc)
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(2**attempt)
        return []
