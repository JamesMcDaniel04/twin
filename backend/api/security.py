"""Authentication utilities for API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from backend.core.config import settings
from backend.core.exceptions import UnauthorizedError
from backend.core.security import verify_access_token
from backend.models import User

_http_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def authenticate_user(
    request: Request,
    bearer_token: Optional[HTTPAuthorizationCredentials] = Depends(_http_bearer),
    api_key: Optional[str] = Depends(_api_key_header),
) -> User:
    if bearer_token and bearer_token.credentials:
        token = bearer_token.credentials
        try:
            payload = verify_access_token(token)
        except UnauthorizedError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
        subject = payload.get("sub")
        if subject is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        user = User(
            id=subject,
            email=payload.get("email", f"{subject}@twinops.local"),
            name=payload.get("name", subject),
            role=payload.get("role", "user"),
            attributes={key: value for key, value in payload.items() if key not in {"sub", "exp", "email", "name", "role"}},
            clearance_level=int(payload.get("clearance", 0)),
        )
        request.state.user = user
        return user

    if api_key:
        user = _resolve_api_key(api_key)
        if user:
            request.state.user = user
            return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def _resolve_api_key(api_key: str) -> Optional[User]:
    key_entry = settings.API_KEYS.get(api_key)
    if not key_entry:
        return None

    return User(
        id=key_entry.get("id", api_key),
        email=key_entry.get("email", f"{api_key}@twinops.local"),
        name=key_entry.get("name", key_entry.get("id", api_key)),
        role=key_entry.get("role", "service"),
        attributes={key: value for key, value in key_entry.items() if key not in {"id", "email", "name", "role"}},
        clearance_level=int(key_entry.get("clearance", 5)),
    )


__all__ = ["authenticate_user"]
