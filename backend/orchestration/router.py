"""Orchestration router for Slack and API requests."""

from __future__ import annotations

import logging
import textwrap
from typing import Dict, List

from backend.core.config import settings
from backend.core.exceptions import KnowledgeNotFoundError
from backend.knowledge.retrieval.graph_rag import GraphRAGEngine, RetrievalSummary, create_graph_rag_engine
from backend.knowledge.retrieval.offline import create_offline_engine
from backend.orchestration.context import context_manager
from backend.orchestration.publisher import event_publisher

logger = logging.getLogger(__name__)


class OrchestrationRouter:
    """Coordinates between Slack inputs, workflows, and knowledge systems."""

    def __init__(self) -> None:
        self.rag_engine = self._build_engine()

    def _build_engine(self) -> GraphRAGEngine:
        """Select a retrieval engine that can run in the current environment."""

        offline_requested = not settings.OPENAI_API_KEY or not settings.ENABLE_ADVANCED_GRAPH_RAG
        if offline_requested:
            logger.info("Initializing offline Graph-RAG engine for Slack orchestration.")
            return create_offline_engine()

        try:
            return create_graph_rag_engine()
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Falling back to offline Graph-RAG engine due to initialization error: %s", exc)
            return create_offline_engine()

    async def route(self, session_id: str, user_id: str, text: str) -> Dict[str, object]:
        """Process a conversational request and return the generated response."""

        window = await context_manager.get(session_id)
        window.add_message("user", text)
        await context_manager.save(window)

        try:
            summary = await self._retrieve_summary(text)
        except KnowledgeNotFoundError as exc:
            window.add_message("assistant", exc.message)
            await context_manager.save(window)
            raise

        answer = self._format_answer(summary)
        window.add_message("assistant", answer)
        await context_manager.save(window)

        citations = self._format_citations(summary)
        documents = self._serialize_documents(summary)

        experiments = None
        if summary.experiments:
            experiments = [
                {
                    "weights": experiment.weights,
                    "score": experiment.score,
                    "coverage": experiment.coverage,
                    "diversity": experiment.diversity,
                    "top_documents": experiment.top_documents,
                }
                for experiment in summary.experiments
            ]

        await event_publisher.publish(
            topic="twinops.responses",
            payload={
                "session_id": session_id,
                "user_id": user_id,
                "response": answer,
                "citations": citations,
                "documents": documents,
                "metrics": {"precision": summary.precision, "recall": summary.recall},
                "ranking": {
                    "weights": summary.weights,
                    "experiments": experiments,
                },
            },
        )

        return {
            "response": answer,
            "citations": citations,
            "documents": documents,
            "precision": summary.precision,
            "recall": summary.recall,
            "weights": summary.weights,
            "experiments": experiments,
        }

    async def _retrieve_summary(self, text: str) -> RetrievalSummary:
        try:
            return await self.rag_engine.retrieve(text, top_k=settings.VECTOR_SEARCH_TOP_K)
        except KnowledgeNotFoundError:
            raise

    def _format_answer(self, summary: RetrievalSummary) -> str:
        if not summary.documents:
            raise KnowledgeNotFoundError(
                error_code="KNOWLEDGE_NOT_FOUND",
                message="No knowledge entries matched the request.",
            )

        lines: List[str] = []
        for idx, document in enumerate(summary.documents[:3], start=1):
            title = document.metadata.get("title") or document.document_id
            snippet = document.metadata.get("summary") or document.metadata.get("chunk") or ""
            snippet = textwrap.shorten(snippet.replace("\n", " "), width=220, placeholder="…")
            lines.append(
                f"{idx}. *{title}* — {snippet} (confidence {document.confidence:.0%})"
            )

        header = "Here is what I found:"
        return f"{header}\n" + "\n".join(lines)

    def _format_citations(self, summary: RetrievalSummary) -> List[Dict[str, object]]:
        citations: List[Dict[str, object]] = []
        for document in summary.documents:
            for citation in document.citations:
                citations.append(
                    {
                        "document_id": citation.source_id,
                        "title": document.metadata.get("title") or citation.document_name,
                        "score": round(document.score, 4),
                        "link": document.metadata.get("direct_link") or "",
                        "timestamp": citation.timestamp.isoformat(),
                    }
                )
        return citations

    def _serialize_documents(self, summary: RetrievalSummary) -> List[Dict[str, object]]:
        documents: List[Dict[str, object]] = []
        for document in summary.documents:
            documents.append(
                {
                    "document_id": document.document_id,
                    "score": round(document.score, 4),
                    "confidence": round(document.confidence, 4),
                    "component_scores": {
                        key: round(value, 4)
                        for key, value in document.component_scores.items()
                    },
                    "metadata": document.metadata,
                }
            )
        return documents


router = OrchestrationRouter()
