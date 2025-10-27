"""Authentication and authorization utilities."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from backend.core.config import settings

API_KEY_HEADER = APIKeyHeader(name="X-TwinOps-Key", auto_error=False)


class Principal(str):
    """Represents an authenticated principal identifier."""


async def api_key_auth(api_key: str | None = Security(API_KEY_HEADER)) -> Principal:
    """Authenticate requests using an API key header."""

    if settings.ENVIRONMENT == "development" and not settings.SECRET_KEY:
        return Principal("development")

    if not api_key or api_key != settings.SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")

    return Principal("api-key")


def require_principal(principal: Principal = Depends(api_key_auth)) -> Principal:
    return principal
