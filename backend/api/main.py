"""FastAPI application entrypoint for TwinOps."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import admin, query, twin, workflow
from backend.api.middleware.logging import LoggingMiddleware
from backend.api.middleware.ratelimit import RateLimitMiddleware
from backend.core.config import settings
from backend.core.database import database_manager
from backend.core.exceptions import ApplicationError
from backend.integrations.slack.bot import slack_bot
from backend.orchestration.publisher import event_publisher


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize shared resources on startup and tear them down on shutdown."""

    await database_manager.initialize()
    yield
    await database_manager.close()
    await event_publisher.close()


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# Routers
app.include_router(query.router, prefix="/api")
app.include_router(twin.router, prefix="/api")
app.include_router(workflow.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.post("/slack/events")
async def slack_events(request: Request):
    """Slack event ingestion endpoint."""

    return await slack_bot.handler.handle(request)


@app.exception_handler(ApplicationError)
async def handle_application_error(_: Request, exc: ApplicationError):
    """Return standardized responses for application layer exceptions."""

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})
