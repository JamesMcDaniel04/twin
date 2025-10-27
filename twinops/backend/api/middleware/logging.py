"""Request/response logging middleware."""

from __future__ import annotations

import logging
import time
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("twinops.api")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Structured logging for inbound HTTP requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "request.completed",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client": request.client.host if request.client else None,
            },
        )

        return response
