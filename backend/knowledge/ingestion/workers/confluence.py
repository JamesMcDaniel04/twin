"""Confluence ingestion worker."""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from backend.core.config import settings
from backend.knowledge.ingestion.workers.base import BaseIngestionWorker

logger = logging.getLogger(__name__)


class ConfluenceIngestionWorker(BaseIngestionWorker):
    source = "confluence"

    def __init__(self, *, space_key: str | None = None, limit: int = 50, **kwargs):
        super().__init__(**kwargs)
        self.space_key = space_key
        self.limit = limit

    async def run(self) -> None:
        if not (settings.CONFLUENCE_URL and settings.CONFLUENCE_EMAIL and settings.CONFLUENCE_API_TOKEN):
            logger.warning("Skipping Confluence ingestion; credentials not configured.")
            return

        params = {
            "limit": self.limit,
            "expand": "body.storage,version",
        }
        if self.space_key:
            params["spaceKey"] = self.space_key

        url = f"{settings.CONFLUENCE_URL}/rest/api/content"
        auth = (settings.CONFLUENCE_EMAIL, settings.CONFLUENCE_API_TOKEN)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params, auth=auth)
            response.raise_for_status()
            payload = response.json()

        pages = payload.get("results", [])
        logger.info("Fetched %s Confluence pages for ingestion.", len(pages))

        for page in pages:
            await self._ingest_page(page)

    async def _ingest_page(self, page: Dict[str, Any]) -> None:
        page_id = page.get("id")
        if not page_id:
            return

        title = page.get("title") or "Untitled Page"
        body_html = ((page.get("body") or {}).get("storage") or {}).get("value", "")
        version = (page.get("version") or {}).get("number", 1)

        metadata = {
            "id": page_id,
            "title": title,
            "mime_type": "text/html",
            "tags": [f"version:{version}", "confluence"],
            "uri": f"{settings.CONFLUENCE_URL}/pages/{page_id}",
        }

        await self.process_document(page_id, body_html.encode("utf-8"), metadata)
