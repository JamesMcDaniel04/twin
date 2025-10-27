"""Simple Redis-backed rate limiting middleware."""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from backend.core.database import database_manager
from backend.core.exceptions import UnauthorizedError
from backend.core.security import verify_access_token


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce a basic rate limit per client IP."""

    def __init__(self, app, *, requests: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.requests = requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        identifier = self._derive_identifier(request)
        redis = database_manager.redis

        if redis is None:
            return await call_next(request)

        bucket = f"ratelimit:{identifier}"
        current_ts = int(time.time())

        ttl = await redis.ttl(bucket)
        remaining = await redis.incr(bucket)

        if ttl == -1:
            await redis.expire(bucket, self.window_seconds)

        if remaining == 1:
            await redis.expire(bucket, self.window_seconds)

        if remaining > self.requests:
            retry_after = ttl if ttl > 0 else self.window_seconds
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests)
        response.headers["X-RateLimit-Remaining"] = str(max(self.requests - remaining, 0))
        response.headers["X-RateLimit-Key"] = identifier
        return response

    def _derive_identifier(self, request: Request) -> str:
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"api:{api_key}"

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                payload = verify_access_token(token)
                subject = payload.get("sub", "anonymous")
                org = payload.get("org") or payload.get("tenant")
                if org:
                    return f"user:{org}:{subject}"
                return f"user:{subject}"
            except UnauthorizedError:
                return f"token:{hash(token)}"

        user = getattr(request.state, "user", None)
        if user and getattr(user, "id", None):
            org = None
            attributes = getattr(user, "attributes", {})
            if isinstance(attributes, dict):
                org = attributes.get("org") or attributes.get("tenant")
            if org:
                return f"user:{org}:{user.id}"
            return f"user:{user.id}"

        client_ip = request.client.host if request.client else "anonymous"
        return f"ip:{client_ip}"
