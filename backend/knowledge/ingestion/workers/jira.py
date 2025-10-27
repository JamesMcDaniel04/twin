"""Jira ingestion worker that synchronises issues into the knowledge base."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from backend.core.config import settings
from backend.knowledge.ingestion.workers.base import BaseIngestionWorker

logger = logging.getLogger(__name__)


class JiraIngestionWorker(BaseIngestionWorker):
    source = "jira"

    def __init__(self, jql: Optional[str] = None, *, max_results: int = 50, expand: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.jql = jql or "order by created desc"
        self.max_results = max_results
        self.expand = expand or "renderedFields"

    async def run(self) -> None:
        if not (settings.JIRA_BASE_URL and settings.JIRA_EMAIL and settings.JIRA_API_TOKEN):
            logger.warning("Skipping Jira ingestion; credentials not configured.")
            return

        auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        url = f"{settings.JIRA_BASE_URL}/rest/api/3/search"

        params = {
            "jql": self.jql,
            "maxResults": self.max_results,
            "expand": self.expand,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params, auth=auth)
            response.raise_for_status()
            data = response.json()

        issues = data.get("issues", [])
        logger.info("Fetched %s Jira issues for ingestion.", len(issues))

        for issue in issues:
            await self._ingest_issue(issue)

    async def _ingest_issue(self, issue: Dict[str, Any]) -> None:
        issue_id = issue.get("id")
        if not issue_id:
            return

        fields = issue.get("fields", {})
        rendered = issue.get("renderedFields", {})

        description_html = rendered.get("description") or ""
        summary = fields.get("summary") or "Untitled Issue"
        status = (fields.get("status") or {}).get("name", "Unknown")
        project_key = (fields.get("project") or {}).get("key", "UNKNOWN")

        metadata = {
            "id": issue_id,
            "title": summary,
            "mime_type": "text/html" if description_html else "text/plain",
            "tags": [status, project_key, *(label for label in fields.get("labels", []) if label)],
            "uri": f"{settings.JIRA_BASE_URL}/browse/{issue.get('key')}",
        }

        content = description_html.encode("utf-8") if description_html else summary.encode("utf-8")
        await self.process_document(issue_id, content, metadata)
