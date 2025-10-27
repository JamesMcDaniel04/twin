from __future__ import annotations

from fastapi import Depends, Request

from backend.api.security import authenticate_user
from backend.core.database import database_manager
from backend.models import User


async def get_db():
    return database_manager


async def get_current_user(request: Request, user: User = Depends(authenticate_user)) -> User:
    return user
