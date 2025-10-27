"""GitHub ingestion worker for repository documentation."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from backend.core.config import settings
from backend.knowledge.ingestion.workers.base import BaseIngestionWorker

logger = logging.getLogger(__name__)


class GitHubIngestionWorker(BaseIngestionWorker):
    source = "github"

    def __init__(self, *, files: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.files = files or ["README.md", "docs/README.md"]

    async def run(self) -> None:
        repos = settings.GITHUB_REPOS
        if not repos:
            logger.warning("Skipping GitHub ingestion; GITHUB_REPOS not configured.")
            return

        headers = {"Accept": "application/vnd.github+json"}
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            for repo in repos:
                await self._ingest_repository(client, repo)

    async def _ingest_repository(self, client: httpx.AsyncClient, repo: str) -> None:
        owner_repo = repo.strip()
        if "/" not in owner_repo:
            logger.warning("Invalid repository format '%s'; expected owner/repo.", owner_repo)
            return

        for path in self.files:
            url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
            response = await client.get(url)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            payload = response.json()
            await self._ingest_file(owner_repo, path, payload)

    async def _ingest_file(self, repo: str, path: str, payload: dict[str, Any]) -> None:
        encoded = payload.get("content")
        if not encoded:
            return

        content = base64.b64decode(encoded.encode("utf-8"))
        name = payload.get("name", path.split("/")[-1])
        mime_type = "text/markdown" if name.lower().endswith(".md") else "text/plain"

        metadata = {
            "id": f"{repo}:{path}",
            "title": f"{repo}::{path}",
            "mime_type": mime_type,
            "tags": ["github", repo],
            "uri": payload.get("html_url"),
        }
        await self.process_document(metadata["id"], content, metadata)
