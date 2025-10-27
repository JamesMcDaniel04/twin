"""GitHub integration."""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from backend.core.config import settings
from backend.integrations.base import IntegrationBase

logger = logging.getLogger(__name__)


class GitHubIntegration(IntegrationBase):
    name = "github"

    async def send_event(self, payload: Dict[str, Any]) -> None:
        app_id = settings.GITHUB_APP_ID
        private_key_path = settings.GITHUB_PRIVATE_KEY_PATH

        if not app_id or not private_key_path:
            logger.warning("GitHub credentials missing; skipping event.")
            return

        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.github.com/app/installations",
                json=payload,
                headers={"Authorization": f"Bearer {app_id}"},
            )


github_integration = GitHubIntegration()
