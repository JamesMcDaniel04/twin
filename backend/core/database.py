"""Database connectivity layer for TwinOps."""

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncDriver, AsyncGraphDatabase
from pinecone import Pinecone

from backend.core.config import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Lazily establishes connections to required datastores."""

    def __init__(self) -> None:
        self.neo4j: Optional[AsyncDriver] = None
        self.pinecone: Optional[Pinecone] = None
        self.index = None
        self.redis: Optional[redis.Redis] = None
        self.mongodb: Optional[AsyncIOMotorClient] = None

    async def initialize(self) -> None:
        """Connect to all backing services."""

        logger.info("Initializing TwinOps database manager")

        # Neo4j connection
        self.neo4j = AsyncGraphDatabase.driver(
            str(settings.NEO4J_URI),
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )

        # Pinecone initialization
        self.pinecone = Pinecone(api_key=settings.PINECONE_API_KEY)
        self.index = self.pinecone.Index(settings.PINECONE_INDEX)

        # Redis connection
        self.redis = await redis.from_url(str(settings.REDIS_URL), decode_responses=True)

        # MongoDB for document storage
        self.mongodb = AsyncIOMotorClient(str(settings.MONGODB_URL))

        logger.info("Database manager initialized")

    async def close(self) -> None:
        """Tear down connections gracefully."""

        logger.info("Closing database connections")

        if self.neo4j is not None:
            await self.neo4j.close()
            self.neo4j = None

        if self.redis is not None:
            await self.redis.close()
            self.redis = None

        if self.mongodb is not None:
            self.mongodb.close()
            self.mongodb = None

        self.index = None
        self.pinecone = None


# Singleton instance used by the service container
database_manager = DatabaseManager()
