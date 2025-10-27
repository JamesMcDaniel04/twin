"""Initial setup script for TwinOps infrastructure."""

from __future__ import annotations

import asyncio
import logging

from elasticsearch import AsyncElasticsearch

from backend.core.config import settings
from backend.core.database import database_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


NEO4J_SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT role_id IF NOT EXISTS ON (r:Role) ASSERT r.id IS UNIQUE",
    "CREATE CONSTRAINT person_id IF NOT EXISTS ON (p:Person) ASSERT p.id IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS ON (d:Document) ASSERT d.id IS UNIQUE",
    "CREATE CONSTRAINT project_id IF NOT EXISTS ON (pr:Project) ASSERT pr.id IS UNIQUE",
    "CREATE CONSTRAINT system_id IF NOT EXISTS ON (s:System) ASSERT s.id IS UNIQUE",
    "CREATE INDEX role_name IF NOT EXISTS FOR (r:Role) ON (r.name)",
    "CREATE INDEX person_email IF NOT EXISTS FOR (p:Person) ON (p.email)",
    "CREATE INDEX document_source IF NOT EXISTS FOR (d:Document) ON (d.source)",
]


async def setup_neo4j() -> None:
    driver = database_manager.neo4j
    if driver is None:
        logger.error("Neo4j driver unavailable. Did initialization fail?")
        return
    async with driver.session() as session:
        for statement in NEO4J_SCHEMA_STATEMENTS:
            await session.run(statement)
            logger.info("Executed: %s", statement)


async def setup_elasticsearch() -> None:
    es = AsyncElasticsearch(settings.ELASTICSEARCH_URL)
    exists = await es.indices.exists(index="twinops-documents")
    if not exists:
        await es.indices.create(
            index="twinops-documents",
            mappings={
                "properties": {
                    "document_id": {"type": "keyword"},
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "source": {"type": "keyword"},
                }
            },
        )
        logger.info("Created Elasticsearch index twinops-documents")
    await es.close()


async def main() -> None:
    await database_manager.initialize()
    await setup_neo4j()
    await setup_elasticsearch()
    await database_manager.close()
    logger.info("TwinOps setup complete")


if __name__ == "__main__":
    asyncio.run(main())
