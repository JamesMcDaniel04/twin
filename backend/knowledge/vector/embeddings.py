"""Embedding generation utilities."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List, Optional, Type

try:  # Optional dependency
    from openai import APIError, AsyncOpenAI
except ImportError:  # pragma: no cover - optional dependency
    AsyncOpenAI = None  # type: ignore[assignment]

    class APIError(RuntimeError):  # type: ignore[override]
        """Fallback OpenAI exception placeholder."""

        pass

from backend.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Wrapper around OpenAI embedding API with deterministic offline fallback."""

    def __init__(self, *, fallback_dimensions: int | None = None) -> None:
        self.model = settings.EMBEDDING_MODEL
        self.batch_size = 16
        self.max_retries = 3
        self._fallback_dimensions = max(8, fallback_dimensions or int(settings.PINECONE_DIMENSION or 1536))

        api_key = settings.OPENAI_API_KEY
        if api_key and AsyncOpenAI is not None:
            self.client: AsyncOpenAI | None = AsyncOpenAI(api_key=api_key)
        else:
            if api_key and AsyncOpenAI is None:
                logger.warning(
                    "OPENAI_API_KEY provided but OpenAI client library is unavailable; using deterministic fallback embeddings."
                )
            else:
                logger.warning(
                    "OPENAI_API_KEY not configured; falling back to deterministic local embeddings for retrieval."
                )
            self.client = None

    async def generate(self, chunks: Iterable[str]) -> List[List[float]]:
        chunk_list = list(chunks)
        if not chunk_list:
            return []

        if self.client is None:
            return [self._offline_embedding(text) for text in chunk_list]

        embeddings: List[List[float]] = []
        for i in range(0, len(chunk_list), self.batch_size):
            batch = chunk_list[i : i + self.batch_size]
            embeddings.extend(await self._embed_batch(batch))
        return embeddings

    async def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        if self.client is None:
            return [self._offline_embedding(text) for text in batch]

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

    def _offline_embedding(self, text: str) -> List[float]:
        """Produce a deterministic, bounded embedding vector without external APIs."""

        if self._fallback_dimensions <= 0:
            return []

        tokens = text.lower().split()
        if not tokens:
            return [0.0] * self._fallback_dimensions

        vector = [0.0] * self._fallback_dimensions
        for index, token in enumerate(tokens):
            bucket = index % self._fallback_dimensions
            token_value = sum(ord(char) for char in token) % 997
            vector[bucket] += token_value / 997.0

        norm = sum(component * component for component in vector) ** 0.5 or 1.0
        return [component / norm for component in vector]
