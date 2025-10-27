"""Offline retrieval helpers shared across API and Slack fallbacks."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from backend.knowledge.retrieval.graph_rag import (
    GraphContextProvider,
    GraphRAGEngine,
    TextRetriever,
    create_graph_rag_engine,
)
from backend.knowledge.retrieval.ranker import HybridRanker
from backend.knowledge.vector.search import VectorSearchService

FALLBACK_KNOWLEDGE_BASE: List[Dict[str, Any]] = [
    {
        "document_id": "doc-aws-infra",
        "title": "AWS Infrastructure Ownership",
        "summary": "The AWS infrastructure is managed by the SRE platform team led by the Infra Lead.",
        "source": "confluence",
        "direct_link": "https://confluence.local/aws-infra",
        "entities": ["AWS", "Infrastructure", "SRE", "Infra Lead"],
        "page_number": 4,
    },
    {
        "document_id": "doc-incident-runbook",
        "title": "High Severity Incident Runbook",
        "summary": "Runbook outlining steps to mitigate high severity incidents involving core services.",
        "source": "notion",
        "direct_link": "https://notion.local/runbooks/high-sev",
        "entities": ["Incident", "Runbook", "Infra Lead"],
        "page_number": 2,
    },
    {
        "document_id": "doc-oncall-rotation",
        "title": "On-call Rotation",
        "summary": "Infra On-call rotation includes Infra Lead and SRE Backup for after-hours coverage.",
        "source": "slack",
        "direct_link": "https://slack.local/archives/oncall",
        "entities": ["On-call", "Infra Lead", "SRE Backup"],
        "page_number": 1,
    },
]


@dataclass
class LocalEmbeddingGenerator:
    """Deterministic, offline embedding generator for development and testing."""

    dimensions: int = 32

    async def generate(self, chunks: Sequence[str]) -> List[List[float]]:
        return [self._encode(chunk) for chunk in chunks]

    def encode_sync(self, text: str) -> List[float]:
        return self._encode(text)

    def _encode(self, text: str) -> List[float]:
        tokens = text.lower().split()
        vector = [0.0] * self.dimensions
        if not tokens:
            return vector

        for index, token in enumerate(tokens[: self.dimensions]):
            token_value = sum(ord(char) for char in token) % 997
            vector[index] = token_value / 997.0
        return vector


@dataclass
class InMemoryGraphProvider(GraphContextProvider):
    knowledge: Sequence[Dict[str, Any]]

    async def expand(self, query: str) -> List[Dict[str, Any]]:
        tokens = set(query.lower().split())
        context: List[Dict[str, Any]] = []
        for item in self.knowledge:
            item_tokens = set(item["summary"].lower().split()) | {entity.lower() for entity in item["entities"]}
            if tokens & item_tokens:
                context.append(
                    {
                        "document_id": item["document_id"],
                        "nodes": item["entities"],
                        "nodes_relevant": item["entities"],
                        "metadata": {
                            "title": item["title"],
                            "summary": item["summary"],
                            "source": item["source"],
                            "direct_link": item["direct_link"],
                        },
                    }
                )
        return context


@dataclass
class InMemoryTextRetriever(TextRetriever):
    knowledge: Sequence[Dict[str, Any]]

    async def search(self, query: str, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []
        for item in self.knowledge:
            if query_lower in item["summary"].lower() or any(entity.lower() in query_lower for entity in item["entities"]):
                results.append(
                    {
                        "document_id": item["document_id"],
                        "score": 0.5,
                        "metadata": {
                            "title": item["title"],
                            "summary": item["summary"],
                            "source": item["source"],
                            "direct_link": item["direct_link"],
                            "page_number": item["page_number"],
                        },
                    }
                )
        return results


def seed_vector_store(
    vector_service: VectorSearchService,
    embedding_generator: LocalEmbeddingGenerator,
    knowledge_base: Sequence[Dict[str, Any]],
) -> None:
    for item in knowledge_base:
        embedding = embedding_generator.encode_sync(f"{item['title']} {item['summary']}")
        vector_service._fallback_store[item["document_id"]] = {  # pylint: disable=protected-access
            "embedding": embedding,
            "metadata": {
                "title": item["title"],
                "summary": item["summary"],
                "direct_link": item["direct_link"],
                "source": item["source"],
                "page_number": item["page_number"],
                "chunk": textwrap.shorten(item["summary"], width=220, placeholder="…"),
            },
        }


def create_offline_engine(
    *,
    knowledge_base: Sequence[Dict[str, Any]] | None = None,
) -> GraphRAGEngine:
    knowledge = list(knowledge_base or FALLBACK_KNOWLEDGE_BASE)
    embedding = LocalEmbeddingGenerator()
    graph_provider = InMemoryGraphProvider(knowledge)
    text_retriever = InMemoryTextRetriever(knowledge)
    vector_search = VectorSearchService()
    seed_vector_store(vector_search, embedding, knowledge)

    return create_graph_rag_engine(
        graph_provider=graph_provider,
        vector_search=vector_search,
        embedding_generator=embedding,  # type: ignore[arg-type]
        text_retriever=text_retriever,
        ranker=HybridRanker(default_weights={"graph": 0.4, "vector": 0.45, "text": 0.15}),
    )
