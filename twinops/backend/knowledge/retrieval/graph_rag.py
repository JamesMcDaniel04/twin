"""Graph-RAG hybrid retrieval engine."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from elasticsearch import AsyncElasticsearch
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError

from backend.core.config import settings
from backend.core.database import database_manager
from backend.knowledge.ingestion.extractors import EntityExtractor
from backend.knowledge.retrieval.ranker import HybridRanker
from backend.knowledge.retrieval.citations import CitationBuilder
from backend.knowledge.vector.search import vector_search
from backend.models.document import Document
from backend.models.query import Query

logger = logging.getLogger(__name__)


class GraphRAGEngine:
    """Implements hybrid retrieval combining graph traversal and semantic search."""

    def __init__(self) -> None:
        self.entity_extractor = EntityExtractor()
        self.rank_engine = HybridRanker()
        self.citations = CitationBuilder()
        self.es = AsyncElasticsearch(settings.ELASTICSEARCH_URL)

    async def retrieve(self, query: Query) -> List[Dict[str, Any]]:
        # 1. Extract entities from query
        entities = await self.extract_query_entities(query.text)

        # 2. Graph traversal for context
        graph_context = await self.traverse_graph(
            entities=entities,
            max_depth=3,
            relationship_types=["OWNS_DOCUMENT", "MANAGES", "DELEGATES_TO"],
        )

        # 3. Build vector search filter from graph context
        search_filter = self.build_search_filter(graph_context)

        # 4. Semantic vector search
        vector_results = []
        if query.embedding:
            vector_results = await self.vector_search(query.embedding, filter=search_filter, top_k=20)

        # 5. Full-text search for keyword matching
        text_results = await self.text_search(query.text, filter=search_filter)

        # 6. Hybrid ranking with learned weights
        ranked_results = self.hybrid_rank(
            graph_context=graph_context,
            vector_results=vector_results,
            text_results=text_results,
            weights={"graph": 0.3, "vector": 0.5, "text": 0.2},
        )

        # 7. Add source citations
        results_with_citations = self.add_citations(ranked_results)

        return results_with_citations

    async def extract_query_entities(self, text: str) -> List[Dict[str, str]]:
        return await self.entity_extractor.extract(text)

    async def traverse_graph(self, entities, max_depth, relationship_types):
        driver = database_manager.neo4j
        if not driver:
            logger.warning("Neo4j driver not available; skipping graph traversal.")
            return []

        entity_ids = [entity.get("id", entity.get("name")) for entity in entities if entity.get("name")]
        if not entity_ids:
            return []

        rel_filter = "|".join(relationship_types)
        query = """
        MATCH (n)
        WHERE n.id IN $entity_ids OR n.name IN $entity_ids
        CALL apoc.path.expandConfig(n, {
            relationshipFilter: $rel_types,
            maxLevel: $max_depth,
            uniqueness: 'NODE_GLOBAL'
        })
        YIELD path
        RETURN path
        """

        try:
            async with driver.session() as session:
                result = await session.run(
                    query,
                    entity_ids=entity_ids,
                    rel_types=rel_filter,
                    max_depth=max_depth,
                )
                paths = await result.values()
                return [self._path_to_context(path[0]) for path in paths]
        except Neo4jError as exc:  # pragma: no cover - network errors
            logger.error("Graph traversal failed: %s", exc)
            return []

    def _path_to_context(self, path) -> Dict[str, Any]:
        nodes = [node["id"] for node in path.nodes if "id" in node]
        relationships = [rel.type for rel in path.relationships]
        return {"nodes": nodes, "relationships": relationships}

    def build_search_filter(self, graph_context: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not graph_context:
            return None
        related_nodes = {node for ctx in graph_context for node in ctx.get("nodes", [])}
        if not related_nodes:
            return None
        return {"document_id": {"$in": list(related_nodes)}}

    async def vector_search(self, query_embedding, filter, top_k):
        return await vector_search.search(query_embedding, top_k=top_k, filter=filter)

    async def text_search(self, query: str, filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {
            "query": {
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": [{"terms": {"document_id": filter["document_id"]["$in"]}}] if filter else [],
                }
            },
            "size": 20,
        }

        try:
            response = await self.es.search(index="twinops-documents", body=body)
            hits = response["hits"]["hits"]
            return [{"id": hit["_id"], "score": hit["_score"], "metadata": hit["_source"]} for hit in hits]
        except Exception as exc:  # pragma: no cover - Elasticsearch not available
            logger.error("Text search failed: %s", exc)
            return []

    def hybrid_rank(self, graph_context, vector_results, text_results, weights):
        return self.rank_engine.rank(graph_context, vector_results, text_results, weights)

    def add_citations(self, ranked_results):
        return self.citations.build(ranked_results)
