"""Workflow activity implementations."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def notify_slack(payload: Dict[str, Any]) -> None:
    """Stub activity to notify Slack channel."""

    logger.info("Notifying Slack: %s", payload)


async def update_jira_ticket(payload: Dict[str, Any]) -> None:
    """Stub activity to update Jira issues."""

    logger.info("Updating Jira ticket: %s", payload)


async def persist_snapshot(payload: Dict[str, Any]) -> None:
    """Stub activity to persist a knowledge snapshot."""

    logger.info("Persisting snapshot: %s", payload)
