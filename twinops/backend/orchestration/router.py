"""Orchestration router for Slack and API requests."""

from __future__ import annotations

import uuid
from typing import Dict

from backend.knowledge.retrieval.graph_rag import GraphRAGEngine
from backend.models.query import Query
from backend.orchestration.context import context_manager
from backend.orchestration.publisher import event_publisher


class OrchestrationRouter:
    """Coordinates between Slack inputs, workflows, and knowledge systems."""

    def __init__(self) -> None:
        self.rag_engine = GraphRAGEngine()

    async def route(self, session_id: str, user_id: str, text: str) -> Dict[str, str]:
        """Process a conversational request and return the generated response."""

        window = await context_manager.get(session_id)
        window.add_message("user", text)
        await context_manager.save(window)

        query = Query(id=str(uuid.uuid4()), text=text)
        results = await self.rag_engine.retrieve(query)
        answer = results[0]["summary"] if results else "No relevant knowledge found."

        window.add_message("assistant", answer)
        await context_manager.save(window)

        await event_publisher.publish(
            topic="twinops.responses",
            payload={
                "session_id": session_id,
                "user_id": user_id,
                "response": answer,
                "documents": [item["document"].id for item in results],
            },
        )

        return {"response": answer, "session_id": session_id}


router = OrchestrationRouter()
