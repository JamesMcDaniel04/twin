from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

from backend.core.exceptions import KnowledgeNotFoundError
from backend.knowledge.graph.manager import graph_manager
from backend.knowledge.retrieval.citations import Citation
from backend.knowledge.retrieval.feedback import FeedbackManager, FeedbackSignal
from backend.knowledge.retrieval.ranker import HybridRanker, RankingExperimentResult
from backend.knowledge.vector.embeddings import EmbeddingGenerator
from backend.knowledge.vector.search import VectorSearchMatch, VectorSearchService

logger = logging.getLogger(__name__)

class GraphContextProvider(Protocol):
    async def expand(self, query: str) -> List[Dict[str, Any]]:
        ...


class TextRetriever(Protocol):
    async def search(self, query: str, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ...


@dataclass
class RetrievalDocument:
    document_id: str
    score: float
    confidence: float
    component_scores: Dict[str, float]
    metadata: Dict[str, Any]
    citations: List[Citation]


@dataclass
class RetrievalSummary:
    documents: List[RetrievalDocument]
    precision: float
    recall: float
    sources: List[Citation]
    weights: Dict[str, float]
    experiments: Optional[List[RankingExperimentResult]] = None


class GraphRAGEngine:
    """Hybrid retrieval engine combining graph traversal with semantic search."""

    def __init__(
        self,
        *,
        graph_provider: GraphContextProvider,
        vector_search: VectorSearchService,
        embedding_generator: EmbeddingGenerator,
        text_retriever: Optional[TextRetriever] = None,
        ranker: Optional[HybridRanker] = None,
        weights: Optional[Dict[str, float]] = None,
        feedback_manager: Optional[FeedbackManager] = None,
    ) -> None:
        self.graph_provider = graph_provider
        self.vector_search = vector_search
        self.embedding_generator = embedding_generator
        self.text_retriever = text_retriever or _DefaultTextRetriever()
        self.ranker = ranker or HybridRanker(default_weights=weights)
        if weights and ranker:
            self.ranker.update_default_weights(weights)
        self.feedback_manager = feedback_manager or FeedbackManager()
        self._experiment_interval = 25
        self._query_count = 0
        self._last_experiments: List[RankingExperimentResult] = []

    async def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalSummary:
        graph_context = await self.graph_provider.expand(query)
        embedding = await self._embed_query(query)
        vector_results = await self.vector_search.search(embedding, top_k=top_k)
        vector_payload = _prepare_vector_payload(vector_results)
        text_results = await self.text_retriever.search(query, graph_context)
        ranked = self.ranker.rank(graph_context, vector_payload, text_results)

        await self._maybe_run_weight_experiments(graph_context, vector_payload, text_results, top_k=top_k)

        if not ranked:
            raise KnowledgeNotFoundError(
                error_code="KNOWLEDGE_NOT_FOUND",
                message=f"No relevant knowledge found for query '{query}'",
                details={"query": query},
            )

        documents = self._build_documents(ranked)
        precision, recall = self._calculate_metrics(documents, graph_context)
        citations = [citation for doc in documents for citation in doc.citations]

        return RetrievalSummary(
            documents=documents,
            precision=precision,
            recall=recall,
            sources=citations,
            weights=self.ranker.weights,
            experiments=self._last_experiments or None,
        )

    async def vector_only(self, query: str, *, top_k: int = 5) -> RetrievalSummary:
        embedding = await self._embed_query(query)
        vector_results = await self.vector_search.search(embedding, top_k=top_k)
        payload = _prepare_vector_payload(vector_results)
        documents = self._build_documents(payload)
        precision, recall = self._calculate_metrics(documents, [])
        citations = [citation for doc in documents for citation in doc.citations]
        return RetrievalSummary(
            documents=documents,
            precision=precision,
            recall=recall,
            sources=citations,
            weights=self.ranker.weights,
        )

    async def _embed_query(self, query: str) -> List[float]:
        embeddings = await self.embedding_generator.generate([query])
        if not embeddings:
            return []
        return embeddings[0]

    async def record_feedback(self, signal: FeedbackSignal) -> None:
        await self.feedback_manager.record(signal)
        recommended = await self.feedback_manager.recommend_weights(self.ranker.weights)
        self.ranker.update_default_weights(recommended)

    async def _maybe_run_weight_experiments(
        self,
        graph_context: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        text_results: List[Dict[str, Any]],
        *,
        top_k: int,
    ) -> None:
        self._query_count += 1
        if self._query_count % self._experiment_interval != 0:
            return
        try:
            self._last_experiments = self.ranker.run_experiments(
                graph_context,
                vector_results,
                text_results,
                top_k=top_k,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to execute ranking weight experiments: %s", exc)

    def _build_documents(self, ranked_payload: List[Dict[str, Any]]) -> List[RetrievalDocument]:
        documents: List[RetrievalDocument] = []
        for item in ranked_payload:
            score = float(item.get("score", 0.0))
            confidence = float(item.get("confidence", 0.0))
            if score <= 0.05 and confidence <= 0.1:
                continue
            metadata = item.get("metadata", {})
            document_id = item.get("document_id") or metadata.get("document_id") or f"doc-{len(documents)}"
            component_scores = item.get("component_scores", {})
            metadata = dict(metadata)
            metadata.setdefault("confidence", confidence)
            metadata.setdefault("confidence_breakdown", component_scores)
            citation = Citation(
                source_id=document_id,
                document_name=metadata.get("title", "Unknown"),
                page_number=metadata.get("page_number"),
                confidence_score=score,
                timestamp=datetime.utcnow(),
                direct_link=metadata.get("direct_link", ""),
            )
            documents.append(
                RetrievalDocument(
                    document_id=document_id,
                    score=score,
                    confidence=confidence,
                    component_scores=component_scores,
                    metadata=metadata,
                    citations=[citation],
                )
            )
        return documents

    def _calculate_metrics(
        self,
        documents: Sequence[RetrievalDocument],
        graph_context: Sequence[Dict[str, Any]],
    ) -> tuple[float, float]:
        if not documents:
            return 0.0, 0.0

        relevant_documents = {
            node_id
            for context in graph_context
            for node_id in context.get("nodes_relevant", context.get("nodes", []))
        }
        if not relevant_documents:
            return 0.0, 0.0

        hits = sum(1 for doc in documents if doc.document_id in relevant_documents)
        precision = hits / len(documents)
        recall = hits / len(relevant_documents) if relevant_documents else 0.0
        return float(precision), float(recall)


def _prepare_vector_payload(matches: Iterable[VectorSearchMatch]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for match in matches:
        payload.append(
            {
                "document_id": match.document_id,
                "score": match.score,
                "metadata": match.metadata,
            }
        )
    return payload


class _DefaultTextRetriever(TextRetriever):
    async def search(self, query: str, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        await asyncio.sleep(0)
        results: List[Dict[str, Any]] = []
        normalized_query = query.lower()
        for ctx in context:
            metadata = ctx.get("metadata", {})
            summary = metadata.get("summary", "")
            if normalized_query in summary.lower():
                results.append(
                    {
                        "document_id": ctx.get("document_id"),
                        "score": 0.6,
                        "metadata": metadata,
                    }
                )
        return results


class _Neo4jGraphProvider(GraphContextProvider):
    async def expand(self, query: str) -> List[Dict[str, Any]]:
        try:
            context = await graph_manager.expand_context(query)
        except Exception as exc:  # pragma: no cover - Neo4j may be unavailable in tests
            logger.warning("Graph context expansion failed: %s", exc)
            return []

        normalized_context: List[Dict[str, Any]] = []
        for record in context:
            metadata = record.get("metadata", {}) or {}
            if "summary" not in metadata:
                metadata["summary"] = ", ".join(record.get("nodes", []))
            metadata.setdefault("title", record.get("title"))
            metadata.setdefault("source", record.get("source"))
            normalized_context.append(
                {
                    "document_id": record.get("document_id"),
                    "nodes": record.get("nodes", []),
                    "seed_entities": record.get("seed_entities", []),
                    "relationships": record.get("relationships", []),
                    "metadata": metadata,
                }
            )
        return normalized_context


def create_graph_rag_engine(
    *,
    graph_provider: Optional[GraphContextProvider] = None,
    vector_search: Optional[VectorSearchService] = None,
    embedding_generator: Optional[EmbeddingGenerator] = None,
    text_retriever: Optional[TextRetriever] = None,
    ranker: Optional[HybridRanker] = None,
    weights: Optional[Dict[str, float]] = None,
    feedback_manager: Optional[FeedbackManager] = None,
) -> GraphRAGEngine:
    provider = graph_provider or _Neo4jGraphProvider()
    vector = vector_search or VectorSearchService()
    embeddings = embedding_generator or EmbeddingGenerator()
    return GraphRAGEngine(
        graph_provider=provider,
        vector_search=vector,
        embedding_generator=embeddings,
        text_retriever=text_retriever,
        ranker=ranker,
        weights=weights,
        feedback_manager=feedback_manager,
    )


async def vector_search(query: str, *, top_k: int = 5, engine: Optional[GraphRAGEngine] = None) -> RetrievalSummary:
    rag_engine = engine or create_graph_rag_engine()
    return await rag_engine.vector_only(query, top_k=top_k)
