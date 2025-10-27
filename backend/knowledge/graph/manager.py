"""Graph operations manager."""

from __future__ import annotations

import logging
from typing import Dict, List

from neo4j import AsyncSession

from backend.core.database import database_manager
from backend.knowledge.graph import queries

logger = logging.getLogger(__name__)


class GraphManager:
    """High-level graph operations for knowledge ingestion."""

    async def upsert_document(self, document: Dict[str, object], entities: List[Dict[str, object]]) -> None:
        driver = database_manager.neo4j
        if driver is None:
            logger.warning("Neo4j driver not initialized; skipping graph update.")
            return

        async with driver.session() as session:  # type: AsyncSession
            await session.execute_write(
                lambda tx: tx.run(
                    queries.UPSERT_DOCUMENT,
                    {
                        "id": document["id"],
                        "title": document["title"],
                        "source": document["source"],
                        "uri": document.get("uri"),
                        "tags": document.get("tags", []),
                        "metadata": document.get("metadata", {}),
                    },
                )
            )
            if entities:
                await session.execute_write(
                    lambda tx: tx.run(
                        queries.LINK_ENTITY,
                        {"entities": entities, "document_id": document["id"]},
                    )
                )


graph_manager = GraphManager()
