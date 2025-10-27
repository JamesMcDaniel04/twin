from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

from backend.core.database import database_manager
from backend.core.exceptions import KnowledgeNotFoundError
from backend.knowledge.retrieval.citations import Citation
from backend.knowledge.retrieval.ranker import HybridRanker
from backend.knowledge.vector.embeddings import EmbeddingGenerator
from backend.knowledge.vector.search import VectorSearchMatch, VectorSearchService


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
    metadata: Dict[str, Any]
    citations: List[Citation]


@dataclass
class RetrievalSummary:
    documents: List[RetrievalDocument]
    precision: float
    recall: float
    sources: List[Citation]


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
    ) -> None:
        self.graph_provider = graph_provider
        self.vector_search = vector_search
        self.embedding_generator = embedding_generator
        self.text_retriever = text_retriever or _DefaultTextRetriever()
        self.ranker = ranker or HybridRanker()
        self.weights = weights or {"graph": 0.35, "vector": 0.5, "text": 0.15}

    async def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalSummary:
        graph_context = await self.graph_provider.expand(query)
        embedding = await self._embed_query(query)
        vector_results = await self.vector_search.search(embedding, top_k=top_k)
        text_results = await self.text_retriever.search(query, graph_context)
        ranked = self.ranker.rank(graph_context, _prepare_vector_payload(vector_results), text_results, self.weights)

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
        )

    async def vector_only(self, query: str, *, top_k: int = 5) -> RetrievalSummary:
        embedding = await self._embed_query(query)
        vector_results = await self.vector_search.search(embedding, top_k=top_k)
        payload = _prepare_vector_payload(vector_results)
        documents = self._build_documents(payload)
        precision, recall = self._calculate_metrics(documents, [])
        citations = [citation for doc in documents for citation in doc.citations]
        return RetrievalSummary(documents=documents, precision=precision, recall=recall, sources=citations)

    async def _embed_query(self, query: str) -> List[float]:
        embeddings = await self.embedding_generator.generate([query])
        if not embeddings:
            return []
        return embeddings[0]

    def _build_documents(self, ranked_payload: List[Dict[str, Any]]) -> List[RetrievalDocument]:
        documents: List[RetrievalDocument] = []
        for item in ranked_payload:
            score = float(item.get("score", 0.0))
            if score <= 0.05:
                continue
            metadata = item.get("metadata", {})
            document_id = item.get("document_id") or metadata.get("document_id") or f"doc-{len(documents)}"
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
        driver = database_manager.neo4j
        if driver is None:
            return []

        cypher = """
        MATCH (entity:Entity)-[:MENTIONS]->(doc:Document)
        WHERE toLower(entity.name) CONTAINS toLower($query)
           OR toLower(doc.title) CONTAINS toLower($query)
        RETURN doc.id AS document_id,
               doc.title AS title,
               doc.source AS source,
               collect(entity.name) AS entities
        LIMIT 25
        """
        async with driver.session() as session:
            result = await session.run(cypher, {"query": query})
            records = await result.data()

        context = []
        for record in records:
            context.append(
                {
                    "document_id": record["document_id"],
                    "nodes": record["entities"],
                    "metadata": {
                        "title": record["title"],
                        "source": record["source"],
                        "summary": ", ".join(record["entities"]),
                    },
                }
            )
        return context


def create_graph_rag_engine(
    *,
    graph_provider: Optional[GraphContextProvider] = None,
    vector_search: Optional[VectorSearchService] = None,
    embedding_generator: Optional[EmbeddingGenerator] = None,
    text_retriever: Optional[TextRetriever] = None,
    ranker: Optional[HybridRanker] = None,
    weights: Optional[Dict[str, float]] = None,
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
    )


async def vector_search(query: str, *, top_k: int = 5, engine: Optional[GraphRAGEngine] = None) -> RetrievalSummary:
    rag_engine = engine or create_graph_rag_engine()
    return await rag_engine.vector_only(query, top_k=top_k)
