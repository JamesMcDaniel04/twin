"""Google Workspace integration."""

from __future__ import annotations

import logging
from typing import Any, Dict

from backend.integrations.base import IntegrationBase

logger = logging.getLogger(__name__)


class GoogleWorkspaceIntegration(IntegrationBase):
    name = "google_workspace"

    async def send_event(self, payload: Dict[str, Any]) -> None:
        logger.info("Google Workspace event placeholder: %s", payload)


google_workspace_integration = GoogleWorkspaceIntegration()
