"""Slack slash command implementations."""

from __future__ import annotations

from backend.orchestration.router import router


async def twin_command(body):
    text = body.get("text", "")
    channel_id = body.get("channel_id")
    user_id = body.get("user_id")
    return await router.route(channel_id, user_id, text)
