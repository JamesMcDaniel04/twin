"""Jira integration."""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from backend.core.config import settings
from backend.integrations.base import IntegrationBase

logger = logging.getLogger(__name__)


class JiraIntegration(IntegrationBase):
    name = "jira"

    def __init__(self) -> None:
        self.base_url = settings.JIRA_BASE_URL
        self.api_token = settings.JIRA_API_TOKEN

    async def send_event(self, payload: Dict[str, Any]) -> None:
        if not self.base_url or not self.api_token:
            logger.warning("Jira credentials missing; skipping event.")
            return

        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.base_url}/rest/api/3/issue",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=30,
            )


jira_integration = JiraIntegration()
