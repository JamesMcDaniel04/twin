"""Slack event handlers."""

from __future__ import annotations

from backend.orchestration.router import router


async def handle_app_mention(event: dict):
    session_id = event.get("channel")
    user_id = event.get("user")
    text = event.get("text", "")
    return await router.route(session_id, user_id, text)
