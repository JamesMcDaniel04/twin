"""Administrative endpoints for TwinOps."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter

from backend.core.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def healthcheck() -> Dict[str, str]:
    """Liveness probe."""

    return {"status": "ok", "environment": settings.ENVIRONMENT}


@router.get("/config")
async def configuration_snapshot() -> Dict[str, str]:
    """Return a limited configuration snapshot for admins."""

    return {
        "api_title": settings.API_TITLE,
        "environment": settings.ENVIRONMENT,
        "neo4j_uri": str(settings.NEO4J_URI),
        "pinecone_index": settings.PINECONE_INDEX,
    }
