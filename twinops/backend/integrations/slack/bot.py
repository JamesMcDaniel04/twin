"""Async Slack bot implementation for TwinOps."""

from __future__ import annotations

import logging
from typing import Any, Dict

from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

from backend.core.config import settings

logger = logging.getLogger(__name__)


class SlackBot:
    """Encapsulates Slack Bolt app configuration and handlers."""

    def __init__(self) -> None:
        self.app = AsyncApp(token=settings.SLACK_BOT_TOKEN, signing_secret=settings.SLACK_SIGNING_SECRET)
        self.handler = AsyncSlackRequestHandler(self.app)
        self.register_handlers()

    def register_handlers(self) -> None:
        """Register slash commands, events, and interactive components."""

        # Slash commands
        self.app.command("/twin")(self.handle_twin_command)
        self.app.command("/delegate")(self.handle_delegate_command)
        self.app.command("/snapshot")(self.handle_snapshot_command)

        # Events
        self.app.event("app_mention")(self.handle_mention)
        self.app.event("message")(self.handle_message)

        # Shortcuts and actions
        self.app.shortcut("escalate_issue")(self.handle_escalation)
        self.app.action("approve_task")(self.handle_approval)

    async def handle_twin_command(self, ack, body, respond, client, logger=logger):
        await ack()
        logger.info("Handling /twin command", extra={"user": body.get("user_id")})
        await respond("👥 TwinOps is creating your digital twin. This feature is under active development.")

    async def handle_delegate_command(self, ack, body, respond, logger=logger):
        await ack()
        logger.info("Handling /delegate command", extra={"user": body.get("user_id")})
        await respond("🧭 Delegation workflow queued. You will receive updates shortly.")

    async def handle_snapshot_command(self, ack, respond):
        await ack()
        await respond("📸 Snapshot captured. The knowledge graph will update momentarily.")

    async def handle_mention(self, body, say):
        user = body.get("event", {}).get("user")
        await say(f"Hi <@{user}>! I'm TwinOps, your operational continuity copilot.")

    async def handle_message(self, body, say):
        if body.get("event", {}).get("subtype") == "bot_message":
            return
        await say("To get started, try `/twin` to instantiate a digital twin.")

    async def handle_escalation(self, ack, body, respond):
        await ack()
        await respond("🚨 Escalation request received. An incident workflow is being initiated.")

    async def handle_approval(self, ack, body, client, respond):
        await ack()
        metadata: Dict[str, Any] = body.get("actions", [{}])[0].get("value", {})
        await respond(f"✅ Approval recorded for task: {metadata}")


slack_bot = SlackBot()
