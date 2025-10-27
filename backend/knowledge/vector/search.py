"""Vector similarity service with Pinecone fallback support."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from backend.core.database import database_manager


@dataclass
class VectorSearchMatch:
    document_id: str
    score: float
    metadata: Dict[str, object]


class VectorSearchService:
    """Abstraction over vector search index with in-memory fallback."""

    def __init__(self) -> None:
        self._fallback_store: Dict[str, Dict[str, object]] = {}

    async def upsert(self, document_id: str, embedding: Iterable[float], metadata: Dict[str, object]) -> None:
        index = database_manager.index
        if index is None:
            self._fallback_store[document_id] = {
                "embedding": list(embedding),
                "metadata": metadata,
            }
            return

        await asyncio.to_thread(
            index.upsert,
            [(document_id, list(embedding), metadata)],
        )

    async def search(self, embedding: Iterable[float], top_k: int = 5, filter: Optional[Dict[str, object]] = None) -> List[VectorSearchMatch]:
        index = database_manager.index
        if index is None:
            return self._search_fallback(list(embedding), top_k, filter or {})

        response = await asyncio.to_thread(
            index.query,
            vector=list(embedding),
            top_k=top_k,
            filter=filter or {},
            include_metadata=True,
        )
        matches = []
        for match in response.matches:
            matches.append(
                VectorSearchMatch(
                    document_id=match.id,
                    score=match.score,
                    metadata=match.metadata or {},
                )
            )
        return matches

    def _search_fallback(self, embedding: List[float], top_k: int, filter: Dict[str, object]) -> List[VectorSearchMatch]:
        if not embedding:
            return []

        results: List[VectorSearchMatch] = []
        for document_id, payload in self._fallback_store.items():
            if filter:
                if not all(payload["metadata"].get(k) == v for k, v in filter.items()):
                    continue
            stored_embedding = payload.get("embedding", [])
            score = self._cosine_similarity(embedding, stored_embedding)
            results.append(
                VectorSearchMatch(
                    document_id=document_id,
                    score=score,
                    metadata=payload.get("metadata", {}),
                )
            )

        results.sort(key=lambda match: match.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _cosine_similarity(lhs: List[float], rhs: List[float]) -> float:
        if not lhs or not rhs or len(lhs) != len(rhs):
            return 0.0
        dot = sum(l * r for l, r in zip(lhs, rhs))
        lhs_norm = sum(l * l for l in lhs) ** 0.5
        rhs_norm = sum(r * r for r in rhs) ** 0.5
        if lhs_norm == 0 or rhs_norm == 0:
            return 0.0
        return dot / (lhs_norm * rhs_norm)
