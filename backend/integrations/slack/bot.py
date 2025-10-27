"""Async Slack bot implementation for TwinOps."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import textwrap
from typing import Any, Dict, List, Optional, Tuple

from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from backend.core.config import settings
from backend.core.exceptions import KnowledgeNotFoundError
from backend.orchestration.router import router as orchestration_router
from backend.orchestration.session import SessionState, session_store

logger = logging.getLogger(__name__)


class SlackBot:
    """Encapsulates Slack Bolt app configuration, session management, and handlers."""

    def __init__(self) -> None:
        self.app = AsyncApp(token=settings.SLACK_BOT_TOKEN, signing_secret=settings.SLACK_SIGNING_SECRET)
        self.handler = AsyncSlackRequestHandler(self.app)
        self.socket_mode_handler: Optional[AsyncSocketModeHandler] = None
        self._socket_task: Optional[asyncio.Task] = None

        if settings.SLACK_APP_TOKEN:
            self.socket_mode_handler = AsyncSocketModeHandler(self.app, settings.SLACK_APP_TOKEN)

        self.register_handlers()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_socket_mode(self) -> None:
        if not self.socket_mode_handler or self._socket_task:
            return
        logger.info("Starting Slack socket mode listener")
        self._socket_task = asyncio.create_task(self.socket_mode_handler.start_async())

    async def stop_socket_mode(self) -> None:
        if self.socket_mode_handler:
            await self.socket_mode_handler.close()
        if self._socket_task:
            self._socket_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._socket_task
            self._socket_task = None

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handlers(self) -> None:
        """Register slash commands, events, and interactive components."""

        self.app.command("/twin")(self.handle_twin_command)
        self.app.command("/delegate")(self.handle_delegate_command)
        self.app.command("/snapshot")(self.handle_snapshot_command)

        self.app.event("app_mention")(self.handle_mention)
        self.app.event("message")(self.handle_message)

        self.app.shortcut("escalate_issue")(self.handle_escalation)
        self.app.action("approve_task")(self.handle_approval)

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    async def handle_twin_command(self, ack, body, respond):
        await ack()
        channel_id = body.get("channel_id")
        user_id = body.get("user_id")
        text = (body.get("text") or "").strip()

        if not text:
            await respond(
                {
                    "response_type": "ephemeral",
                    "text": "Usage: `/twin <your question>`\nTry `/twin Who owns the production deploy pipeline?`",
                }
            )
            return

        await respond(
            {
                "response_type": "ephemeral",
                "text": f"🔍 Searching TwinOps knowledge base for _{text}_ …",
            }
        )

        session_id, _ = await self._ensure_session(channel_id, user_id)
        await self._dispatch_query(
            respond,
            session_id,
            user_id,
            text,
            response_mode="in_channel",
        )

    async def handle_delegate_command(self, ack, body, respond):
        await ack()
        user_id = body.get("user_id")
        task_text = (body.get("text") or "").strip()

        if not task_text:
            await respond({"response_type": "ephemeral", "text": "Usage: `/delegate <task description>`"})
            return

        await respond(
            {
                "response_type": "in_channel",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Delegation Request*\n```{task_text}```\n\nRouting to available personnel …",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"Requested by <@{user_id}>"},  # type: ignore[dict-item]
                        ],
                    },
                ],
            }
        )

    async def handle_snapshot_command(self, ack, respond):
        await ack()
        await respond(
            {
                "response_type": "in_channel",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                "📸 *Knowledge Snapshot Triggered*\n"
                                "Capturing current role assignments, active workflows, and documentation state."
                            ),
                        },
                    }
                ],
            }
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def handle_mention(self, body, say):
        event = body.get("event", {})
        channel_id = event.get("channel")
        user_id = event.get("user")
        text = (event.get("text") or "")
        query = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

        if not query:
            await say("Hi! Ask me a question about your operational knowledge base.")
            return

        await say(f"🔎 Working on that, <@{user_id}> …")
        session_id, _ = await self._ensure_session(channel_id, user_id)
        await self._dispatch_query(say, session_id, user_id, query)

    async def handle_message(self, body, say):
        event = body.get("event", {})
        if event.get("subtype") == "bot_message":
            return
        channel_id = event.get("channel")
        user_id = event.get("user")
        text = (event.get("text") or "").strip()
        if not text:
            return
        session_id, _ = await self._ensure_session(channel_id, user_id)
        await self._dispatch_query(say, session_id, user_id, text)

    # ------------------------------------------------------------------
    # Interactive components
    # ------------------------------------------------------------------

    async def handle_escalation(self, ack, body, respond):
        await ack()
        await respond({"response_type": "ephemeral", "text": "🚨 Escalation workflow queued. Stay tuned!"})

    async def handle_approval(self, ack, body, respond):
        await ack()
        action = body.get("actions", [{}])[0]
        task_id = action.get("value", "unknown")
        await respond(f"✅ Approval recorded for task `{task_id}`")

    # ------------------------------------------------------------------
    # Kafka integration
    # ------------------------------------------------------------------

    async def dispatch_async_response(self, payload: Dict[str, Any]) -> None:
        """Send asynchronous responses produced by background workers."""

        session_id = payload.get("session_id")
        response = payload.get("response")
        citations = payload.get("citations", [])
        documents = payload.get("documents", [])

        channel_id, _ = self._decode_session_id(session_id)
        if not channel_id or not response:
            logger.warning("Unable to dispatch async response: payload=%s", payload)
            return

        ranking = payload.get("ranking") or {}
        blocks = self._build_response_blocks(response, citations, documents, ranking.get("weights"))
        try:
            await self.app.client.chat_postMessage(channel=channel_id, text=response, blocks=blocks)
        except Exception as exc:  # pragma: no cover - Slack API errors
            logger.error("Failed to post async Slack message: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch_query(
        self,
        responder,
        session_id: str,
        user_id: str,
        text: str,
        *,
        response_mode: Optional[str] = None,
    ) -> None:
        try:
            result = await orchestration_router.route(session_id=session_id, user_id=user_id, text=text)
        except KnowledgeNotFoundError as exc:
            await self._emit_message(
                responder,
                text=f"🙇 Sorry, I couldn't find anything relevant.\n```{exc.message}```",
                response_mode="ephemeral" if response_mode else None,
            )
            return
        except Exception as exc:
            logger.exception("Slack query failed: %s", exc)
            await self._emit_message(
                responder,
                text="⚠️ Something went wrong. Try again shortly.",
                response_mode="ephemeral" if response_mode else None,
            )
            return

        blocks = self._build_response_blocks(
            result["response"],
            result.get("citations", []),
            result.get("documents", []),
            result.get("weights"),
        )
        await self._emit_message(
            responder,
            text=result["response"],
            blocks=blocks,
            response_mode=response_mode,
        )

    async def _ensure_session(self, channel_id: str, user_id: str) -> Tuple[str, SessionState]:
        session_id = f"slack:{channel_id}:{user_id}"
        state = await session_store.load(session_id)
        if state is None:
            state = SessionState(session_id=session_id, user_id=user_id)
            await session_store.save(state)
        return session_id, state

    def _build_response_blocks(
        self,
        answer: str,
        citations: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
        weights: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": answer},
            }
        ]

        if citations:
            blocks.append({"type": "divider"})
            for citation in citations[:5]:
                title = citation.get("title") or citation.get("document_id")
                link = citation.get("link")
                score = citation.get("score")
                details = f"*{title}*"
                if link:
                    details = f"<{link}|{title}>"
                if score is not None:
                    details += f" _(score: {score:.2f})_"
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": details}})

        if documents:
            weights = weights or {"graph": 0.35, "vector": 0.5, "text": 0.15}
            top = documents[0]
            preview = (top.get("metadata", {}) or {}).get("chunk") or ""
            if preview:
                preview = textwrap.shorten(preview.replace("\n", " "), width=190, placeholder="…")
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f"Snippet: {preview}"}],  # type: ignore[dict-item]
                    }
                )

            breakdown_lines: List[str] = []
            for idx, doc in enumerate(documents[:3], start=1):
                metadata = doc.get("metadata", {}) or {}
                title = metadata.get("title") or doc.get("document_id")
                component_scores = doc.get("component_scores", {}) or {}
                weighted_components = {
                    name: component_scores.get(name, 0.0) * weights.get(name, 0.0)
                    for name in weights
                }
                total = sum(weighted_components.values())
                if total > 0:
                    breakdown = ", ".join(
                        f"{name} {value / total:.0%}"
                        for name, value in weighted_components.items()
                        if value > 0
                    )
                else:
                    breakdown = ", ".join(
                        f"{name} {component_scores.get(name, 0.0):.2f}"
                        for name in weights
                        if component_scores.get(name)
                    ) or "n/a"
                confidence = doc.get("confidence")
                if confidence is None:
                    confidence = doc.get("score", 0.0)
                breakdown_lines.append(
                    f"{idx}. *{title}* — confidence {confidence:.0%} ({breakdown})"
                )

            if breakdown_lines:
                blocks.append({"type": "divider"})
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "\n".join(breakdown_lines),
                        },
                    }
                )

        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Generated by TwinOps"}]})  # type: ignore[dict-item]
        return blocks

    async def _emit_message(
        self,
        responder,
        *,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        response_mode: Optional[str] = None,
    ) -> None:
        payload = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        if response_mode:
            payload["response_type"] = response_mode

        try:
            await responder(**payload)
        except TypeError:
            await responder(payload)

    def _decode_session_id(self, session_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        if not session_id or not session_id.startswith("slack:"):
            return None, None
        _, channel_id, user_id = session_id.split(":", 2)
        return channel_id, user_id


slack_bot = SlackBot()
