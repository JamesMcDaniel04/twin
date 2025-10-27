"""Simple Redis-backed rate limiting middleware."""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from backend.core.database import database_manager


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce a basic rate limit per client IP."""

    def __init__(self, app, *, requests: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.requests = requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "anonymous"
        redis = database_manager.redis

        if redis is None:
            return await call_next(request)

        bucket = f"ratelimit:{client_ip}"
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
        return response
