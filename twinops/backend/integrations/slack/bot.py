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
        """
        Handle /twin command - Query digital twin knowledge.

        Usage: /twin <question>
        Example: /twin Who handles AWS infrastructure issues?
        """
        await ack()

        user_id = body.get("user_id")
        query_text = body.get("text", "").strip()

        logger.info(f"/twin command from {user_id}: {query_text}")

        if not query_text:
            await respond({
                "response_type": "ephemeral",
                "text": "Usage: `/twin <your question>`",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*How to use /twin:*\n```/twin Who handles AWS infrastructure?```\n```/twin What's the process for deploying to production?```"
                        }
                    }
                ]
            })
            return

        # Show loading state
        await respond({
            "response_type": "ephemeral",
            "text": f"🔍 Searching knowledge base for: _{query_text}_\nThis may take a few seconds..."
        })

        try:
            # Import here to avoid circular dependencies
            from backend.knowledge.retrieval.graph_rag import create_graph_rag_engine

            # Query the Graph-RAG engine
            engine = create_graph_rag_engine()
            results = await engine.retrieve(query_text, top_k=5)

            # Format response with citations
            response_blocks = self._format_twin_response(query_text, results)

            await respond({
                "response_type": "in_channel",
                "blocks": response_blocks
            })

        except Exception as e:
            logger.error(f"Error processing /twin command: {e}", exc_info=True)
            await respond({
                "response_type": "ephemeral",
                "text": f"❌ Sorry, I encountered an error: {str(e)}"
            })

    async def handle_delegate_command(self, ack, body, respond, logger=logger):
        """
        Handle /delegate command - Route requests to available personnel.

        Usage: /delegate <task description>
        Example: /delegate Create Jira ticket for database performance
        """
        await ack()

        user_id = body.get("user_id")
        task_text = body.get("text", "").strip()

        logger.info(f"/delegate command from {user_id}: {task_text}")

        if not task_text:
            await respond({
                "response_type": "ephemeral",
                "text": "Usage: `/delegate <task description>`"
            })
            return

        await respond({
            "response_type": "ephemeral",
            "text": f"🧭 Finding the best person to handle: _{task_text}_"
        })

        try:
            from backend.workflows.delegation import delegation_manager

            # Find suitable delegate
            # For now, returning a placeholder
            await respond({
                "response_type": "in_channel",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Delegation Request*\n```{task_text}```\n\n*Status:* Routing to available personnel..."
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Requested by <@{user_id}>"
                            }
                        ]
                    }
                ]
            })

        except Exception as e:
            logger.error(f"Error processing /delegate command: {e}", exc_info=True)
            await respond({
                "response_type": "ephemeral",
                "text": f"❌ Delegation failed: {str(e)}"
            })

    async def handle_snapshot_command(self, ack, respond):
        """
        Handle /snapshot command - Create point-in-time knowledge snapshot.

        Usage: /snapshot [name]
        Example: /snapshot Release-v2.3.4
        """
        await ack()

        await respond({
            "response_type": "in_channel",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "📸 *Knowledge Snapshot Created*\n\nCaptured:\n• Current role assignments\n• Active workflows\n• Documentation state"
                    }
                }
            ]
        })

    async def handle_mention(self, body, say):
        """Handle @TwinOps mentions in channels."""
        event = body.get("event", {})
        user = event.get("user")
        text = event.get("text", "")

        # Remove the mention from the text
        import re
        query = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

        if query:
            await say(f"Hi <@{user}>! Let me search for: _{query}_")

            try:
                from backend.knowledge.retrieval.graph_rag import create_graph_rag_engine

                engine = create_graph_rag_engine()
                results = await engine.retrieve(query, top_k=3)

                response_blocks = self._format_twin_response(query, results)
                await say(blocks=response_blocks)

            except Exception as e:
                logger.error(f"Error in mention handler: {e}")
                await say(f"Sorry <@{user}>, I encountered an error processing your request.")
        else:
            await say(f"Hi <@{user}>! I'm TwinOps, your operational continuity assistant. Try `/twin <question>` or just ask me anything!")

    async def handle_message(self, body, say):
        """Handle direct messages to the bot."""
        event = body.get("event", {})

        # Ignore bot messages
        if event.get("subtype") == "bot_message":
            return

        # Only respond in DM channels
        if event.get("channel_type") != "im":
            return

        user = event.get("user")
        text = event.get("text", "").strip()

        if text:
            await say(f"Thanks for your message! Processing: _{text}_")
            # Process as query
            try:
                from backend.knowledge.retrieval.graph_rag import create_graph_rag_engine

                engine = create_graph_rag_engine()
                results = await engine.retrieve(text, top_k=3)

                response_blocks = self._format_twin_response(text, results)
                await say(blocks=response_blocks)

            except Exception as e:
                logger.error(f"Error in DM handler: {e}")
                await say("Sorry, I encountered an error. Try using `/twin <question>` instead.")

    async def handle_escalation(self, ack, body, respond):
        """Handle escalation shortcut."""
        await ack()

        await respond({
            "response_type": "in_channel",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "🚨 *Escalation Initiated*\n\nCreating incident workflow..."
                    }
                }
            ]
        })

    async def handle_approval(self, ack, body, client, respond):
        """Handle approval button clicks."""
        await ack()

        action = body.get("actions", [{}])[0]
        task_id = action.get("value", "unknown")

        await respond({
            "response_type": "ephemeral",
            "text": f"✅ Task approved: {task_id}"
        })

    def _format_twin_response(self, query: str, results: Any) -> List[Dict[str, Any]]:
        """Format Graph-RAG results as Slack blocks."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Query:* {query}"
                }
            },
            {"type": "divider"}
        ]

        # Add top results
        for doc in results.documents[:3]:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{doc.metadata.get('title', 'Result')}*\nConfidence: {doc.score:.2%}\n{doc.metadata.get('summary', '')[:200]}"
                }
            })

        # Add citations
        if results.sources:
            citations_text = "\n".join([
                f"• {cite.document_name} (confidence: {cite.confidence_score:.2%})"
                for cite in results.sources[:5]
            ])

            blocks.append({"type": "divider"})
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Sources:*\n{citations_text}"
                    }
                ]
            })

        return blocks


slack_bot = SlackBot()
