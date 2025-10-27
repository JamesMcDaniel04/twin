"""Seed script for TwinOps test data."""

from __future__ import annotations

import asyncio
import logging

from backend.core.database import database_manager
from backend.knowledge.graph.manager import graph_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed_graph() -> None:
    document = {
        "id": "doc-sample-001",
        "title": "Incident Response Runbook",
        "source": "confluence",
        "metadata": {"classification": "public"},
    }
    entities = [
        {"id": "role-incident-commander", "name": "Incident Commander", "type": "Role"},
        {"id": "system-api-gateway", "name": "API Gateway", "type": "System"},
    ]
    await graph_manager.upsert_document(document, entities)
    logger.info("Seeded sample document and entities")


async def main() -> None:
    await database_manager.initialize()
    await seed_graph()
    await database_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
