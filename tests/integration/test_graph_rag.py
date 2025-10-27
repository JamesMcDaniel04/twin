import pytest

from backend.knowledge.retrieval.graph_rag import GraphRAGEngine, vector_search
from backend.knowledge.retrieval.ranker import HybridRanker
from backend.knowledge.vector.search import VectorSearchMatch


class StubEmbeddingGenerator:
    async def generate(self, chunks):
        vectors = []
        for chunk in chunks:
            vectors.append([float(len(chunk)) % 7, 0.5])
        return vectors


class StubGraphProvider:
    async def expand(self, query):
        return [
            {
                "document_id": "doc-aws",
                "nodes": ["AWS", "Infrastructure"],
                "nodes_relevant": ["doc-aws"],
                "metadata": {
                    "title": "AWS Ownership",
                    "summary": "Infra team owns AWS operations.",
                    "direct_link": "https://example.com/aws",
                    "page_number": 3,
                },
            }
        ]


class StubTextRetriever:
    async def search(self, query, context):
        return [
            {
                "document_id": "doc-aws",
                "score": 0.65,
                "metadata": context[0]["metadata"],
            }
        ]


class StubVectorSearch:
    async def search(self, embedding, top_k=5, filter=None):
        return [
            VectorSearchMatch(
                document_id="doc-aws",
                score=0.62,
                metadata={
                    "title": "AWS Ownership",
                    "summary": "Infra team owns AWS operations.",
                    "direct_link": "https://example.com/aws",
                    "page_number": 3,
                },
            ),
            VectorSearchMatch(
                document_id="doc-unrelated",
                score=0.60,
                metadata={
                    "title": "HR Policies",
                    "summary": "Human resources policies unrelated to AWS.",
                    "direct_link": "https://example.com/hr",
                    "page_number": 10,
                },
            ),
        ]


@pytest.mark.asyncio
async def test_hybrid_retrieval():
    query = "Who handles AWS infrastructure?"

    engine = GraphRAGEngine(
        graph_provider=StubGraphProvider(),
        vector_search=StubVectorSearch(),
        embedding_generator=StubEmbeddingGenerator(),
        text_retriever=StubTextRetriever(),
        ranker=HybridRanker(),
        weights={"graph": 0.6, "vector": 0.3, "text": 0.1},
    )

    vector_only_results = await vector_search(query, engine=engine)
    graph_rag_results = await engine.retrieve(query)

    assert graph_rag_results.precision > vector_only_results.precision
    assert graph_rag_results.sources
    for citation in graph_rag_results.sources:
        assert citation.direct_link
