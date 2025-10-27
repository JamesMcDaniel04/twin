"""Graph operations manager."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from neo4j import AsyncSession

from backend.core.config import settings
from backend.core.database import database_manager
from backend.knowledge.graph import queries

logger = logging.getLogger(__name__)


class GraphManager:
    """High-level graph operations for knowledge ingestion and context expansion."""

    def __init__(self) -> None:
        self._document_locks: Dict[str, asyncio.Lock] = {}
        self._lock_guard = asyncio.Lock()

    async def upsert_document(self, document: Dict[str, object], entities: List[Dict[str, object]]) -> None:
        """Create or update a document node and attach related entities."""

        driver = database_manager.neo4j
        if driver is None:
            logger.warning("Neo4j driver not initialized; skipping graph update.")
            return

        document_id = str(document["id"])
        lock = await self._acquire_lock(document_id)
        try:
            async with lock:
                async with driver.session() as session:  # type: AsyncSession
                    await session.execute_write(self._write_document, document)
                    if entities:
                        await session.execute_write(self._link_entities, document_id, entities)
        finally:
            await self._release_lock(document_id, lock)

    async def expand_context(
        self,
        query: str,
        *,
        limit: int = 25,
        max_depth: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """Return graph context for the provided query using APOC traversals."""

        driver = database_manager.neo4j
        if driver is None:
            logger.debug("Neo4j driver unavailable; returning empty graph context.")
            return []

        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return []

        traversal_depth = max_depth or settings.GRAPH_TRAVERSAL_MAX_DEPTH
        seed_limit = min(limit * 4, 100)

        async with driver.session() as session:  # type: AsyncSession
            result = await session.run(
                queries.APOC_TRAVERSE_CONTEXT,
                {
                    "terms": terms,
                    "limit": limit,
                    "max_depth": traversal_depth,
                    "seed_limit": seed_limit,
                },
            )
            records = await result.data()

        aggregated: Dict[str, Dict[str, object]] = {}
        for record in records:
            document_id = record["document_id"]
            entry = aggregated.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "title": record.get("title"),
                    "source": record.get("source"),
                    "nodes": set(),
                    "seed_entities": set(),
                    "relationships": [],
                    "metadata": (record.get("metadata") or {}) | {},
                },
            )
            entry["seed_entities"].add(record.get("seed_entity"))
            entry["nodes"].update(record.get("entities", []))
            entry["relationships"].extend(record.get("relationships", []))
            current_metadata = entry["metadata"]
            new_metadata = record.get("metadata") or {}
            for key, value in new_metadata.items():
                # Preserve the first non-empty metadata value.
                current_metadata.setdefault(key, value)

        context: List[Dict[str, object]] = []
        for payload in aggregated.values():
            relationships = [
                rel
                for rel in payload["relationships"]
                if rel and rel.get("start") is not None and rel.get("end") is not None
            ]
            deduped = {(rel["type"], rel["start"], rel["end"]): rel for rel in relationships}
            payload["relationships"] = list(deduped.values())
            payload["nodes"] = sorted(filter(None, payload["nodes"]))
            payload["seed_entities"] = sorted(filter(None, payload["seed_entities"]))
            context.append(payload)

        return context

    async def _acquire_lock(self, doc_id: str) -> asyncio.Lock:
        async with self._lock_guard:
            lock = self._document_locks.get(doc_id)
            if lock is None:
                lock = asyncio.Lock()
                self._document_locks[doc_id] = lock
            return lock

    async def _release_lock(self, doc_id: str, lock: asyncio.Lock) -> None:
        async with self._lock_guard:
            current = self._document_locks.get(doc_id)
            if current is lock and not lock.locked():
                self._document_locks.pop(doc_id, None)

    @staticmethod
    async def _write_document(tx, document: Dict[str, object]) -> None:
        await tx.run(
            queries.UPSERT_DOCUMENT,
            {
                "id": document["id"],
                "title": document["title"],
                "source": document.get("source"),
                "uri": document.get("uri"),
                "tags": document.get("tags", []),
                "metadata": document.get("metadata", {}),
            },
        )

    @staticmethod
    async def _link_entities(tx, document_id: str, entities: List[Dict[str, object]]) -> None:
        await tx.run(
            queries.LINK_ENTITIES,
            {"entities": entities, "document_id": document_id},
        )


graph_manager = GraphManager()
