from __future__ import annotations

from backend.core.database import database_manager
from backend.models import User


async def get_db():
    return database_manager


async def get_current_user() -> User:
    return User(
        id="system",
        email="system@twinops.local",
        name="TwinOps System",
        role="system",
        attributes={"teams": ["platform"]},
        clearance_level=10,
    )
