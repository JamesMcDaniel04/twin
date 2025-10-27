"""Caching utilities for orchestration layer."""

from __future__ import annotations

import json
from typing import Any, Optional

from backend.core.database import database_manager


class Cache:
    """Wrapper around Redis for simple JSON caching."""

    async def get(self, key: str) -> Optional[Any]:
        redis = database_manager.redis
        if redis is None:
            return None
        value = await redis.get(key)
        return json.loads(value) if value else None

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        redis = database_manager.redis
        if redis is None:
            return
        await redis.set(key, json.dumps(value), ex=ttl)

    async def delete(self, key: str) -> None:
        redis = database_manager.redis
        if redis is None:
            return
        await redis.delete(key)


cache = Cache()
